# sbot Rebuild Backlog

Learn-by-doing roadmap. Each layer is the **smallest thing** you can add, test, and play with.
Goal: get sbot running on Telegram + Messenger ASAP, then circle back for improvements.

Reference: `sample_code/nanobot/`

---

## Layer 1 — Agent loop + tools in one file ✅

Single file with agent loop, 3 tools, interactive + single-message CLI.
**Done.** `sbot.py` works end-to-end with MiniMax via Anthropic-compatible API.

---

## Layer 2 — Session persistence ✅

JSONL save/load, timestamped sessions, `--session` flag to resume.
**Done.** `sbot/session.py`

---

## Layer 3 — System prompt from file ✅

Base prompt from `sbot/prompts/system.txt`, bootstrap files (AGENTS.md, SOUL.md, USER.md, TOOLS.md) appended.
**Done.** `sbot/config.py`

---

## Layer 4 — Full tool suite ✅

8 tools: read_file (paginated), list_dir, write_file, edit_file, search_files (ripgrep), exec_cmd, ask_user, plan.
Tool descriptions externalized to `sbot/prompts/tools/*.txt`.
Reference prompts collected in `sbot/prompts/samples/`.
**Done.** `sbot/tools.py`

---

# EPIC: Two-Channel MVP (Telegram + Messenger)

Priority: get sbot reachable from real messaging apps ASAP. Memory/auto-compact comes later.

---

## Layer 5 — Message bus + service mode

Decouple the agent from CLI so it can serve multiple channels.

- [ ] `InboundMessage` / `OutboundMessage` dataclasses (channel, chat_id, text, metadata)
- [ ] `MessageBus` — two `asyncio.Queue`s (inbound + outbound)
- [ ] Refactor `agent_turn()` to consume from inbound, publish to outbound
- [ ] Refactor CLI as a "channel" — pushes to inbound, consumes from outbound
- [ ] Session key changes from name to `channel:chat_id`
- [ ] Gateway mode: `python3 -m sbot serve` — runs as a long-lived service
- **Checkpoint**: CLI still works exactly the same, but goes through the bus
- **Reference**: `nanobot/bus/queue.py`

---

## Layer 6 — Telegram channel

First real channel. Users can talk to sbot from Telegram.

- [ ] `BaseChannel` interface: `start()`, `stop()`, `send()`, `is_allowed()`
- [ ] `TelegramChannel` using `python-telegram-bot` (or `aiogram`)
- [ ] Bot token from `.env` (`TELEGRAM_BOT_TOKEN`)
- [ ] Allowlist: only respond to configured chat IDs
- [ ] `ChannelManager` — starts/stops enabled channels
- [ ] Wire into gateway mode
- **Checkpoint**: send a message on Telegram, get a response from sbot with tool use
- **Reference**: `nanobot/channels/telegram.py`

---

## Layer 7 — Facebook Messenger channel

Second channel. Same agent, different platform.

- [ ] `MessengerChannel` using Facebook Graph API / webhook
- [ ] Webhook endpoint (lightweight FastAPI or aiohttp server for Meta verification)
- [ ] Page access token + verify token from `.env`
- [ ] Allowlist by sender ID
- [ ] Register in ChannelManager
- **Checkpoint**: both Telegram and Messenger work simultaneously, each user gets their own session
- **Reference**: Meta Messenger Platform docs

---

# POST-MVP: Improvements

Circle back after the two-channel MVP is working.

---

## Layer 8 — Auto-compact

- [ ] Implement auto-compact: summarize session history when approaching context window limit
- **Design doc**: `docs/tech/sbot/auto-compact.md`
- **Reference**: `nanobot/agent/memory.py`, Claude Code's auto-compact behavior

---

## Layer 9 — Provider abstraction

- [ ] Base provider interface (swap models without touching agent loop)
- [ ] Retry wrapper for transient failures
- [ ] Support multiple providers (MiniMax, Claude, OpenAI)
- **Reference**: `nanobot/providers/`

---

## Layer 10 — Cron + heartbeat

- [ ] Persistent job store
- [ ] Cron tool so the agent can schedule tasks
- [ ] Heartbeat service (periodic check)
- **Reference**: `nanobot/cron/`, `nanobot/heartbeat/`

---

## Layer 11 — Advanced extensions

- [ ] Subagent spawn
- [ ] MCP dynamic tool discovery
- [ ] Skills system
- [ ] More channels (Slack, Discord, WhatsApp)
- **Checkpoint**: feature-complete match with nanobot

---

### Layer 12 - Telegram group
Can this join a group, and everyone in that group can invoke it to do something ("Hey @sbot , go make resaerch abc" - "Hey summarize what we have discussed sofar ?" ... )