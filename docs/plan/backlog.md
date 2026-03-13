# sbot Rebuild Backlog

Rebuild roadmap following the reverse engineering playbook (`../../docs/tech/reverse-engineering-playbook.md`).

## Stage 0 — Mental Model
- [ ] Read `nanobot/cli/commands.py`
- [ ] Read `nanobot/agent/loop.py`
- [ ] Read `nanobot/bus/events.py` and `nanobot/bus/queue.py`
- [ ] Read `nanobot/config/schema.py`
- [ ] Can explain end-to-end message flow in <2 minutes

## Stage 1 — Minimal Core (CLI bot)
- [ ] Project scaffolding (pyproject.toml, package structure)
- [ ] Config schema (pydantic, minimal fields)
- [ ] Session persistence (append-only JSONL)
- [ ] Tool base class + registry + one tool (read_file or exec)
- [ ] Agent loop: message loop with max tool iterations
- [ ] LLM provider: one concrete impl (LiteLLM)
- [ ] CLI entrypoint: interactive prompt → agent → print response
- [ ] **Checkpoint**: handles a prompt requiring 2+ sequential tool calls

## Stage 2 — Provider Abstraction
- [ ] Provider base interface (LLMResponse + ToolCallRequest shapes)
- [ ] Retry wrapper for transient failures
- [ ] Provider/model resolution strategy
- [ ] Input normalization/sanitization
- [ ] **Checkpoint**: swap model/provider without changing loop logic

## Stage 3 — Channel Gateway
- [ ] MessageBus (async inbound/outbound queues)
- [ ] BaseChannel interface + ChannelManager
- [ ] Channel allowlist policy
- [ ] One real channel adapter (Telegram or Slack)
- [ ] Gateway startup topology
- [ ] **Checkpoint**: same prompt works from CLI and channel with identical core loop

## Stage 4 — Memory Compaction
- [ ] Prompt token estimation
- [ ] Turn-boundary-safe consolidation
- [ ] MEMORY.md + HISTORY.md generation via LLM
- [ ] Fallback when memory-consolidation LLM call fails
- [ ] **Checkpoint**: long sessions stay functional without blowing context

## Stage 5 — Background Scheduling
- [ ] Persistent job store (jobs.json)
- [ ] Schedule types: at, every, cron expr
- [ ] CronService with callback into core loop
- [ ] HeartbeatService (two-phase skip/run)
- [ ] **Checkpoint**: scheduled task executes and posts to live channel

## Stage 6 — Advanced Extensions
- [ ] Subagent spawn (scoped toolset, background execution)
- [ ] MCP dynamic tool discovery and registration
- [ ] WhatsApp Node bridge (optional)
- [ ] **Checkpoint**: can explain why each extension preserves modularity
