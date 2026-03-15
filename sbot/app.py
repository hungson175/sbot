"""App entry point — interactive and gateway modes."""

import asyncio
import logging
import sys

from langchain_anthropic import ChatAnthropic

from .agent import agent_loop
from .bus import MessageBus
from .channels.base import get_enabled_channel_classes
from .channels.cli import CLIChannel
from .config import API_BASE, API_KEY, MODEL
from .tools import TOOLS

# Import channels package to trigger @register_channel decorators
import sbot.channels  # noqa: F401


def _build_llm():
    if not API_KEY:
        print("Set ANTHROPIC_AUTH_TOKEN env var (or add to .env)")
        sys.exit(1)
    llm = ChatAnthropic(
        model=MODEL,
        api_key=API_KEY,
        base_url=API_BASE,
        max_tokens=4096,
    )
    return llm.bind_tools(TOOLS)


async def main_cli():
    """Interactive CLI mode — own bus, own agent."""
    llm = _build_llm()
    bus = MessageBus()
    cli = CLIChannel(bus)

    agent_task = asyncio.create_task(agent_loop(llm, bus))
    try:
        await cli.start()
    finally:
        agent_task.cancel()


async def main_serve():
    """Gateway mode — each channel gets its own bus + agent (fully isolated)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("sbot")

    channel_classes = get_enabled_channel_classes()
    if not channel_classes:
        logger.error("No channels enabled. Set token env vars (e.g. TELEGRAM_BOT_TOKEN)")
        sys.exit(1)

    tasks = []
    channels = []
    for cls in channel_classes:
        bus = MessageBus()
        llm = _build_llm()
        ch = cls(bus)
        channels.append(ch)

        await ch.start()
        task = asyncio.create_task(agent_loop(llm, bus))
        tasks.append(task)
        logger.info(f"Channel started: {ch.name} (isolated agent)")

    logger.info(f"sbot gateway running with {len(channels)} bot(s) (Ctrl+C to stop)")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Shutting down...")
        for ch in channels:
            await ch.stop()
        for task in tasks:
            task.cancel()


def run():
    """Entry point — check for 'serve' argument."""
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        asyncio.run(main_serve())
    else:
        asyncio.run(main_cli())
