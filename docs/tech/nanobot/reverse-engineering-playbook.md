# Reverse Engineering Playbook

How to learn nanobot by rebuilding it piece by piece in sbot.
This follows the **single-file first, refactor later** methodology.

## Learning Strategy

- Each layer = **smallest thing you can add, test, and play with**
- Stay in one file as long as possible — understand the whole flow before splitting
- NO premature abstractions (registries, base classes, bus) until they're earned
- Copy ideas from nanobot, not code
- After each layer: stop, play around, break things, then move on

## Recommended Read Order

When you need to understand how nanobot does something, read in this order:

1. `cli/commands.py` — how it starts up
2. `agent/loop.py` — the core (2,239 lines, read in chunks)
3. `agent/context.py` — how system prompt is assembled
4. `agent/tools/*` — tool definitions
5. `session/manager.py` — JSONL persistence
6. `providers/*` — LLM abstraction
7. `channels/*` — multi-platform input/output
8. `agent/memory.py` — memory consolidation
9. `cron/*` and `heartbeat/*` — background services
10. `agent/subagent.py` and `agent/tools/mcp.py` — advanced features

## Layer-by-Layer Reference Map

What to read in nanobot when working on each sbot layer:

| sbot Layer | Read in nanobot |
|---|---|
| 2 — Session persistence | `session/manager.py` |
| 3 — System prompt from file | `agent/context.py`, `templates/` |
| 4 — Write/edit tools | `agent/tools/filesystem.py` |
| 5 — Memory consolidation | `agent/memory.py`, `utils/helpers.py` |
| 6 — Refactor into packages | Overall package structure |
| 7 — Provider abstraction | `providers/base.py`, `providers/registry.py` |
| 8 — Message bus + channel | `bus/`, `channels/base.py`, `channels/manager.py` |
| 9 — Cron + heartbeat | `cron/`, `heartbeat/` |
| 10 — Extensions | `agent/subagent.py`, `agent/tools/mcp.py`, `skills/` |

## Drills (do these when you want deeper understanding)

### Drill A: Control-flow tracing
Pick a prompt that invokes 2+ tools. Log each internal transition:
inbound event → provider call → tool execution → session save → outbound event

### Drill B: Failure injection
Test sbot against: provider timeout, malformed tool args, oversized tool output.
Goal: degrade gracefully, don't deadlock.

### Drill C: API surface freeze (do after Layer 6)
Define stable interfaces (Provider, Tool, Channel, SessionStore).
Re-implement internals without changing call sites.
Goal: prove the architecture is decoupled.

## Definition of Done

You're done when sbot:
- Has feature parity with nanobot's core capabilities
- You can add a new tool and channel quickly
- You can explain every async boundary and why it exists
- You could simplify a subsystem while keeping behavior stable
