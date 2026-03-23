"""Agent loop — consumes from inbound bus, publishes to outbound."""

import asyncio
import contextvars
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .bus import InboundMessage, MessageBus, MsgType, OutboundMessage
from .compact import (
    BYTES_PER_TOKEN,
    COMPACT_TRIGGER,
    CONTEXT_WINDOW,
    KEEP_RECENT_TURNS,
    MAX_FAILURES_BEFORE_RAW,
    POST_COMPACT_TARGET,
    MemoryStore,
    compact_with_llm,
    count_recent_messages,
    estimate_tokens,
    format_token_usage,
    prune_tool_outputs,
    raw_archive,
    rebuild_history,
)
from .config import SYSTEM_PROMPT
from .session import load_last_token_usage, load_session, save_compact_event, save_full_session
from .skills import get_skills_prompt, set_group_context
from .tools import TOOL_MAP

logger = logging.getLogger(__name__)

# Shared state: last known token usage per session (read by context_status tool)
# ContextVar is async-safe — each coroutine gets its own value, no race conditions
_session_token_usage: dict[str, dict] = {}
_current_session_var: contextvars.ContextVar[str] = contextvars.ContextVar("current_session", default="")


def get_current_token_usage() -> dict:
    """Get token usage for the currently active session. Called by context_status tool."""
    return _session_token_usage.get(_current_session_var.get(), {})




def _session_key(msg: InboundMessage) -> str:
    return f"{msg.channel}_{msg.chat_id}"


def _extract_reply(response: AIMessage) -> str:
    if isinstance(response.content, str):
        return response.content
    return "\n".join(
        b["text"] for b in response.content
        if isinstance(b, dict) and b.get("type") == "text"
    )


async def _emit(bus: MessageBus, channel: str, chat_id: str, text: str, message_type: str,
                metadata: dict | None = None):
    """Emit outbound message. Sync callback fires immediately (CLI prints),
    then yields so async consumers (Telegram sender) can process."""
    bus.emit(OutboundMessage(
        channel=channel, chat_id=chat_id, text=text, message_type=message_type,
        metadata=metadata or {},
    ))
    await asyncio.sleep(0.05)  # yield for async sender loops (Telegram HTTP POST)


async def agent_loop(llm, bus: MessageBus):
    """Main loop: consume inbound messages, process, publish outbound."""
    while True:
        msg = await bus.inbound.get()
        try:
            await _process_message(llm, bus, msg)
        except Exception as e:
            await _emit(bus, msg.channel, msg.chat_id, f"Error: {e}", MsgType.ERROR)


