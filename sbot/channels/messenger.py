"""Facebook Messenger channel — webhook inbound, Graph API outbound."""

import asyncio
import os
import logging

import aiohttp
from aiohttp import web

from ..bus import InboundMessage, MsgType, OutboundMessage
from .base import BaseChannel, register_channel

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v21.0/me/messages"
MAX_MSG_LEN = 2000  # Messenger limit


@register_channel
class MessengerChannel(BaseChannel):
    """Facebook Messenger channel. Webhook inbound, Graph API outbound."""

    channel_name = "messenger"
    env_token_var = "MESSENGER_PAGE_TOKEN"

    def __init__(self, bus):
        super().__init__("messenger", bus)
        self._page_token = os.environ.get("MESSENGER_PAGE_TOKEN", "")
        self._verify_token = os.environ.get("MESSENGER_VERIFY_TOKEN", "")
        self._port = int(os.environ.get("MESSENGER_WEBHOOK_PORT", "8080"))
        self._allowed_ids = self._parse_allowed_ids()
        self._send_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._runner: web.AppRunner | None = None
        self._http_session: aiohttp.ClientSession | None = None
        bus.register_channel(self.name, self._on_outbound)

    def _parse_allowed_ids(self) -> set[str]:
        raw = os.environ.get("MESSENGER_ALLOWED_IDS", "")
        if not raw.strip():
            return set()
        return {x.strip() for x in raw.split(",") if x.strip()}

    def is_allowed(self, chat_id: str) -> bool:
        if not self._allowed_ids:
            return True
        return chat_id in self._allowed_ids

    # ── Webhook handlers ──────────────────────────────────────────────

    async def _handle_webhook_get(self, request: web.Request) -> web.Response:
        """Meta verification challenge — echo hub.challenge if token matches."""
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode == "subscribe" and token == self._verify_token:
            logger.info("Messenger: webhook verified")
            return web.Response(text=challenge)

        logger.warning("Messenger: webhook verification failed")
        return web.Response(status=403, text="Forbidden")

    async def _handle_webhook_post(self, request: web.Request) -> web.Response:
        """Receive inbound messages from Meta. Must return 200 quickly."""
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad JSON")

        if body.get("object") != "page":
            return web.Response(status=404, text="Not a page event")

        for entry in body.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event.get("sender", {}).get("id", "")
                message = event.get("message", {})
                text = message.get("text", "").strip()

                if not sender_id or not text:
                    continue

                if not self.is_allowed(sender_id):
                    logger.warning(f"Messenger: blocked message from {sender_id}")
                    continue

                logger.info(f"Messenger: received from {sender_id}: {text[:50]}...")
                await self.bus.inbound.put(InboundMessage(
                    channel=self.name,
                    chat_id=sender_id,
                    text=text,
                ))

        # Must return 200 within 20 seconds or Meta retries
        return web.Response(text="EVENT_RECEIVED")

    # ── Outbound ──────────────────────────────────────────────────────

    def _on_outbound(self, msg: OutboundMessage):
        """Sync callback from bus — queues for async sending."""
        self._send_queue.put_nowait(msg)

    async def _sender_loop(self):
        """Background task: consume send queue, POST to Graph API.

        Progress events send typing indicators.
        RESPONSE/ERROR send the actual message text.
        """
        while True:
            msg = await self._send_queue.get()
            try:
                if msg.message_type in (MsgType.THINKING, MsgType.TOOL_CALL, MsgType.TOOL_RESULT):
                    await self._send_typing_on(msg.chat_id)

                elif msg.message_type in (MsgType.RESPONSE, MsgType.ERROR):
                    await self._send_text(msg.chat_id, msg.text)

            except Exception as e:
                logger.error(f"Messenger send failed: {e}")

    async def _send_typing_on(self, recipient_id: str):
        """Send typing indicator to show the bot is working."""
        payload = {
            "recipient": {"id": recipient_id},
            "sender_action": "typing_on",
        }
        await self._graph_api_post(payload)

    async def _send_text(self, recipient_id: str, text: str):
        """Send text message, splitting into chunks if >2000 chars."""
        if not text:
            return

        # Split long messages into chunks
        chunks = [text[i:i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]
        for chunk in chunks:
            payload = {
                "recipient": {"id": recipient_id},
                "message": {"text": chunk},
            }
            await self._graph_api_post(payload)

    async def _graph_api_post(self, payload: dict):
        """POST to Facebook Graph API."""
        if not self._http_session:
            return
        async with self._http_session.post(
            GRAPH_API_URL,
            json=payload,
            params={"access_token": self._page_token},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(f"Messenger API error {resp.status}: {body}")

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self):
        """Start webhook server + sender loop."""
        if not self._page_token:
            logger.warning("Messenger: no MESSENGER_PAGE_TOKEN, skipping")
            return

        self._http_session = aiohttp.ClientSession()

        # Setup aiohttp web server
        app = web.Application()
        app.router.add_get("/webhook", self._handle_webhook_get)
        app.router.add_post("/webhook", self._handle_webhook_post)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()

        # Start sender loop
        asyncio.create_task(self._sender_loop())

        logger.info(f"Messenger: webhook server on port {self._port}")

    async def stop(self):
        """Stop webhook server and HTTP session."""
        if self._runner:
            await self._runner.cleanup()
        if self._http_session:
            await self._http_session.close()
        logger.info("Messenger: stopped")

    async def send(self, msg: OutboundMessage):
        """For BaseChannel interface — delegates to queue."""
        self._on_outbound(msg)
