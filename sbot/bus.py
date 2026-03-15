"""Message bus — inbound/outbound with callback-based delivery."""

import asyncio
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable


class MsgType(StrEnum):
    THINKING = "thinking"        # iteration count, thinking blocks, token usage
    TOOL_CALL = "tool_call"      # tool name + args (before execution)
    TOOL_RESULT = "tool_result"  # tool output (after execution)
    RESPONSE = "response"        # final reply text
    ERROR = "error"              # exceptions, failures
    STATUS = "status"            # session resumed, plan updates, system info


@dataclass
class InboundMessage:
    channel: str        # "cli", "telegram", "messenger"
    chat_id: str        # unique sender/group ID per channel
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class OutboundMessage:
    channel: str        # routed back to originating channel
    chat_id: str        # routed back to originating sender
    text: str
    message_type: MsgType = MsgType.RESPONSE
    metadata: dict = field(default_factory=dict)


class MessageBus:
    """Inbound queue + synchronous callback-based outbound delivery."""

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._handlers: dict[str, Callable[[OutboundMessage], None]] = {}

    def register_channel(self, name: str, handler: Callable[[OutboundMessage], None]):
        """Register a channel with a sync callback for outbound messages."""
        self._handlers[name] = handler

    def emit(self, msg: OutboundMessage):
        """Deliver outbound message IMMEDIATELY via sync callback. No queue, no buffering."""
        handler = self._handlers.get(msg.channel)
        if handler:
            handler(msg)
            sys.stdout.flush()
