"""Base channel interface + auto-discovery registry."""

import os
from abc import ABC, abstractmethod

from ..bus import MessageBus, OutboundMessage


# Registry of all channel classes — populated by register_channel decorator
_CHANNEL_REGISTRY: dict[str, type["BaseChannel"]] = {}


def register_channel(cls):
    """Decorator: register a channel class in the global registry."""
    _CHANNEL_REGISTRY[cls.channel_name] = cls
    return cls


def get_enabled_channel_classes() -> list[type["BaseChannel"]]:
    """Return channel classes that have their env token set (without instantiating)."""
    return [
        cls for cls in _CHANNEL_REGISTRY.values()
        if cls.env_token_var and os.environ.get(cls.env_token_var)
    ]


class BaseChannel(ABC):
    """Abstract channel adapter. Each platform implements this."""

    channel_name: str = ""       # override in subclass: "telegram", "messenger", etc.
    env_token_var: str = ""      # override in subclass: "TELEGRAM_BOT_TOKEN", etc.

    def __init__(self, name: str, bus: MessageBus):
        self.name = name
        self.bus = bus

    @abstractmethod
    async def start(self):
        """Connect to platform and start listening."""

    @abstractmethod
    async def stop(self):
        """Graceful disconnect."""

    @abstractmethod
    async def send(self, msg: OutboundMessage):
        """Deliver a message to the platform."""

    def is_allowed(self, chat_id: str) -> bool:
        """Check if this chat_id is allowed. Override for allowlists."""
        return True
