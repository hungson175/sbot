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

## session.py
JSONL persistence in `sessions/`. `save_messages()` batches writes.
`load_session()` caps at 100 most recent messages. Dir created at import.

## config.py
Loads `.env`, reads `prompts/system.txt` as base prompt, appends bootstrap files (AGENTS.md, SOUL.md, USER.md, TOOLS.md).

## tools.py
7 tools via `@tool(description=_load_description("name"))`.
Descriptions in `prompts/tools/*.txt`. `exec_cmd` has `background` mode.

## channels/base.py
`BaseChannel` ABC: `start()`, `stop()`, `send()`, `is_allowed()`.
`@register_channel` decorator + `get_enabled_channel_classes()` for auto-discovery.

## channels/cli.py
`CLIChannel` — sync callback prints with `flush=True`. `asyncio.Event` waits for RESPONSE/ERROR.

## channels/telegram.py
`TelegramChannel` — polling inbound via `python-telegram-bot`. Async send queue outbound.
Only sends RESPONSE/ERROR to Telegram. Allowlist via `TELEGRAM_ALLOWED_CHAT_IDS`.
