# Architectural Decisions — sbot

## Isolated agents per channel (not shared)
Each channel gets its own bus + LLM + agent_loop. Channels don't share agent state.
**Why:** If one channel crashes, others keep working. Naturally isolated sessions. Can scale independently. LLM is a remote API call, no local model to share.
**Trade-off:** Multiple Python tasks per process (minimal overhead since LLM is HTTP).

## Sync callback outbound (not async queues)
`bus.emit()` calls a sync callback directly. No async queue for outbound delivery.
**Why:** Async queue-based outbound caused buffered output — all messages dumped at once. `asyncio.sleep(0)` yields are non-deterministic with 3+ tasks.
**Trade-off:** Network channels (Telegram) must queue internally to avoid blocking the agent on HTTP calls.

## Channel auto-discovery via decorator
`@register_channel` + `get_enabled_channel_classes()` — channels self-register, gateway discovers enabled ones by checking env vars.
**Why:** Open/closed principle. Adding a new channel = new file + import in `__init__.py` + env var. Zero changes to app.py.

## Tool descriptions in .txt files (not docstrings)
`@tool(description=_load_description("name"))` loads from `prompts/tools/*.txt`.
**Why:** Iterate on descriptions without touching Python. `.bind_tools()` sends them automatically — no duplication in system prompt.

## No ask_user tool
Agent is autonomous — never asks questions. `ask_user` caused stdin race with CLI channel and would hang in non-terminal channels.

## Future: External message broker (Redis/NATS)
Current bus is in-process Python object. When scaling requires it, extract to an external message broker:
- **When**: channels need to run on different machines, or `sleep(0.05)` hack becomes a problem with 5+ channels
- **Approach**: Redis Streams or NATS. Agent publishes to `outbound:{channel}` stream, each channel process subscribes to its own stream.
- **Why it's easy**: current `MessageBus` interface (`bus.inbound.put()`, `bus.emit()`) is clean enough that swapping to Redis is a localized change — agent and channels don't need to know.
- **Gains**: process isolation (crash safety), independent scaling, natural delivery timing (no sleep hacks), message replay/monitoring
- **Costs**: external dependency, network serialization, deployment complexity

## exec_cmd background mode
`background=true` starts process with `Popen` + `start_new_session=True`, returns PID immediately.
**Why:** Without it, `npm start` or `python server.py` blocks the agent forever.