async def _process_message(llm, bus: MessageBus, msg: InboundMessage):
    """Process one inbound message through the agent turn."""
    session_name = _session_key(msg)
    _current_session_var.set(session_name)
    set_group_context(msg.metadata.get("is_group", False))

    # Build outbound metadata for reply threading (group chats)
    out_meta = {}
    if msg.metadata.get("is_group"):
        out_meta["is_group"] = True
        out_meta["reply_to_message_id"] = msg.metadata.get("message_id")

    # Load session with offset
    prev_messages, last_consolidated = load_session(session_name)

    # Inject per-session MEMORY.md into system prompt
    memory_store = MemoryStore(session_name)
    memory_ctx = memory_store.read_memory()
    system_content = SYSTEM_PROMPT
    if memory_ctx:
        system_content += f"\n\n---\n\n## Long-term Memory\n\n{memory_ctx}"

    # Inject skill metadata (name + description only, ~2k tokens)
    is_group = msg.metadata.get("is_group", False)
    skills_ctx = get_skills_prompt(is_group=is_group)
    if skills_ctx:
        system_content += f"\n\n---\n\n{skills_ctx}"

    # Build history — prefix group messages with sender name
    user_text = msg.text
    if msg.metadata.get("is_group") and msg.metadata.get("sender_name"):
        user_text = f"[{msg.metadata['sender_name']}]: {msg.text}"

    history = [SystemMessage(content=system_content)]
    history.extend(prev_messages)
    history.append(HumanMessage(content=user_text))

    # Use last known API token count as base (accurate), only estimate the new user message.
    # Codex does the same: trust last_token_usage.total_tokens, estimate only delta items.
    # Falls back to full estimate on first-ever turn or after restart.
    stored_tokens = _session_token_usage.get(session_name, {}).get("input_tokens")
    if stored_tokens is None:
        stored_tokens = load_last_token_usage(session_name) or None
    if stored_tokens:
        new_msg_bytes = len(msg.text.encode("utf-8"))
        last_input_tokens = stored_tokens + (new_msg_bytes + BYTES_PER_TOKEN - 1) // BYTES_PER_TOKEN
    else:
        last_input_tokens = estimate_tokens(history)
    compact_failures = 0
    iteration = 0

    while True:
        iteration += 1
        await _emit(bus, msg.channel, msg.chat_id,
              f"⟳ iteration {iteration}", MsgType.THINKING, out_meta)

        # --- COMPACTION CHECK (before LLM call) ---
        if last_input_tokens > CONTEXT_WINDOW * COMPACT_TRIGGER:
            await _emit(bus, msg.channel, msg.chat_id,
                  "Compacting context...", MsgType.STATUS, out_meta)

            # Phase 1: prune old tool outputs (free)
            history, freed = prune_tool_outputs(history)
            logger.info(f"Phase 1 prune freed ~{freed} chars")

            # Phase 2: LLM compact (if still over threshold)
            if estimate_tokens(history) > CONTEXT_WINDOW * COMPACT_TRIGGER:
                try:
                    summary = await compact_with_llm(llm, history)

                    # Adaptive keep: try 3→2→1→0 turns until under POST_COMPACT_TARGET
                    target_tokens = int(CONTEXT_WINDOW * POST_COMPACT_TARGET)
                    base = rebuild_history(summary, [], system_content)
                    base_tokens = estimate_tokens(base)
                    for keep in range(KEEP_RECENT_TURNS, -1, -1):
                        recent_count = count_recent_messages(history, keep) if keep > 0 else 0
                        recent = history[-recent_count:] if recent_count > 0 else []
                        if base_tokens + estimate_tokens(recent) <= target_tokens or keep == 0:
                            history = rebuild_history(summary, recent, system_content)
                            logger.info(f"Phase 2 compact: keeping {keep} turns, {len(history)} messages")
                            break

                    # Persist memory + history
                    memory_store.write_memory(summary.memory_update)
                    memory_store.append_history(summary.history_entry)
                    save_compact_event(session_name, len(prev_messages) + last_consolidated, summary.session_summary)

                    compact_failures = 0
                except Exception as e:
                    compact_failures += 1
                    logger.warning(f"Compact failed ({compact_failures}/{MAX_FAILURES_BEFORE_RAW}): {e}")
                    if compact_failures >= MAX_FAILURES_BEFORE_RAW:
                        memory_store.append_history(raw_archive(history))
                        # Hard truncate to prevent context overflow on next LLM call
                        recent_count = count_recent_messages(history, 1)
                        recent = history[-recent_count:] if recent_count > 0 else []
                        history = [SystemMessage(content=system_content)] + recent
                        compact_failures = 0
                        logger.warning("Max compact failures — raw archived + hard truncated to 1 turn")

            last_input_tokens = 0  # reset after compaction

        response: AIMessage = await llm.ainvoke(history)
        history.append(response)

        # Track tokens: use API total (input + cached), fall back to tiktoken estimate
        usage = (response.response_metadata or {}).get("usage", {})
        api_total = (
            (usage.get("input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
        )
        if api_total:
            last_input_tokens = api_total
        else:
            last_input_tokens = estimate_tokens(history)

        # Store in shared state for context_status tool
        _session_token_usage[session_name] = {
            "input_tokens": last_input_tokens,
            "context_window": CONTEXT_WINDOW,
            "usage_pct": round(last_input_tokens / CONTEXT_WINDOW * 100, 1) if last_input_tokens else 0,
            "output_tokens": usage.get("output_tokens", 0),
        }

        # Emit thinking / text content
        if isinstance(response.content, list):
            for block in response.content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        await _emit(bus, msg.channel, msg.chat_id,
                              f"💭 {block['thinking'][:500]}", MsgType.THINKING, out_meta)
                    elif block.get("type") == "text" and block.get("text"):
                        await _emit(bus, msg.channel, msg.chat_id,
                              f"💬 {block['text'][:300]}", MsgType.THINKING, out_meta)
        elif isinstance(response.content, str) and response.content:
            await _emit(bus, msg.channel, msg.chat_id,
                  f"💬 {response.content[:300]}", MsgType.THINKING, out_meta)

        # Emit metadata
        if usage:
            await _emit(bus, msg.channel, msg.chat_id,
                  f"📊 tokens: in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')}",
                  MsgType.THINKING, out_meta)

        # No tool calls → done
        if not response.tool_calls:
            reply = _extract_reply(response)
            # Append token usage to final response
            if last_input_tokens:
                reply += f"\n\n---\n📊 {format_token_usage(last_input_tokens)}"
            await _emit(bus, msg.channel, msg.chat_id, reply, MsgType.RESPONSE, out_meta)
            break

        # Execute tool calls
        for tc in response.tool_calls:
            args_str = json.dumps(tc["args"], ensure_ascii=False, indent=2)
            await _emit(bus, msg.channel, msg.chat_id,
                  f"🔧 {tc['name']}({args_str})", MsgType.TOOL_CALL, out_meta)

            tool_fn = TOOL_MAP.get(tc["name"])
            if tool_fn:
                # Run sync tools in executor so they don't block the event loop
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, tool_fn.invoke, tc["args"])
            else:
                result = f"Unknown tool: {tc['name']}"
            result_preview = result[:500] + ("..." if len(result) > 500 else "")
            await _emit(bus, msg.channel, msg.chat_id,
                  f"→ {tc['name']}: {result_preview}", MsgType.TOOL_RESULT, out_meta)

            history.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    # Persist full history (skip SystemMessage) + last API token count for next turn
    save_full_session(session_name, history[1:], token_usage=last_input_tokens)
