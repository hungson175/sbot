"""Tests for sbot.channels.telegram — TelegramChannel with group chat support.

Coverage target: 60%+ (infra/glue channel)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from sbot.bus import InboundMessage, MessageBus, MsgType, OutboundMessage


def _make_update(
    text="hello",
    chat_id=123,
    chat_type="private",
    user_first_name="Son",
    user_username="sonph",
    reply_to_bot=False,
    bot_username="sbot_ai",
):
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.chat.id = chat_id
    update.message.chat.type = chat_type
    update.message.from_user.first_name = user_first_name
    update.message.from_user.username = user_username
    update.message.message_id = 42

    if reply_to_bot:
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.from_user.is_bot = True
        update.message.reply_to_message.from_user.username = bot_username
    else:
        update.message.reply_to_message = None

    return update


def _make_context(bot_username="sbot_ai"):
    """Create a mock CallbackContext with bot info."""
    context = MagicMock()
    context.bot.username = bot_username
    return context


@pytest.fixture
def telegram_channel(bus, monkeypatch, tmp_path):
    """Create TelegramChannel with mocked token and no allowlist."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    from sbot.channels.telegram import TelegramChannel
    ch = TelegramChannel(bus)
    ch._env_path = tmp_path / ".env.nonexistent"  # no .env = allow all
    return ch


class TestGroupDetection:
    """Bot should only respond in groups when mentioned or replied to."""

    @pytest.mark.asyncio
    async def test_private_message_always_processed(self, telegram_channel, bus):
        """DMs are always processed regardless of mention."""
        update = _make_update(text="hello", chat_type="private")
        context = _make_context()

        await telegram_channel._handle_message(update, context)

        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "hello"

    @pytest.mark.asyncio
    async def test_group_message_with_mention_processed(self, telegram_channel, bus):
        """Group message mentioning @bot should be processed."""
        update = _make_update(
            text="@sbot_ai what's the weather?",
            chat_type="group",
            chat_id=-100123,
        )
        context = _make_context()

        await telegram_channel._handle_message(update, context)

        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "what's the weather?"  # mention stripped

    @pytest.mark.asyncio
    async def test_group_message_without_mention_ignored(self, telegram_channel, bus):
        """Group message without mention or reply should be ignored."""
        update = _make_update(
            text="just chatting with friends",
            chat_type="group",
            chat_id=-100123,
        )
        context = _make_context()

        await telegram_channel._handle_message(update, context)

        assert bus.inbound.empty()

    @pytest.mark.asyncio
    async def test_group_reply_to_bot_processed(self, telegram_channel, bus):
        """Replying to bot's message in group should trigger response."""
        update = _make_update(
            text="can you explain more?",
            chat_type="group",
            chat_id=-100123,
            reply_to_bot=True,
        )
        context = _make_context()

        await telegram_channel._handle_message(update, context)

        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "can you explain more?"

    @pytest.mark.asyncio
    async def test_supergroup_with_mention_processed(self, telegram_channel, bus):
        """Supergroup (large group) should work the same as group."""
        update = _make_update(
            text="@sbot_ai help me",
            chat_type="supergroup",
            chat_id=-100456,
        )
        context = _make_context()

        await telegram_channel._handle_message(update, context)

        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "help me"


class TestMentionStripping:
    """@botname should be stripped from message text."""

    @pytest.mark.asyncio
    async def test_mention_at_start(self, telegram_channel, bus):
        update = _make_update(text="@sbot_ai hello world", chat_type="group", chat_id=-100)
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "hello world"

    @pytest.mark.asyncio
    async def test_mention_at_end(self, telegram_channel, bus):
        update = _make_update(text="hello @sbot_ai", chat_type="group", chat_id=-100)
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "hello"

    @pytest.mark.asyncio
    async def test_mention_in_middle(self, telegram_channel, bus):
        update = _make_update(text="hey @sbot_ai what up", chat_type="group", chat_id=-100)
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "hey what up"

    @pytest.mark.asyncio
    async def test_only_mention_becomes_empty_ignored(self, telegram_channel, bus):
        """Message that's only the mention should be ignored (empty after strip)."""
        update = _make_update(text="@sbot_ai", chat_type="group", chat_id=-100)
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        assert bus.inbound.empty()

    @pytest.mark.asyncio
    async def test_no_mention_stripping_in_private(self, telegram_channel, bus):
        """Private messages shouldn't strip @mentions (they're part of the text)."""
        update = _make_update(text="@sbot_ai hello", chat_type="private")
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.text == "@sbot_ai hello"


