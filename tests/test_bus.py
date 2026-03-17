"""Tests for sbot.bus — MessageBus, MsgType, dataclasses.

Coverage target: 60%+ (infra/glue)
"""

import asyncio

import pytest

from sbot.bus import InboundMessage, MessageBus, MsgType, OutboundMessage


class TestMsgType:
    def test_values(self):
        assert MsgType.THINKING == "thinking"
        assert MsgType.TOOL_CALL == "tool_call"
        assert MsgType.TOOL_RESULT == "tool_result"
        assert MsgType.RESPONSE == "response"
        assert MsgType.ERROR == "error"
        assert MsgType.STATUS == "status"

    def test_is_str(self):
        assert isinstance(MsgType.RESPONSE, str)


class TestInboundMessage:
    def test_defaults(self):
        msg = InboundMessage(channel="cli", chat_id="1", text="hello")
        assert msg.channel == "cli"
        assert msg.chat_id == "1"
        assert msg.text == "hello"
        assert msg.metadata == {}

    def test_with_metadata(self):
        msg = InboundMessage(channel="telegram", chat_id="42", text="hi", metadata={"key": "val"})
        assert msg.metadata == {"key": "val"}


class TestOutboundMessage:
    def test_defaults(self):
        msg = OutboundMessage(channel="cli", chat_id="1", text="reply")
        assert msg.message_type == MsgType.RESPONSE
        assert msg.metadata == {}

    def test_custom_type(self):
        msg = OutboundMessage(channel="cli", chat_id="1", text="err", message_type=MsgType.ERROR)
        assert msg.message_type == MsgType.ERROR


class TestMessageBus:
    def test_register_and_emit(self, bus, captured_messages):
        msg = OutboundMessage(channel="test", chat_id="1", text="hello")
        bus.emit(msg)
        assert len(captured_messages) == 1
        assert captured_messages[0].text == "hello"

    def test_emit_unknown_channel_does_not_crash(self, bus):
        msg = OutboundMessage(channel="nonexistent", chat_id="1", text="hello")
        bus.emit(msg)  # should not raise

    def test_multiple_channels(self):
        bus = MessageBus()
        ch1_msgs, ch2_msgs = [], []
        bus.register_channel("ch1", lambda m: ch1_msgs.append(m))
        bus.register_channel("ch2", lambda m: ch2_msgs.append(m))

        bus.emit(OutboundMessage(channel="ch1", chat_id="1", text="a"))
        bus.emit(OutboundMessage(channel="ch2", chat_id="1", text="b"))

        assert len(ch1_msgs) == 1
        assert len(ch2_msgs) == 1
        assert ch1_msgs[0].text == "a"
        assert ch2_msgs[0].text == "b"

    @pytest.mark.asyncio
    async def test_inbound_queue(self, bus):
        msg = InboundMessage(channel="cli", chat_id="1", text="test")
        await bus.inbound.put(msg)
        got = await asyncio.wait_for(bus.inbound.get(), timeout=1.0)
        assert got.text == "test"
