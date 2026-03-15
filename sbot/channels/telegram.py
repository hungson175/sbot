"""Telegram channel — receives messages via polling, sends via async queue."""

import asyncio
import os
import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from ..bus import InboundMessage, MsgType, OutboundMessage
import telegramify_markdown
from .base import BaseChannel, register_channel

logger = logging.getLogger(__name__)


@register_channel
class TelegramChannel(BaseChannel):
    """Telegram bot channel. Uses polling for inbound, async queue for outbound."""

    channel_name = "telegram"
    env_token_var = "TELEGRAM_BOT_TOKEN"

    def __init__(self, bus):
        super().__init__("telegram", bus)
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._allowed_ids = self._parse_allowed_ids()
        self._send_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._app: Application | None = None
        bus.register_channel(self.name, self._on_outbound)

    def _parse_allowed_ids(self) -> set[int]:
        raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        if not raw.strip():
            return set()  # empty = allow all
        return {int(x.strip()) for x in raw.split(",") if x.strip()}

    def is_allowed(self, chat_id: str) -> bool:
        if not self._allowed_ids:
            return True  # no allowlist = allow all
        return int(chat_id) in self._allowed_ids

    def _on_outbound(self, msg: OutboundMessage):
        """Sync callback from bus — queues for async sending. Non-blocking."""
        self._send_queue.put_nowait(msg)

    async def _sender_loop(self):
        """Background task: consume send queue, POST to Telegram API.

        Progress events (thinking, tool_call, tool_result) update a single
        status message in-place. The final RESPONSE is sent as a new message.
        """
        # Track the live status message per chat_id
        status_msgs: dict[str, int] = {}  # chat_id → message_id

        while True:
            msg = await self._send_queue.get()
            chat_id = int(msg.chat_id)
            try:
                if msg.message_type in (MsgType.THINKING, MsgType.TOOL_CALL, MsgType.TOOL_RESULT):
                    # Progress: edit existing status message or create one
                    status_text = msg.text[:4000]  # Telegram limit ~4096
                    if msg.chat_id in status_msgs:
                        try:
                            await self._app.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=status_msgs[msg.chat_id],
                                text=f"⏳ {status_text}",
                            )
                        except Exception:
                            pass  # edit can fail if text unchanged
                    else:
                        sent = await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=f"⏳ {status_text}",
                        )
                        status_msgs[msg.chat_id] = sent.message_id

                elif msg.message_type in (MsgType.RESPONSE, MsgType.ERROR):
                    # Delete the status message
                    if msg.chat_id in status_msgs:
                        try:
                            await self._app.bot.delete_message(
                                chat_id=chat_id,
                                message_id=status_msgs.pop(msg.chat_id),
                            )
                        except Exception:
                            status_msgs.pop(msg.chat_id, None)

                    # Send final response with formatting
                    await self._send_formatted(chat_id, msg.text)

            except Exception as e:
                logger.error(f"Telegram send failed: {e}")

    async def _send_formatted(self, chat_id: int, text: str):
        """Send a message with MarkdownV2 formatting, fallback to plain text."""
        formatted = telegramify_markdown.markdownify(text)
        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=formatted,
                parse_mode="MarkdownV2",
            )
        except Exception:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=None,
            )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming Telegram message."""
        if not update.message or not update.message.text:
            return

        chat_id = str(update.message.chat_id)
        if not self.is_allowed(chat_id):
            logger.warning(f"Telegram: blocked message from {chat_id}")
            return

        text = update.message.text.strip()
        if not text:
            return

        logger.info(f"Telegram: received from {chat_id}: {text[:50]}...")
        await self.bus.inbound.put(InboundMessage(
            channel=self.name,
            chat_id=chat_id,
            text=text,
        ))

    async def start(self):
        """Start Telegram polling + sender loop."""
        if not self._token:
            logger.warning("Telegram: no TELEGRAM_BOT_TOKEN, skipping")
            return

        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message,
        ))

        # Start sender loop
        asyncio.create_task(self._sender_loop())

        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram: polling started")

    async def stop(self):
        """Stop Telegram polling."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram: stopped")

    async def send(self, msg: OutboundMessage):
        """For BaseChannel interface — delegates to queue."""
        self._on_outbound(msg)
