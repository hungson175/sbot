"""CLI channel — terminal interactive mode as a channel adapter."""

import asyncio

from ..bus import InboundMessage, MsgType, OutboundMessage
from .base import BaseChannel


class CLIChannel(BaseChannel):
    """Interactive CLI as a channel. Reads from stdin, writes to stdout."""

    def __init__(self, bus):
        super().__init__("cli", bus)
        self._chat_id = "local"
        self._done = asyncio.Event()
        bus.register_channel(self.name, self._on_outbound)

    def _on_outbound(self, msg: OutboundMessage):
        """Sync callback — prints immediately, no buffering."""
        match msg.message_type:
            case MsgType.THINKING:
                print(f"  {msg.text}", flush=True)
            case MsgType.TOOL_CALL:
                print(f"\n  {msg.text}", flush=True)
            case MsgType.TOOL_RESULT:
                print(f"  {msg.text}", flush=True)
            case MsgType.RESPONSE:
                print(f"\nsbot> {msg.text}\n", flush=True)
            case MsgType.ERROR:
                print(f"\n❌ {msg.text}\n", flush=True)
            case MsgType.STATUS:
                print(f"  ℹ {msg.text}", flush=True)
            case _:
                print(f"  [{msg.message_type}] {msg.text}", flush=True)

        if msg.message_type in (MsgType.RESPONSE, MsgType.ERROR):
            self._done.set()

    async def start(self):
        """Read user input in a loop, push to inbound bus."""
        print("sbot — interactive mode (Ctrl+C to exit)\n")
        loop = asyncio.get_event_loop()
        while True:
            try:
                user_input = await loop.run_in_executor(None, lambda: input("you> ").strip())
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if not user_input:
                continue
            self._done.clear()
            await self.bus.inbound.put(InboundMessage(
                channel=self.name, chat_id=self._chat_id, text=user_input,
            ))
            # Wait until agent finishes (response or error delivered)
            await self._done.wait()

    async def send(self, msg: OutboundMessage):
        """For BaseChannel interface — delegates to _on_outbound."""
        self._on_outbound(msg)

    async def stop(self):
        pass
