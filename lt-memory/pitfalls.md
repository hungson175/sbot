# Pitfalls — sbot

Gotchas discovered during implementation. Check here before modifying tricky areas.

## Outbound delivery — buffering happens when producer doesn't yield
The core problem: if the agent emits multiple messages between `await` points, consumers in separate async tasks can't process them until the agent yields. This manifests differently per channel:
- **CLI**: sync callback → `print()` works immediately (same call stack). No buffering.
- **Network channels** (Telegram): sync callback only queues the message. The actual HTTP POST runs in an async sender task, which can't execute until the agent yields.
- **Fix**: `await asyncio.sleep(0.05)` after each `_emit()` gives async sender loops time to POST. `sleep(0)` is NOT enough for HTTP round-trips.
- **Future**: replace with proper delivery confirmation (bus awaits until channel confirms receipt).

## Tool descriptions
- Every `@tool` parameter MUST have a description with examples in its `.txt` file. MiniMax M2.5 has worse parameter extraction than Claude with vague descriptions.
- Tool descriptions live in `sbot/prompts/tools/*.txt`, NOT in Python docstrings. The `@tool(description=_load_description("name"))` pattern loads them at import time.
- Do NOT duplicate tool descriptions in the system prompt. `.bind_tools()` already attaches them to the API request.

## Message types — use MsgType StrEnum, not bare strings
Bare string constants (`"thinking"`, `"response"`) have no typo protection and no exhaustiveness checking. Use `MsgType.THINKING`, `MsgType.RESPONSE`, etc. Add catch-all `case _:` in match statements so unknown types aren't silently dropped.

## Bootstrap files
AGENTS.md, SOUL.md, USER.md, TOOLS.md are ADDITIVE to the base system prompt, not replacements. They get appended with `## filename.md` headers.

## Session persistence
- SystemMessage is never saved to JSONL — it's config, not history.
- AIMessage tool_calls must be preserved in serialization or tool dispatch breaks on resume.
- Session history capped at 100 messages on load to avoid context window overflow. (Review: this cap may be redundant now that auto-compact exists — see backlog.)
- Use `save_messages()` (batch) not per-message saves — single file open, no per-call mkdir.
- `load_session()` returns `tuple[list, int]` (messages, last_consolidated) — not just a list.
- JSONL lines with `_type` field are metadata/compact events, skipped by `_dict_to_msg()`.
- **Session truncation must respect message boundaries.** Slicing `messages[-N:]` can orphan ToolMessages whose parent AIMessage (with `tool_calls`) was cut. MiniMax returns 400: `tool result's tool id not found`. Fix: after truncation, walk forward to the first HumanMessage for a clean boundary.

## Auto-compact
- Compaction triggers when API-reported `input_tokens` exceeds 80% of 204k context window.
- Phase 1 (prune) is free: strips old ToolMessage content, shrinks old tool_call args. NEVER breaks AIMessage→ToolMessage pairing.
- Phase 2 (LLM compact) uses `with_structured_output(CompactSummary)` with JSON-parse fallback — MiniMax may not support structured output.
- **Adaptive keep**: after compaction, must be under 40% of context window. Tries keeping 3→2→1→0 turns until target is met. Prevents re-compaction spiral when recent turns are large.
- Per-session memory stored in `sessions/{session_name}_memory/MEMORY.md` and `HISTORY.md`.
- `last_input_tokens` starts at 0 — compaction only triggers after at least one API response with usage data.
- After `MAX_FAILURES_BEFORE_RAW` (3) compact failures, falls back to raw text archive in HISTORY.md + hard truncates to SystemMessage + 1 turn. Without hard truncation, the bloated history stays in memory and the next LLM call hits context limit.
- Use `contextvars.ContextVar` (not plain globals) to share session state between agent.py and tools. Plain globals cause race conditions in gateway mode with concurrent users.

## Tool execution
- Tool functions are SYNC (`tool_fn.invoke()`). Run them in `loop.run_in_executor()` or they block the entire event loop, preventing outbound messages from being delivered during tool execution.

## Autonomous mode
- Do NOT include `ask_user` tool — it calls `input()` directly, races with CLI channel's stdin, and hangs in non-terminal channels. The agent should be autonomous and never ask questions.

## exec_cmd background mode
- Long-running commands (servers, watchers) MUST use `background=true` or the agent freezes waiting for them to exit. Uses `subprocess.Popen` with `start_new_session=True` so the process survives independently.

## Network channel outbound — async send queue, not sync callback
- CLI uses sync callback (instant `print()`). Network channels (Telegram, Messenger) must NOT do HTTP calls in the sync callback — that blocks the agent during API latency. Instead: sync callback queues the message, a background `_sender_loop` task does the actual async HTTP POST.

## Testing pitfalls
- **venv vs system pip**: `pip install pytest` installs to system Python, not `.venv`. Use `uv pip install` or `.venv/bin/python3 -m pip install` explicitly.
- **Mocking `with_structured_output` for fallback tests**: `llm.with_structured_output()` returns a NEW LLM object. To test the fallback path (structured output fails → JSON parse), make the returned LLM's `ainvoke` raise, not `with_structured_output` itself: `structured_llm = AsyncMock(); structured_llm.ainvoke.side_effect = NotImplementedError; mock_llm.with_structured_output.return_value = structured_llm`.
- **VCR cassettes**: recorded in `tests/integration/cassettes/`. Re-record with `--record-mode=once` after changing system prompts or tool definitions — stale cassettes will replay old LLM responses that don't match new code expectations.

## MiniMax M2.5 quirks
- Always-on `<think>` reasoning — adds ~2s latency per turn even for trivial responses.
- "Thoughtful disobedience" — may override system prompt constraints. Enforce limits in code, not prompts.
- Preserve `<think>` blocks in conversation history — stripping them degrades response quality.