class TestSenderMetadata:
    """Group messages should include sender info in metadata."""

    @pytest.mark.asyncio
    async def test_group_message_includes_sender_name(self, telegram_channel, bus):
        update = _make_update(
            text="@sbot_ai hi",
            chat_type="group",
            chat_id=-100,
            user_first_name="Alice",
            user_username="alice99",
        )
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.metadata["sender_name"] == "Alice"
        assert msg.metadata["sender_username"] == "alice99"

    @pytest.mark.asyncio
    async def test_private_message_includes_sender(self, telegram_channel, bus):
        update = _make_update(text="hello", chat_type="private", user_first_name="Son")
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.metadata.get("sender_name") == "Son"

    @pytest.mark.asyncio
    async def test_group_message_includes_message_id(self, telegram_channel, bus):
        """message_id needed for reply_to_message_id in responses."""
        update = _make_update(text="@sbot_ai hi", chat_type="group", chat_id=-100)
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.metadata["message_id"] == 42

    @pytest.mark.asyncio
    async def test_group_flag_in_metadata(self, telegram_channel, bus):
        update = _make_update(text="@sbot_ai hi", chat_type="group", chat_id=-100)
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.metadata["is_group"] is True

    @pytest.mark.asyncio
    async def test_private_not_group(self, telegram_channel, bus):
        update = _make_update(text="hi", chat_type="private")
        context = _make_context()
        await telegram_channel._handle_message(update, context)
        msg = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert msg.metadata["is_group"] is False


class TestReplyThreading:
    """In groups, bot should reply to the triggering message."""

    @pytest.mark.asyncio
    async def test_group_response_uses_reply_to(self, telegram_channel):
        """Sender loop should use reply_to_message_id for group responses."""
        telegram_channel._app = MagicMock()
        mock_send = AsyncMock(return_value=MagicMock(message_id=99))
        telegram_channel._app.bot.send_message = mock_send

        msg = OutboundMessage(
            channel="telegram",
            chat_id="-100123",
            text="Here's the answer",
            message_type=MsgType.RESPONSE,
            metadata={"reply_to_message_id": 42, "is_group": True},
        )
        telegram_channel._send_queue.put_nowait(msg)

        # Run one iteration of sender loop
        task = asyncio.create_task(telegram_channel._sender_loop())
        await asyncio.sleep(0.1)
        task.cancel()

        mock_send.assert_called()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs.get("reply_to_message_id") == 42

    @pytest.mark.asyncio
    async def test_private_response_no_reply_to(self, telegram_channel):
        """Private messages should not use reply_to_message_id."""
        telegram_channel._app = MagicMock()
        mock_send = AsyncMock(return_value=MagicMock(message_id=99))
        telegram_channel._app.bot.send_message = mock_send

        msg = OutboundMessage(
            channel="telegram",
            chat_id="123",
            text="Here's the answer",
            message_type=MsgType.RESPONSE,
            metadata={"is_group": False},
        )
        telegram_channel._send_queue.put_nowait(msg)

        task = asyncio.create_task(telegram_channel._sender_loop())
        await asyncio.sleep(0.1)
        task.cancel()

        mock_send.assert_called()
        call_kwargs = mock_send.call_args[1]
        assert "reply_to_message_id" not in call_kwargs or call_kwargs.get("reply_to_message_id") is None


class TestAllowlist:
    """Allowlist should support both positive (DM) and negative (group) chat IDs."""

    def test_negative_group_id_in_allowlist(self, bus, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_ALLOWED_CHAT_IDS=123,-100456\n")
        from sbot.channels.telegram import TelegramChannel
        ch = TelegramChannel(bus)
        ch._env_path = env_file
        assert ch.is_allowed("123")
        assert ch.is_allowed("-100456")
        assert not ch.is_allowed("999")

    def test_hot_reload_allowlist(self, bus, monkeypatch, tmp_path):
        """Allowlist should pick up changes without restart."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_ALLOWED_CHAT_IDS=123\n")
        from sbot.channels.telegram import TelegramChannel
        ch = TelegramChannel(bus)
        ch._env_path = env_file
        assert ch.is_allowed("123")
        assert not ch.is_allowed("456")

        # Update .env — should take effect immediately
        env_file.write_text("TELEGRAM_ALLOWED_CHAT_IDS=123,456\n")
        assert ch.is_allowed("456")
