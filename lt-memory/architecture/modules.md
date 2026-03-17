# Modules — sbot

## app.py
Entry point. `run()` dispatches to `main_cli()` or `main_serve()` based on args.
- CLI mode: one bus + one agent + CLIChannel
- Gateway mode: per-channel isolated bus + agent + LLM via `get_enabled_channel_classes()`

## bus.py
`MessageBus` — inbound `asyncio.Queue`, outbound via sync callback dict.
`MsgType` StrEnum: THINKING, TOOL_CALL, TOOL_RESULT, RESPONSE, ERROR, STATUS.
`emit()` calls registered handler directly (no async queue for outbound).

## agent.py
`agent_loop(llm, bus)` — consumes `bus.inbound`, runs `_process_message()`.
Unbounded `while True` tool-calling loop. Tools run in `run_in_executor()`.
Session save batched via `save_messages()`. Emits events via `_emit()` → `bus.emit()`.
Auto-compact check before each LLM call (triggers at 80% of 204k context).
System prompt assembled at runtime: base prompt + memory (per-session) + skills metadata (name + description).
Token usage appended to every final response. Uses `contextvars.ContextVar` for async-safe per-session state (shared with `context_status` tool).

## compact.py
Two-phase context compaction + per-session memory persistence.
- Phase 1 `prune_tool_outputs()`: strips old ToolMessage content, shrinks tool_call args (free, no LLM)
- Phase 2 `compact_with_llm()`: structured summary via `with_structured_output(CompactSummary)`, JSON-parse fallback
- `rebuild_history()`: SystemMessage + summary pair + recent turns
- `MemoryStore`: per-session `MEMORY.md` (facts) + `HISTORY.md` (grep-searchable log) in `sessions/{name}_memory/`
- `format_token_usage()`: shared formatter for token display (used by agent.py + context_status tool)
- Adaptive keep: tries 3→2→1→0 turns post-compact to stay under 40% target

## session.py
JSONL persistence in `sessions/`. `save_messages()` batches writes.
`load_session()` returns `tuple[list, int]` (messages, last_consolidated). Caps at 100 most recent.
`save_compact_event()` writes `_type: compact` lines. Lines with `_type` field are skipped by message deserializer.

## config.py
Loads `.env`, reads `prompts/system.txt` as base prompt, appends bootstrap files (AGENTS.md, SOUL.md, USER.md, TOOLS.md).

## skills.py
Skill discovery from `~/.claude/skills/` (user global, Claude Code compatible) and `.claude/skills/` (project-level, higher precedence on name conflict).
Parses YAML frontmatter (name, description) without PyYAML dependency. Module-level cache — discovered once, reused.
`format_skills_for_prompt()` generates markdown listing for system prompt injection (~2k tokens for ~46 skills).
`load_skill_content()` returns SKILL.md body (after frontmatter) + lists bundled resources (references/, scripts/, assets/).

## tools.py
11 tools via `@tool(description=_load_description("name"))`.
Descriptions in `prompts/tools/*.txt`. `exec_cmd` has `background` mode.
`context_status` tool reads current session token usage via lazy import from `agent.get_current_token_usage()`.
`web_search`/`web_fetch` use Exa API (lazy singleton client). `skill` tool loads skill content on demand via `skills.py`.

## channels/base.py
`BaseChannel` ABC: `start()`, `stop()`, `send()`, `is_allowed()`.
`@register_channel` decorator + `get_enabled_channel_classes()` for auto-discovery.

## channels/cli.py
`CLIChannel` — sync callback prints with `flush=True`. `asyncio.Event` waits for RESPONSE/ERROR.

## channels/telegram.py
`TelegramChannel` — polling inbound via `python-telegram-bot`. Async send queue outbound.
Only sends RESPONSE/ERROR to Telegram. Allowlist via `TELEGRAM_ALLOWED_CHAT_IDS`.
