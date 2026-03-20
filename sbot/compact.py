"""Auto-compact — two-phase context compaction for long conversations."""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Constants ---

CONTEXT_WINDOW = 204_000
COMPACT_TRIGGER = 0.60          # trigger at 60% of context window
BYTES_PER_TOKEN = 4             # UTF-8 bytes per token heuristic (same as Codex)
POST_COMPACT_TARGET = 0.40      # after compaction, must be under 40%
KEEP_RECENT_TURNS = 3           # preferred turns to keep (adaptive: 3→2→1→0)
MAX_FAILURES_BEFORE_RAW = 3     # then fall back to raw archive

COMPACT_PROMPT = """[CONTEXT COMPACTION] Summarize this conversation for handoff to continue in a smaller context.

Return valid JSON with these fields:
- session_summary: 3-4 sentences about what this session is about, key decisions made
- turns: array of {user_query, bot_response} for each older turn (bot_response max 200 chars)
- plan_state: current plan todo_list if plan tool was used, null otherwise
- files_touched: array of file paths that were read, written, or edited
- memory_update: long-term facts worth remembering (user preferences, project state, key discoveries)
- history_entry: a timestamped paragraph summarizing what happened (for grep-searchable log)"""


# --- Pydantic models ---

class CompactTurn(BaseModel):
    user_query: str
    bot_response: str = Field(max_length=200)


class CompactSummary(BaseModel):
    session_summary: str
    turns: list[CompactTurn] = []
    plan_state: list[dict] | None = None
    files_touched: list[str] = []
    memory_update: str = ""
    history_entry: str = ""


# --- Token estimation ---

# Lazy-loaded tiktoken encoder
_encoder = None

def _get_encoder():
    global _encoder
    if _encoder is None:
        import tiktoken
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


# Cache tool schema token count (computed once, tools don't change at runtime)
_tool_schema_tokens: int | None = None

def _get_tool_schema_tokens() -> int:
    """Count tokens in tool schemas (sent via .bind_tools()). Cached after first call."""
    global _tool_schema_tokens
    if _tool_schema_tokens is not None:
        return _tool_schema_tokens
    try:
        from .tools import TOOLS
        from langchain_core.utils.function_calling import convert_to_openai_function
        schemas = [convert_to_openai_function(t) for t in TOOLS]
        text = json.dumps(schemas, ensure_ascii=False)
        _tool_schema_tokens = len(_get_encoder().encode(text))
    except Exception:
        _tool_schema_tokens = 1500  # safe fallback
    return _tool_schema_tokens


