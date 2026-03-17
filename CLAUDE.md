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
  tools.py         — 11 tools: read_file, list_dir, write_file, edit_file, search_files, exec_cmd (with background), plan, context_status, web_search, web_fetch, skill
  skills.py        — Skill discovery (~/.claude/skills/ + .claude/skills/), frontmatter parsing, content loading
  compact.py       — Two-phase context compaction (prune + LLM summary) + per-session MemoryStore
  agent.py         — agent_loop() consuming from bus, emitting outbound events, auto-compact, skill/memory injection
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
- [x] Layer 10 — Skills system (discovery, `skill` tool, prompt injection)
- [ ] Layer 9+ — Provider abstraction, cron, extensions

Full backlog: `docs/plan/backlog.md`

## Testing — TDD (MANDATORY)

**No Tests → No Code.** Every new feature or bug fix follows Red → Green:

1. **Define coverage target FIRST** — before writing any test, decide and state the target line coverage % for the module being changed. sbot targets by layer:
   - agent.py, session.py, compact.py (core loop): 85%+
   - tools.py, skills.py (service layer): 80%+
   - bus.py, config.py, channels/ (infra/glue): 60%+
   - New/changed lines per commit: 85%+
2. **Write failing tests** — tests that define the expected behavior. Run them, confirm they fail (RED).
3. **Write the code** — minimum code to make tests pass (GREEN).
4. **Refactor** — clean up, then re-run tests to confirm still green.
5. **Test categories** — coverage % is necessary but NOT sufficient. Every test suite must cover:
   - **Normal cases** — happy path, typical inputs
   - **Boundary cases** — empty inputs, max values, off-by-one, first/last element
   - **Error/exception cases** — invalid input, missing files, network failures, malformed data
   - **Edge cases** — unicode, very large inputs, concurrent access where relevant
6. **Be honest about coverage gaps.** If a module legitimately can't hit the target (e.g. network I/O channels need integration tests, not unit tests), state why and what test type would cover it instead. Don't write bullshit tests just to inflate coverage numbers.

**LLM calls MUST be mocked in unit tests.** LLM API calls cost money and are non-deterministic. Mock `llm.ainvoke()`, `llm.with_structured_output()`, and any Exa API calls. Use `unittest.mock.patch` or `pytest-mock`. Only E2E tests (separate scope) may hit real APIs.

```bash
python3 -m pytest tests/test_*.py -v                           # Unit tests only (fast)
python3 -m pytest tests/integration/ -v                        # Integration tests (replays VCR cassettes)
python3 -m pytest tests/ -v                                    # All tests
python3 -m pytest tests/ --cov=sbot --cov-report=term-missing  # All + coverage
python3 -m pytest tests/integration/ --record-mode=once -v     # Re-record cassettes (hits real API, costs $)
```

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
