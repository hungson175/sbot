# Architecture Overview — sbot

Python async app with LangChain + MiniMax M2.5 + message bus.

## Design Principles
- Each channel gets its own bus + agent + LLM (fully isolated)
- Shared long-term memory across channels (future)
- Sync callback outbound for CLI (immediate), async send queue for network channels (non-blocking)
- Open/closed: add new channels via `@register_channel` decorator + env var, no core changes

## Detailed Docs
- [flows.md](flows.md) — User flow diagrams (Mermaid)
- [modules.md](modules.md) — Per-module descriptions
- [decisions.md](decisions.md) — Key architectural decisions and their rationale

## Reference
- `docs/tech/nanobot/` — nanobot architecture (original reference)
- `docs/tech/openclaw/` — OpenClaw message architecture (advanced patterns for later)
- `docs/tech/sbot/message-architecture.md` — sbot's planned multi-channel design
