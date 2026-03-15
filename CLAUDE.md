# CLAUDE.md — sbot

sbot is a from-scratch AI assistant framework, learning from nanobot's design but **not copying it**.
Reference: `sample_code/nanobot/` | Architecture docs: `docs/tech/`

## Key Decisions
- **LangChain** foundation: `@tool` decorator, `ChatAnthropic` with `.bind_tools()`, LangChain message types
- **MiniMax M2.5** via Anthropic-compatible API (`ANTHROPIC_AUTH_TOKEN` in `.env`)
- **Prompts externalized**: system prompt in `sbot/prompts/system.txt`, tool descriptions in `sbot/prompts/tools/*.txt`
- `.bind_tools()` attaches tool descriptions to API requests — do NOT duplicate in system prompt
- **Sync callback outbound** for CLI (immediate print), **async send queue** for network channels (non-blocking)

## Commands
```bash
python3 -m sbot                         # Interactive CLI mode
python3 -m sbot serve                   # Gateway mode (Telegram + future channels)
```

## Current Structure
```
sbot/
  config.py        — API key, model, system prompt loader
  tools.py         — 8 tools: read_file, list_dir, write_file, edit_file, search_files, exec_cmd (with background), plan, context_status
  compact.py       — Two-phase context compaction (prune + LLM summary) + per-session MemoryStore
  agent.py         — agent_loop() consuming from bus, emitting outbound events, auto-compact
  session.py       — JSONL persistence with compact/metadata events
  bus.py           — MessageBus with MsgType enum, sync callback delivery
  app.py           — Entry point: CLI mode + gateway mode (`serve`)
  channels/
    base.py        — BaseChannel ABC (start, stop, send, is_allowed)
    cli.py         — CLI channel (sync callback → print)
    telegram.py    — Telegram channel (polling inbound, async send queue outbound)
  prompts/
    system.txt     — Base system prompt (behavioral rules only)
    tools/*.txt    — One file per tool description
    samples/       — Reference prompts from: opencode, aider, cline, swe-agent, bolt
```

## Growth Plan
- [x] Layer 1–4 — Agent loop, sessions, prompts, tools
- [x] Layer 5 — Message bus + CLI channel
- [x] Layer 6 — Telegram channel (polling, allowlist, async send queue)
- [ ] Layer 7 — Facebook Messenger channel
- [x] Layer 8 — Auto-compact (two-phase context compaction + per-session memory)
- [ ] Layer 9+ — Provider abstraction, cron, extensions

Full backlog: `docs/plan/backlog.md`

## Key Conventions
- Tool descriptions in `sbot/prompts/tools/<name>.txt` with `Args:` section and examples
- System prompt = behavioral rules only (no tool descriptions)
- Message types use `MsgType` StrEnum — never bare strings
- CLI outbound: sync callback (immediate). Network channels: async send queue (non-blocking)
- Tools run in `run_in_executor` to avoid blocking the event loop
- `exec_cmd` has `background=true` for long-running/server commands
- Session key = `{channel}_{chat_id}` (e.g. `telegram_6614099581`)

## Env Vars
- `ANTHROPIC_AUTH_TOKEN` — MiniMax API key
- `TELEGRAM_BOT_TOKEN` — Telegram bot token from @BotFather
- `TELEGRAM_ALLOWED_CHAT_IDS` — comma-separated chat IDs (empty = allow all)

## Pitfalls
Read [lt-memory/pitfalls.md](lt-memory/pitfalls.md) before modifying tricky areas.

## Architecture Docs — KEEP IN SYNC
When making significant structural changes (new modules, new channels, changed message flow), update the relevant file in `lt-memory/architecture/`. Run `/claude-md diff` or `/claude-md deep` to auto-sync.

## Long-Term Memory
`lt-memory/` — detail files read on-demand:
- `architecture/` — System design (split into focused files):
  - [overview.md](lt-memory/architecture/overview.md) — High-level design + principles
  - [flows.md](lt-memory/architecture/flows.md) — User flow diagrams (Mermaid)
  - [modules.md](lt-memory/architecture/modules.md) — Per-module descriptions
  - [decisions.md](lt-memory/architecture/decisions.md) — Key decisions + rationale
- `pitfalls.md` — Gotchas discovered during implementation
