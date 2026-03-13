# CLAUDE.md — sbot

sbot is a from-scratch reimplementation of the nanobot AI assistant framework.
Reference codebase lives at `../nanobot/`. Read `../docs/tech/` for architecture docs.

## Learning Methodology
**Single-file first, refactor later.** Each layer is ONE tiny step:
1. Start with everything in ONE file — grasp the whole flow
2. Play around, experiment, break things
3. Only then add the next small piece
4. Refactoring into multiple files/abstractions = its own separate layer
5. NO premature abstractions (providers, registries, bus, config schemas) until they're actually needed

**What "layer" means:** NOT a whole subsystem. A layer is the smallest thing you can add, test, and understand. Examples:
- Layer 1: agent loop + tools in one file → it works, you understand the flow
- Layer 2: add session persistence (still same file or minimal addition)
- Layer 3: add a system prompt from a file
- Later: refactor into packages when the single file gets too big

**Anti-patterns to avoid:**
- Building a full package structure before having working code
- Provider abstraction before testing multiple models
- Registry pattern before having 5+ tools
- MessageBus before having multiple channels

## Commands
```bash
# Run
ANTHROPIC_AUTH_TOKEN=sk-... python3 sbot.py "message"   # Single message
ANTHROPIC_AUTH_TOKEN=sk-... python3 sbot.py              # Interactive mode
```

## Current State
- **Stack**: Python 3.11+, asyncio, langchain-anthropic
- **LLM**: MiniMax-M2.5-highspeed via Anthropic-compatible API (`https://api.minimax.io/anthropic`)
- **API Key**: `ANTHROPIC_AUTH_TOKEN` env var
- **Structure**: Single file `sbot.py` — agent loop + 3 tools (read_file, list_dir, exec)

## Growth Plan
- [x] Layer 1 — Agent loop + tools in one file
- [ ] Layer 2 — Session persistence (JSONL, same file)
- [ ] Layer 3 — System prompt from file (AGENTS.md / SOUL.md)
- [ ] Layer 4 — Write/edit file tools
- [ ] Layer 5 — Refactor into package structure
- [ ] ... (define as we go)

## Pitfalls
Read [lt-memory/pitfalls.md](lt-memory/pitfalls.md) before modifying tricky areas.

## Long-Term Memory
`lt-memory/` — detail files read on-demand:
- `architecture.md` — Target system design (reference for later layers)
- `pitfalls.md` — Gotchas discovered during implementation
