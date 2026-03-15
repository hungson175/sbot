# Nanobot Architecture Overview

## What It Is

`nanobot` is an event-driven personal AI assistant framework (~14k lines Python).
Core idea: a single agent loop consumes messages from any source, calls an LLM with tools, and sends replies back.

## High-Level Data Flow

```
[Input Sources]           [Core]                    [Integrations]
  CLI ──────────┐
  Telegram ─────┤       MessageBus
  Discord ──────┼──→  (inbound queue)
  Slack ────────┤         │
  Cron ─────────┘         ▼
                     AgentLoop ──→ LLM Provider
                      │  │  │         (LiteLLM / Azure / Custom)
                      │  │  │
                      │  │  └──→ ToolRegistry
                      │  │         (exec, read/write/edit, web, cron, mcp, spawn)
                      │  │
                      │  └──→ ContextBuilder
                      │         (SOUL.md + AGENTS.md + MEMORY.md + skills)
                      │
                      └──→ SessionManager
                             (JSONL per conversation)
                      │
                      ▼
                  MessageBus
                (outbound queue) ──→ ChannelManager ──→ back to input sources
```

## Key Components

### Agent Loop (`agent/loop.py` — 2,239 lines)
The brain. Receives inbound messages, builds context, calls LLM in a tool-calling loop (max 40 iterations), persists session, triggers memory consolidation, publishes response.

### Message Bus (`bus/queue.py`)
Two `asyncio.Queue`s — inbound and outbound. This is what decouples channels from the agent. Channels push to inbound, agent pushes to outbound, channels consume outbound.

### Context Builder (`agent/context.py`)
Assembles the system prompt from multiple sources:
1. Identity info (platform, Python version)
2. Bootstrap files: SOUL.md, AGENTS.md, USER.md, TOOLS.md
3. Long-term memory (MEMORY.md)
4. Active skills + skills summary

### Session Manager (`session/manager.py` — 213 lines)
JSONL storage. First line = metadata (`created_at`, `last_consolidated`), rest = append-only messages. Session key = `channel:chat_id`. Tracks what's been consolidated so memory doesn't re-summarize.

### Memory System (`agent/memory.py`)
Two files:
- **MEMORY.md** — current long-term facts (updated by LLM consolidation)
- **HISTORY.md** — timestamped log of all consolidation summaries

Triggers when prompt token count approaches context window limit. Uses LLM `save_memory` tool call, with raw-archive fallback on failure.

### Tool System (`agent/tools/`)
Abstract `Tool` base class with `name`, `description`, `parameters` (JSON schema), `execute()`.
`ToolRegistry` stores and dispatches tools. Built-in tools:
- **Filesystem**: read_file, write_file, edit_file, list_dir
- **Shell**: exec (with deny patterns + optional workspace restriction)
- **Web**: web_search (Brave API), web_fetch
- **Messaging**: send_message (inter-channel)
- **Scheduling**: cron
- **Delegation**: spawn (background subagents)
- **Dynamic**: mcp_<server>_<tool>

### Provider System (`providers/`)
Abstract `LLMProvider` with `chat()` / `chat_with_retry()`. Key shapes: `LLMResponse`, `ToolCallRequest`, `GenerationSettings`.
`ProviderRegistry` handles resolution by model prefix/keywords/env keys.
Implementations: LiteLLM (covers 100+ models), Azure OpenAI, OpenAI Codex (OAuth), Custom template.

### Channel System (`channels/`)
Abstract `BaseChannel`: `start()`, `stop()`, `send()`, `is_allowed()`.
12 implementations: Telegram, Discord, Slack, Feishu, DingTalk, WeChat Work, QQ, WhatsApp, Matrix, MoChat, Email.
`ChannelManager` auto-discovers from `channels/` directory, starts only enabled ones.

### Skills System (`skills/`)
SKILL.md markdown files with frontmatter. Loaded from workspace (`skills/*/SKILL.md`) or built-in. Workspace overrides built-in. Skills can declare requirements (bins/env).
Built-in: memory consolidation, cron reminders, tmux control, GitHub, weather, summarization, skill creator.

### Config System (`config/`)
Pydantic models for everything. `config.json` at `~/.nanobot/`. Supports camelCase/snake_case aliases. Per-channel config with enable/allowlist fields.

## Startup Modes

### `nanobot agent` (CLI mode)
1. Load config → build provider → build AgentLoop
2. Single-message: call `process_direct()` and exit
3. Interactive: start bus + loop, stream replies

### `nanobot gateway` (multi-channel mode)
1. Load config → instantiate: MessageBus, provider, SessionManager, CronService, AgentLoop, ChannelManager, HeartbeatService
2. Start all concurrently
3. Shutdown: close MCP → stop heartbeat/cron → stop channels

## Background Services

**CronService** — persistent jobs (`cron/jobs.json`), supports `at`/`every`/`cron expr`, fires callback through main agent loop.

**HeartbeatService** — reads HEARTBEAT.md on interval, asks model `skip|run` via virtual tool call, only runs full agent when needed.

**SubagentManager** — spawned by `spawn` tool. Scoped toolset (file/shell/web, no recursive spawn). Reports back via synthetic `system` message to bus.

## WhatsApp Bridge

Node.js (`bridge/`) instead of Python SDK. Binds WebSocket on 127.0.0.1, handles QR login, media download, message relay. Python side manages lifecycle.

## Security

- Optional `tools.restrictToWorkspace` sandbox
- `exec` blocks dangerous command patterns
- Empty `allow_from` = deny all
- MCP has per-server timeouts + lazy connection
