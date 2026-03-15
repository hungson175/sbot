# Runtime Flows

## Gateway Message Flow

```
User sends message
  → Channel receives it
  → Channel publishes InboundMessage to MessageBus.inbound
  → AgentLoop consumes from inbound
  → Resolves session key, loads/creates session
  → Optionally consolidates old context (token budget)
  → Builds full message payload:
      system prompt (identity + templates + memory + skills)
      + session history
      + runtime metadata
      + current user message (+ media if present)
  → Tool-calling loop:
      call provider.chat_with_retry(messages, tools)
      if tool calls → execute via ToolRegistry → append results → continue
      if final text → done
  → Saves turn to session JSONL
  → Triggers post-turn memory consolidation check
  → Publishes OutboundMessage to MessageBus.outbound
  → ChannelManager consumes outbound
  → Channel sends response to user
```

## CLI Interactive Flow

1. `nanobot agent` builds AgentLoop, starts `agent.run()` task
2. CLI publishes each user input as inbound bus message (`cli` channel)
3. Outbound consumer prints progress/tool hints + final response
4. Exit signals trigger graceful shutdown + MCP close

## Tool-Calling Loop

- Tools executed serially in call order
- Each result inserted as `role=tool` message linked by `tool_call_id`
- Loop exits on first non-tool assistant response OR max iterations hit
- On hard provider errors (`finish_reason=error`): return fallback text, don't poison session

## Session & Memory Flow

### Session persistence
- JSONL in `workspace/sessions/`
- Line 1: metadata (`created_at`, `updated_at`, `last_consolidated`)
- Remaining lines: append-only conversation messages

### Memory consolidation
- Before/after turns, estimate prompt size
- If exceeds context window: consolidate older user-turn-aligned chunks into:
  - `memory/HISTORY.md` — timestamped log entries
  - `memory/MEMORY.md` — current long-term state
- Uses LLM `save_memory` tool-call contract, with raw-archive fallback on repeated failures

## Cron Flow

```
jobs.json → CronService loads/recomputes
  → arms next timer
  → due job fires → on_job callback
  → AgentLoop.process_direct()
  → optional outbound delivery
  → update job state + next_run → persist jobs.json
```

Schedule types: `at` (one-time), `every` (fixed interval), `cron` (cron expression + optional timezone)

## Heartbeat Flow

1. Every `heartbeat.interval_s`, read HEARTBEAT.md
2. Ask model to call virtual `heartbeat` tool: `skip` (no tasks) or `run` (execute)
3. If `run`: call `on_execute` (main agent loop), then `on_notify` (deliver to channel)

Two-phase design avoids brittle free-text parsing.

## Subagent Flow

1. Main loop invokes `spawn` tool
2. SubagentManager creates background task with scoped toolset (file/shell/web; no spawn/message)
3. Subagent runs up to capped iterations
4. On completion/failure: injects synthetic `system` message into bus
5. Main loop summarizes result back to user

## MCP Integration Flow

1. Lazily connects configured MCP servers on first runtime call
2. For each discovered tool: wrap as `mcp_<server>_<tool>`, register in ToolRegistry
3. During execution: forward calls over MCP session with per-server timeout
4. Text blocks flattened into plain tool results for LLM context
