"""Telegram channel — receives messages via polling, sends via async queue.

Supports both private (DM) and group chats. In groups, the bot only responds
when mentioned (@botname) or when a user replies to the bot's message.
"""

import asyncio
import os
import re
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from ..bus import InboundMessage, MsgType, OutboundMessage
import telegramify_markdown
from .base import BaseChannel, register_channel

logger = logging.getLogger(__name__)

_GROUP_CHAT_TYPES = {"group", "supergroup"}


@register_channel
class TelegramChannel(BaseChannel):
    """Telegram bot channel. Uses polling for inbound, async queue for outbound."""

    channel_name = "telegram"
    env_token_var = "TELEGRAM_BOT_TOKEN"

    def __init__(self, bus):
        super().__init__("telegram", bus)
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._env_path = Path(".env")
        self._send_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._app: Application | None = None
        bus.register_channel(self.name, self._on_outbound)

    def _load_allowed_ids(self) -> set[int]:
        """Read allowlist fresh from .env file each time (hot-reload)."""
        raw = ""
        if self._env_path.exists():
            for line in self._env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("TELEGRAM_ALLOWED_CHAT_IDS="):
                    raw = line.split("=", 1)[1].strip()
                    break
        if not raw:
            raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        if not raw.strip():
            return set()  # empty = allow all
        return {int(x.strip()) for x in raw.split(",") if x.strip()}

    def is_allowed(self, chat_id: str) -> bool:
        allowed = self._load_allowed_ids()
        if not allowed:
            return True  # no allowlist = allow all
        return int(chat_id) in allowed

    def _on_outbound(self, msg: OutboundMessage):
        """Sync callback from bus — queues for async sending. Non-blocking."""
        self._send_queue.put_nowait(msg)

    def _is_group_chat(self, update: Update) -> bool:
        return update.message.chat.type in _GROUP_CHAT_TYPES

    def _is_bot_mentioned(self, text: str, bot_username: str) -> bool:
        """Check if @bot_username appears in the message text."""
        return f"@{bot_username}" in text

    def _is_reply_to_bot(self, update: Update, bot_username: str) -> bool:
        """Check if the message is a reply to one of the bot's messages."""
        reply = update.message.reply_to_message
        if not reply or not reply.from_user:
            return False
        return reply.from_user.is_bot and reply.from_user.username == bot_username

    def _strip_mention(self, text: str, bot_username: str) -> str:
        """Remove @bot_username from text and clean up whitespace."""
        cleaned = re.sub(rf"@{re.escape(bot_username)}\b", "", text)
        return re.sub(r"\s+", " ", cleaned).strip()
        # \b ensures we don't strip partial matches like @sbot_ai_v2

    async def _sender_loop(self):
        """Background task: consume send queue, POST to Telegram API.

        Progress events (thinking, tool_call, tool_result) each send a NEW
        message so the full process is visible as it happens. When the final
        RESPONSE arrives, all intermediate messages are bulk-deleted and only
        the answer remains.
        """
        # Track all intermediate message IDs per chat_id for bulk delete at end
        progress_msgs: dict[str, list[int]] = {}  # chat_id -> [message_id, ...]

        while True:
            msg = await self._send_queue.get()
            chat_id = int(msg.chat_id)
            reply_to = msg.metadata.get("reply_to_message_id") if msg.metadata.get("is_group") else None
            try:
                if msg.message_type in (MsgType.THINKING, MsgType.TOOL_CALL, MsgType.TOOL_RESULT):
                    sent = await self._app.bot.send_message(
                        chat_id=chat_id,
                        text=msg.text[:4096],
                        **({"reply_to_message_id": reply_to} if reply_to else {}),
                    )
                    progress_msgs.setdefault(msg.chat_id, []).append(sent.message_id)

                elif msg.message_type in (MsgType.RESPONSE, MsgType.ERROR):
                    # Bulk-delete all intermediate messages
                    for mid in progress_msgs.pop(msg.chat_id, []):
                        try:
                            await self._app.bot.delete_message(chat_id=chat_id, message_id=mid)
                        except Exception:
                            pass

                    # Send final response with formatting
                    await self._send_formatted(chat_id, msg.text, reply_to=reply_to)

            except Exception as e:
                logger.error(f"Telegram send failed: {e}")

    async def _send_formatted(self, chat_id: int, text: str, reply_to: int | None = None):
        """Send a message with MarkdownV2 formatting, fallback to plain text."""
        formatted = telegramify_markdown.markdownify(text)
        reply_kwargs = {"reply_to_message_id": reply_to} if reply_to else {}
        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=formatted,
                parse_mode="MarkdownV2",
                **reply_kwargs,
            )
        except Exception:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=None,
                **reply_kwargs,
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

        is_group = self._is_group_chat(update)
        bot_username = context.bot.username

        # In groups, only respond when mentioned or replied to
        if is_group:
            mentioned = self._is_bot_mentioned(text, bot_username)
            replied = self._is_reply_to_bot(update, bot_username)
            if not mentioned and not replied:
                return  # ignore messages not directed at bot
            # Strip @mention from text
            if mentioned:
                text = self._strip_mention(text, bot_username)
                if not text:
                    return  # empty after stripping mention

        # Build metadata
        metadata = {
            "is_group": is_group,
            "message_id": update.message.message_id,
            "sender_name": update.message.from_user.first_name,
            "sender_username": update.message.from_user.username,
        }

        logger.info(f"Telegram: received from {chat_id} ({'group' if is_group else 'dm'}): {text[:50]}...")
        await self.bus.inbound.put(InboundMessage(
            channel=self.name,
            chat_id=chat_id,
            text=text,
            metadata=metadata,
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
