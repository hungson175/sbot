# sbot Message Architecture

## Design Decision

Start with nanobot's simple two-queue pattern. Evolve toward OpenClaw's sophistication only when needed.

## Current State (Layer 4)

Direct CLI loop — no bus, no routing:
```
CLI input() → agent_turn() → print()
```

## Target: Two-Channel MVP (Layers 5-7)

### Core Data Structures

```python
@dataclass
class InboundMessage:
    channel: str      # "cli", "telegram", "messenger"
    chat_id: str      # unique sender/group ID per channel
    text: str
    metadata: dict    # optional: attachments, reply_to, etc.

@dataclass
class OutboundMessage:
    channel: str      # routed back to originating channel
    chat_id: str      # routed back to originating sender
    text: str
    metadata: dict
```

### Message Flow

```
[CLI]        ─┐
[Telegram]   ─┼─→  inbound queue  →  AgentLoop  →  outbound queue  ─┬─→ [CLI]
[Messenger]  ─┘         │                               │            ├─→ [Telegram]
                         │                               │            └─→ [Messenger]
                    asyncio.Queue                   asyncio.Queue
                                                    (filtered by channel)
```

### Routing Rules

1. Each inbound message carries `channel` + `chat_id`
2. Agent processes message, tags response with same `channel` + `chat_id`
3. Each channel only picks up outbound messages matching its channel name
4. No cross-talk: Telegram messages never go to Messenger

### Session Keying

```
Session key = "{channel}:{chat_id}"

Examples:
  "cli:local"              → CLI user
  "telegram:12345678"      → Telegram user
  "messenger:98765"        → Messenger user
  "telegram:group:-100123" → Telegram group chat
```

Each session has its own JSONL file: `sessions/telegram_12345678.jsonl`

### Channel Interface

```python
class BaseChannel:
    async def start(self):    ...  # Connect to platform, start listening
    async def stop(self):     ...  # Graceful disconnect
    async def send(self, msg: OutboundMessage): ...  # Deliver to platform
    def is_allowed(self, chat_id: str) -> bool:  ...  # Allowlist check
```

### ChannelManager

```python
class ChannelManager:
    channels: dict[str, BaseChannel]   # "telegram" → TelegramChannel, etc.

    async def start_all(self):         # Start enabled channels
    async def stop_all(self):          # Graceful shutdown
    async def consume_outbound(self):  # Route outbound messages to correct channel
```

### Gateway Mode

```bash
python3 -m sbot serve    # Long-lived service with all channels
python3 -m sbot          # CLI mode (still works, CLI is just another channel)
```

Gateway startup:
1. Load config
2. Create MessageBus (two asyncio.Queues)
3. Create AgentLoop (consumes inbound, publishes outbound)
4. Create ChannelManager (starts enabled channels)
5. Run all concurrently

### Agent Loop Changes

Current `agent_turn(llm, history, user_text)` becomes:
```python
async def run(self):
    while True:
        msg: InboundMessage = await self.bus.inbound.get()
        session = load_session(f"{msg.channel}:{msg.chat_id}")
        history = [SystemMessage(content=SYSTEM_PROMPT)] + session
        reply = await agent_turn(self.llm, history, msg.text)
        save_new_messages(f"{msg.channel}:{msg.chat_id}", history)
        await self.bus.outbound.put(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            text=reply,
        ))
```

## What We're NOT Doing (Yet)

These are OpenClaw features we'll add later if needed:

| Feature | Why not now | When to add |
|---------|------------|-------------|
| Queue modes (collect/steer/interrupt) | Only 1 session at a time is fine for MVP | When users complain about queued message handling |
| Lane-based concurrency | Single agent, no parallelism needed | When running multiple agents or sub-agents |
| Inbound debouncing | Can add per-channel later | When WhatsApp/Messenger users send fragmented messages |
| Message deduplication | Low traffic initially | When channel redeliveries become a problem |
| Streaming/chunking per channel | Simple text replies first | When UX demands real-time streaming |

## Implementation Order

1. **Layer 5**: `InboundMessage`/`OutboundMessage` + `MessageBus` + refactor CLI as channel + `sbot serve`
2. **Layer 6**: `BaseChannel` + `TelegramChannel` + `ChannelManager` + allowlist
3. **Layer 7**: `MessengerChannel` (webhook + Graph API)
