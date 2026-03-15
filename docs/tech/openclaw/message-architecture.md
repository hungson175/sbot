# OpenClaw Message Architecture

Reference: https://docs.openclaw.ai/ | GitHub: openclaw/openclaw (314k stars, TypeScript)

## Overview

Single-writer, event-driven architecture. Gateway daemon owns sessions, channels, tools, memory, scheduling. WebSocket API on `127.0.0.1:18789`.

## Message Flow

```
Inbound:  Channel Bridge → Debounce → Session Resolution → Queue (with modes) → Agent Runtime → LLM
Outbound: Agent Response → Tool Execution → Message Bridge → Platform Delivery
```

## Queue Modes

When a message arrives while the agent is already processing:

| Mode | Behavior |
|------|----------|
| `collect` (default) | Coalesce queued messages into single followup turn after current run ends |
| `followup` | Wait for current run, then start new turn |
| `steer` | Inject into current run immediately, cancel pending tool calls |
| `steer-backlog` | Immediate steering + deferred handling |
| `interrupt` | Hard-stop the current run |

Configured via `messages.queue` with per-channel overrides (`messages.queue.byChannel`).

## Lane-Based Concurrency

| Lane | Concurrency | Purpose |
|------|-------------|---------|
| Global | 4 (configurable) | Rate limiting across all sessions |
| Session | 1 | Single-writer — one run per session at a time |
| Sub-agent | 8 | Parallel background work |
| Cron | Parallel with main | Scheduled jobs |

## Inbound Debouncing

Rapid consecutive messages from same sender batched into single turn:
- WhatsApp: 5000ms
- Slack / Discord: 1500ms
- Per-channel overrides supported

Key: debouncer uses fire-and-forget pattern (`void onFlush().catch()`) — non-blocking so queue system can detect active run and route correctly.

## Session Key Routing

```
Direct messages:    agent:<agentId>:<mainKey>
Per-peer DMs:       agent:<agentId>:dm:<peerId>
Per-channel-peer:   agent:<agentId>:<channel>:dm:<peerId>
Group chats:        agent:<agentId>:<channel>:group:<id>
```

`dmScope` config: contacts across channels share one session (continuity) or isolated (per-peer security).

## Streaming / Chunking

`blockStreamingDefault`, `blockStreamingBreak`, `humanDelay` control reply delivery with per-channel overrides. Telegram supports streaming reasoning tokens into draft bubbles.

## Queue UX

When message is queued, user sees: "Your message is queued (1 running, 2 queued)"

## Deduplication

Messages cached by `channel/account/peer/session/messageID` to prevent duplicate agent runs from channel redeliveries.

## Relevance to sbot

For MVP (2 channels), nanobot's simple two-queue is sufficient. When sbot grows, consider adding:
1. **Debouncing** — especially for WhatsApp/Messenger (users send fragmented messages)
2. **Queue modes** — at least `collect` to merge queued messages
3. **Session-level single-writer** — one agent run per conversation at a time

## Reference Links

- Docs: https://docs.openclaw.ai/concepts/messages
- "You Could've Invented OpenClaw" gist (Python from scratch): https://gist.github.com/dabit3/bc60d3bea0b02927995cd9bf53c3db32
- Architecture deep dive: https://gist.github.com/royosherove/971c7b4a350a30ac8a8dad41604a95a0