def estimate_tokens(messages: list, include_tools: bool = True) -> int:
    """Estimate token count using tiktoken (cl100k_base).

    Includes tool schemas by default since .bind_tools() sends them with every request.
    """
    enc = _get_encoder()
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg.content, str):
            parts.append(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        text = block.get("text", "")
                        if text:
                            parts.append(text)
                    elif btype == "thinking":
                        thinking = block.get("thinking", "")
                        if thinking:
                            parts.append(thinking)
                    # Skip "tool_use" blocks — args already counted via msg.tool_calls
                else:
                    parts.append(str(block))
        if isinstance(msg, AIMessage) and msg.tool_calls:
            parts.append(json.dumps(msg.tool_calls, ensure_ascii=False))
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            parts.append(msg.tool_call_id)
    tokens = len(enc.encode("\n".join(parts)))
    # Add per-message overhead (~4 tokens each for role, separators)
    tokens += len(messages) * 4
    if include_tools:
        tokens += _get_tool_schema_tokens()
    return tokens


# --- Turn boundary helpers ---

def _find_turn_boundaries(messages: list) -> list[int]:
    """Return indices where each turn starts (each HumanMessage = new turn).
    Skips SystemMessage at index 0 if present."""
    boundaries = []
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            boundaries.append(i)
    return boundaries


def count_recent_messages(messages: list, keep_turns: int) -> int:
    """Count how many messages are in the last `keep_turns` turns."""
    boundaries = _find_turn_boundaries(messages)
    if len(boundaries) <= keep_turns:
        # All messages are "recent" (minus system message)
        start = 1 if isinstance(messages[0], SystemMessage) else 0
        return len(messages) - start
    cutoff = boundaries[-keep_turns]
    return len(messages) - cutoff


# --- Phase 1: Prune tool outputs (no LLM call) ---

def prune_tool_outputs(messages: list, keep_recent: int = KEEP_RECENT_TURNS) -> tuple[list, int]:
    """Strip content from old ToolMessages, return (new_messages, chars_freed).

    - Protects the last `keep_recent` turns
    - For older ToolMessages: replace content with "[pruned: N chars]"
    - For older AIMessages with tool_calls: keep tool names, strip args
    - NEVER breaks AIMessage→ToolMessage pairing
    """
    boundaries = _find_turn_boundaries(messages)
    if len(boundaries) <= keep_recent:
        return messages, 0  # nothing to prune

    # Messages before this index are "old" and can be pruned
    protect_from = boundaries[-keep_recent]

    new_messages = []
    chars_freed = 0

    for i, msg in enumerate(messages):
        if i >= protect_from:
            # Recent turn — keep as-is
            new_messages.append(msg)
            continue

        if isinstance(msg, ToolMessage):
            content_len = len(msg.content) if isinstance(msg.content, str) else 0
            if content_len > 100:
                chars_freed += content_len
                new_messages.append(
                    ToolMessage(
                        content=f"[pruned: {content_len} chars]",
                        tool_call_id=msg.tool_call_id,
                    )
                )
            else:
                new_messages.append(msg)
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            # Keep tool names but strip large args
            stripped_calls = []
            for tc in msg.tool_calls:
                args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                if len(args_str) > 200:
                    chars_freed += len(args_str)
                    stripped_calls.append({
                        **tc,
                        "args": {k: f"[{len(str(v))} chars]" for k, v in tc.get("args", {}).items()},
                    })
                else:
                    stripped_calls.append(tc)
            new_messages.append(
                AIMessage(content=msg.content, tool_calls=stripped_calls)
            )
        else:
            new_messages.append(msg)

    logger.info(f"Phase 1 prune: freed ~{chars_freed} chars from {protect_from} old messages")
    return new_messages, chars_freed


# --- Phase 2: LLM compaction ---

async def compact_with_llm(llm, history: list) -> CompactSummary:
    """Append COMPACT_PROMPT at end of history (KV cache reuse), get structured summary.

    Tries with_structured_output first, falls back to JSON parsing from text.
    """
    compact_history = list(history) + [HumanMessage(content=COMPACT_PROMPT)]

    # Try structured output first (may not be supported by all providers)
    try:
        structured_llm = llm.with_structured_output(CompactSummary)
        result = await structured_llm.ainvoke(compact_history)
        if isinstance(result, CompactSummary):
            return result
    except (NotImplementedError, TypeError, ValueError) as e:
        logger.warning(f"with_structured_output not supported ({e}), falling back to JSON parse")

    # Fallback: regular invoke + parse JSON from response
    response = await llm.ainvoke(compact_history)
    text = response.content if isinstance(response.content, str) else str(response.content)

    # Extract JSON from response (may be wrapped in ```json blocks)
    json_text = text
    if "```json" in json_text:
        json_text = json_text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in json_text:
        json_text = json_text.split("```", 1)[1].split("```", 1)[0]

    try:
        data = json.loads(json_text.strip())
        return CompactSummary(**data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"JSON parse failed ({e}), creating minimal summary from text")
        return CompactSummary(
            session_summary=text[:500],
            history_entry=f"[{_now_str()}] Auto-compact (parse failed): {text[:300]}",
        )


# --- Rebuild history after compaction ---

def rebuild_history(summary: CompactSummary, recent_messages: list, system_prompt: str) -> list:
    """Build: SystemMessage + summary-as-context + recent full turns.

    Summary injected as HumanMessage + AIMessage pair so it looks like
    a natural conversation continuation.
    """
    # Format summary text
    parts = [f"**Session Summary:** {summary.session_summary}"]
    if summary.turns:
        parts.append("\n**Previous turns:**")
        for t in summary.turns:
            parts.append(f"- User: {t.user_query}")
            parts.append(f"  Bot: {t.bot_response}")
    if summary.files_touched:
        parts.append(f"\n**Files touched:** {', '.join(summary.files_touched)}")
    if summary.plan_state:
        parts.append(f"\n**Plan state:** {json.dumps(summary.plan_state, ensure_ascii=False)}")

    summary_text = "\n".join(parts)

    history = [SystemMessage(content=system_prompt)]
    history.append(HumanMessage(content=f"## Session Summary\n\n{summary_text}"))
    history.append(AIMessage(content="Understood. I have the context from our previous conversation. Let's continue."))
    history.extend(recent_messages)
    return history


# --- Memory persistence ---

class MemoryStore:
    """Per-session MEMORY.md (facts) + HISTORY.md (grep-searchable log).
    Directory: sessions/{session_name}_memory/
    """

    def __init__(self, session_name: str):
        self.dir = Path("sessions") / f"{session_name}_memory"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._memory_path = self.dir / "MEMORY.md"
        self._history_path = self.dir / "HISTORY.md"

    def read_memory(self) -> str:
        if self._memory_path.exists():
            return self._memory_path.read_text().strip()
        return ""

    def write_memory(self, content: str):
        if content.strip():
            self._memory_path.write_text(content.strip() + "\n")

    def append_history(self, entry: str):
        if entry.strip():
            with open(self._history_path, "a") as f:
                f.write(entry.strip() + "\n\n---\n\n")


# --- Raw archive fallback ---

def raw_archive(messages: list) -> str:
    """Format messages as timestamped text dump. Used after MAX_FAILURES_BEFORE_RAW."""
    lines = [f"[{_now_str()}] Raw archive of {len(messages)} messages:"]
    for msg in messages:
        if isinstance(msg, SystemMessage):
            continue
        role = type(msg).__name__.replace("Message", "")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        lines.append(f"[{role}] {content[:300]}")
    return "\n".join(lines)


# --- Token formatting ---

def format_token_usage(input_tokens: int, context_window: int = CONTEXT_WINDOW) -> str:
    """Format token usage as 'Xk / Yk tokens (Z%)'. Single source of truth."""
    in_k = round(input_tokens / 1000, 1)
    max_k = round(context_window / 1000, 1)
    pct = round(input_tokens / context_window * 100, 1)
    return f"{in_k}k / {max_k}k tokens ({pct}%)"


# --- Helpers ---

def _now_str() -> str:
    """Current time in UTC+7 as string."""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
