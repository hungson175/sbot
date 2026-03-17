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

## Layer 8 — Auto-compact ✅

Two-phase context compaction + per-session memory.
- Phase 1: prune old tool outputs (free)
- Phase 2: LLM summary with structured output
- Adaptive keep (3→2→1→0 turns), hard truncation fallback
- Per-session MEMORY.md + HISTORY.md
- Token tracking (tiktoken estimate + API actual)
**Done.** `sbot/compact.py`, `sbot/agent.py`, `sbot/session.py`

---

## Layer 9 — MCP Client

Connect to external MCP servers and merge their tools into sbot's tool registry.

- [ ] MCP client using `@modelcontextprotocol/sdk` (Python: `mcp` package)
- [ ] `StdioClientTransport` for local MCP servers (subprocess)
- [ ] Config-driven: `mcp` section in config file or `.env`
- [ ] Tool discovery: `list_tools()` → convert to LangChain `@tool` format
- [ ] Merge MCP tools into `TOOL_MAP` seamlessly
- [ ] Connection state tracking (connected/failed/disabled)
- [ ] Graceful cleanup on shutdown
- **Checkpoint**: configure an MCP server (e.g. filesystem), sbot can use its tools
- **Reference**: `docs/tech/opencode/mcp-server.md`, OpenCode `src/mcp/`

---

## Layer 10 — Skills + Commands

User-defined skills (context docs) and slash commands (reusable prompts).

- [ ] SKILL.md format: markdown with frontmatter (name, description, requires)
- [ ] Skill discovery: project `skills/` + user `~/.sbot/skills/`
- [ ] `skill` tool: lists available skills, loads content into context on demand
- [ ] Eligibility filtering: check required binaries exist
- [ ] Slash commands: markdown templates with `$ARGUMENTS` substitution
- [ ] Commands directory: `.sbot/commands/`
- [ ] Built-in commands: `/compact`, `/status`, `/memory`
- [ ] Size limits to prevent prompt bloat
- **Checkpoint**: create a skill, invoke it via `/skill-name`, see it work
- **Reference**: `docs/tech/opencode/skills-commands.md`, `docs/tech/openclaw/skills-and-tool-search.md`

---

## Layer 11 — Tool Search (Deferred Tools)

Avoid bloating context with unused tool schemas when many tools/MCP servers are connected.

- [ ] Start with small set of always-available tools (read, write, edit, exec, search, plan)
- [ ] `tool_search` meta-tool: agent searches for tools by keyword
- [ ] Deferred tool schemas: listed by name only, full schema loaded on demand
- [ ] Reduces initial prompt size significantly with many MCP servers
- [ ] Budget-aware: track tool schema tokens, enforce limits
- **Checkpoint**: add 20+ tools via MCP, verify prompt stays small until tools are searched
- **Reference**: Claude Code's `ToolSearch` pattern (not in OpenCode/OpenClaw — they send all tools upfront)
- **Note**: Neither OpenCode nor OpenClaw implements this. Claude Code is the reference.

---

## Layer 12 — Long-term Memory

Persistent memory system that survives across sessions and compactions.

- [ ] File-first design: MEMORY.md canonical, always loaded into system prompt
- [ ] Memory types: user preferences, project context, discoveries
- [ ] Memory tools: `memory_save`, `memory_search`
- [ ] Optional: SQLite index with hybrid search (vector + BM25)
- [ ] Pre-compaction flush: save important context before compact
- **Checkpoint**: sbot remembers user preferences across sessions
- **Reference**: `docs/tech/openclaw/long-term-memory.md`

---

## Low Priority — Review MAX_HISTORY_MESSAGES cap

`session.py:MAX_HISTORY_MESSAGES = 100` arbitrarily caps loaded messages. Auto-compact (Layer 8) already handles context overflow — this cap may be redundant and caused the orphaned ToolMessage bug (truncating mid-tool-call sequence). Consider removing it entirely or replacing with a token-based limit. If kept, the truncation must respect message boundaries (current fix walks to first HumanMessage).

---

## Layer 13 — Provider abstraction

- [ ] Base provider interface (swap models without touching agent loop)
- [ ] Retry wrapper for transient failures
- [ ] Support multiple providers (MiniMax, Claude, OpenAI)
- [ ] **Model-aware prompt formatter**: injection format (XML tags for Claude, lean markdown for MiniMax, etc.) adapts per provider. Covers: system prompt sections, memory injection, skill listing, compact summaries. Consider: if user switches model mid-session, does the cached prompt prefix (key caching) conflict with the new format?
- **Reference**: `nanobot/providers/`, OpenCode `ai` SDK pattern

---

## Layer 14 — Cron + heartbeat

- [ ] Persistent job store
- [ ] Cron tool so the agent can schedule tasks
- [ ] Heartbeat service (periodic check)
- **Reference**: `nanobot/cron/`, `nanobot/heartbeat/`

---

## Layer 15 — More channels + group chat

- [ ] Facebook Messenger channel (webhook + Graph API)
- [ ] Slack channel
- [ ] Telegram group support (@sbot mention-based invocation)
- [ ] Per-sender context in group chats
- **Checkpoint**: multiple channels + group chat working simultaneously

---

## Layer 16 — Obsidian / PKM Integration ⚠️ IMPORTANT

Lower priority but high value. Connect sbot to user's Obsidian vault so it can read/write notes, manage Kanban tasks, search knowledge base.

- [ ] Read/write notes in Obsidian vault (`$MY_PKM_PATH`)
- [ ] Navigate vault structure (folders, tags, links)
- [ ] Search notes by keyword and semantic meaning (via qmd: BM25 + vector)
- [ ] Manage Kanban board tasks (inbox, in-progress, done)
- [ ] Organize inbox items
- [ ] Could be implemented as a skill (Layer 10) or MCP server (Layer 9)
- **Checkpoint**: ask sbot "what's in my inbox?" from Telegram, get Obsidian inbox items
- **Reference**: Claude Code's `use-my-pkm` skill, `$MY_PKM_PATH` env var