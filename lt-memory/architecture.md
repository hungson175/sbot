# Architecture — sbot

Reimplementation of nanobot. Reference: `../../docs/tech/architecture-overview.md`

## Core Components

### AgentLoop (`sbot/agent/loop.py`)
Orchestration core. Receives inbound messages, builds context, runs iterative LLM tool-calling loop, persists sessions, publishes outbound replies.

Turn lifecycle:
1. Receive InboundMessage from bus
2. Resolve session, load/create
3. Optionally consolidate old context (token budget)
4. Build message payload: system prompt + session history + runtime metadata + user message
5. Iterative LLM loop: call provider → if tool calls, execute + append results → repeat; else finalize
6. Persist turn to session JSONL
7. Trigger memory consolidation check
8. Publish OutboundMessage

### MessageBus (`sbot/bus/`)
Async inbound/outbound queues decoupling channels from agent. Events: InboundMessage, OutboundMessage.

### Providers (`sbot/providers/`)
LLM provider abstraction. Standard response shape (LLMResponse + ToolCallRequest). Retry wrapper. Provider/model resolution. Primary impl via LiteLLM.

### Channels (`sbot/channels/`)
BaseChannel interface: `start()`, `stop()`, `send()`, `is_allowed()`. ChannelManager auto-discovers and manages lifecycle. Each channel publishes inbound to bus, consumes outbound.

### Sessions (`sbot/session/`)
Append-only JSONL files. First line = metadata. Remaining lines = conversation messages.

### Tools (`sbot/agent/tools/`)
Tool base class with name, description, parameters (JSON schema), execute(). Default tools: read_file, write_file, edit_file, list_dir, exec, web_search, web_fetch, message, spawn, cron. Plus dynamic MCP tools.

### Memory (`sbot/agent/memory.py`)
Token-aware consolidation. When prompt exceeds context window, older turns consolidated into MEMORY.md (long-term state) and HISTORY.md (timestamped log). Uses LLM save_memory tool call with raw-archive fallback.

### Config (`sbot/config/`)
Pydantic schema. Default path `~/.sbot/config.json`. Runtime dirs derived from config location. Workspace stores prompts, memory, sessions, skills.

### Cron (`sbot/cron/`)
Persistent job store (jobs.json). Schedule types: at (one-time), every (interval), cron (expression). Callbacks execute through main agent loop.

### Heartbeat (`sbot/heartbeat/`)
Periodic check of HEARTBEAT.md. Two-phase: ask model skip/run, then execute only if needed.

### Subagents (`sbot/agent/subagent.py`)
spawn tool delegates to SubagentManager. Background task with scoped toolset (no recursive spawn/message). Reports back via synthetic system message.

## Startup Topologies

### CLI mode (`sbot agent`)
Load config → build provider + AgentLoop → interactive bus loop or single-message process_direct()

### Gateway mode (`sbot gateway`)
Load config → instantiate MessageBus, provider, SessionManager, CronService, AgentLoop, ChannelManager, HeartbeatService → start all concurrently → shutdown closes MCP, stops services
