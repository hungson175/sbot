"""Tests for sbot.agent — agent loop, message processing.

Coverage target: 85%+ (core loop)
LLM calls: ALL MOCKED
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from sbot.agent import _extract_reply, _process_message, _session_key, _session_token_usage, get_current_token_usage
from sbot.bus import InboundMessage, MessageBus, MsgType, OutboundMessage


class TestSessionKey:
    def test_format(self):
        msg = InboundMessage(channel="telegram", chat_id="12345", text="hi")
        assert _session_key(msg) == "telegram_12345"

    def test_cli(self):
        msg = InboundMessage(channel="cli", chat_id="local", text="hi")
        assert _session_key(msg) == "cli_local"


class TestExtractReply:
    def test_string_content(self):
        msg = AIMessage(content="hello world")
        assert _extract_reply(msg) == "hello world"

    def test_list_content_with_text(self):
        msg = AIMessage(content=[
            {"type": "thinking", "thinking": "reasoning"},
            {"type": "text", "text": "the answer"},
        ])
        assert _extract_reply(msg) == "the answer"

    def test_list_content_multiple_text_blocks(self):
        msg = AIMessage(content=[
            {"type": "text", "text": "part1"},
            {"type": "text", "text": "part2"},
        ])
        assert _extract_reply(msg) == "part1\npart2"

    def test_empty_content(self):
        msg = AIMessage(content="")
        assert _extract_reply(msg) == ""


class TestGetCurrentTokenUsage:
    def test_no_data(self):
        result = get_current_token_usage()
        # May or may not have data depending on prior tests; just verify it doesn't crash
        assert isinstance(result, dict)


class TestProcessMessage:
    """Integration tests for _process_message with mocked LLM."""

    @pytest.mark.asyncio
    async def test_simple_response(self, tmp_path, monkeypatch):
        """LLM returns a text response with no tool calls."""
        # Redirect sessions
        monkeypatch.setattr("sbot.session.SESSIONS_DIR", tmp_path)

        bus = MessageBus()
        captured = []
        bus.register_channel("test", lambda msg: captured.append(msg))

        # Mock LLM — returns simple response
        response = AIMessage(content="Hello! I'm sbot.")
        response.response_metadata = {"usage": {"input_tokens": 500, "output_tokens": 20}}
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=response)

        msg = InboundMessage(channel="test", chat_id="1", text="hi")

        from sbot.agent import _process_message
        with patch("sbot.agent.SYSTEM_PROMPT", "You are sbot."):
            with patch("sbot.agent.get_skills_prompt", return_value=""):
                await _process_message(mock_llm, bus, msg)

        # Should have emitted: thinking + thinking(content) + thinking(tokens) + response
        response_msgs = [m for m in captured if m.message_type == MsgType.RESPONSE]
        assert len(response_msgs) == 1
        assert "Hello! I'm sbot." in response_msgs[0].text

    @pytest.mark.asyncio
    async def test_tool_call_loop(self, tmp_path, monkeypatch):
        """LLM makes a tool call, then responds."""
        monkeypatch.setattr("sbot.session.SESSIONS_DIR", tmp_path)

        bus = MessageBus()
        captured = []
        bus.register_channel("test", lambda msg: captured.append(msg))

        # First response: tool call
        tool_response = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_1",
                "name": "list_dir",
                "args": {"path": "."},
            }],
        )
        tool_response.response_metadata = {"usage": {"input_tokens": 500, "output_tokens": 20}}

        # Second response: final answer
        final_response = AIMessage(content="Here are the files.")
        final_response.response_metadata = {"usage": {"input_tokens": 800, "output_tokens": 30}}

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_response, final_response])

        msg = InboundMessage(channel="test", chat_id="1", text="list files")

        from sbot.agent import _process_message
        with patch("sbot.agent.SYSTEM_PROMPT", "You are sbot."):
            with patch("sbot.agent.get_skills_prompt", return_value=""):
                await _process_message(mock_llm, bus, msg)

        # Should have tool_call and tool_result messages
        tool_call_msgs = [m for m in captured if m.message_type == MsgType.TOOL_CALL]
        tool_result_msgs = [m for m in captured if m.message_type == MsgType.TOOL_RESULT]
        response_msgs = [m for m in captured if m.message_type == MsgType.RESPONSE]

        assert len(tool_call_msgs) >= 1
        assert len(tool_result_msgs) >= 1
        assert len(response_msgs) == 1
        assert "Here are the files" in response_msgs[0].text

    @pytest.mark.asyncio
    async def test_unknown_tool(self, tmp_path, monkeypatch):
        """LLM calls a tool that doesn't exist."""
        monkeypatch.setattr("sbot.session.SESSIONS_DIR", tmp_path)

        bus = MessageBus()
        captured = []
        bus.register_channel("test", lambda msg: captured.append(msg))

        tool_response = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "nonexistent_tool", "args": {}}],
        )
        tool_response.response_metadata = {"usage": {"input_tokens": 500, "output_tokens": 20}}

        final_response = AIMessage(content="Sorry, tool not found.")
        final_response.response_metadata = {"usage": {"input_tokens": 800, "output_tokens": 30}}

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_response, final_response])

        msg = InboundMessage(channel="test", chat_id="1", text="do something")

        from sbot.agent import _process_message
        with patch("sbot.agent.SYSTEM_PROMPT", "You are sbot."):
            with patch("sbot.agent.get_skills_prompt", return_value=""):
                await _process_message(mock_llm, bus, msg)

        tool_results = [m for m in captured if m.message_type == MsgType.TOOL_RESULT]
        assert any("Unknown tool" in m.text for m in tool_results)

    @pytest.mark.asyncio
    async def test_skills_injected_in_system_prompt(self, tmp_path, monkeypatch):
        """Verify skills metadata is injected into system prompt."""
        monkeypatch.setattr("sbot.session.SESSIONS_DIR", tmp_path)

        bus = MessageBus()
        bus.register_channel("test", lambda msg: None)

        response = AIMessage(content="ok")
        response.response_metadata = {"usage": {"input_tokens": 500, "output_tokens": 10}}
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=response)

        msg = InboundMessage(channel="test", chat_id="1", text="hi")

        from sbot.agent import _process_message
        with patch("sbot.agent.SYSTEM_PROMPT", "Base prompt"):
            with patch("sbot.agent.get_skills_prompt", return_value="## Available Skills\n- test-skill: does stuff"):
                await _process_message(mock_llm, bus, msg)

        # Check what was passed to LLM
        call_args = mock_llm.ainvoke.call_args[0][0]
        system_msg = call_args[0]
        assert isinstance(system_msg, SystemMessage)
        assert "Available Skills" in system_msg.content
        assert "test-skill" in system_msg.content

    @pytest.mark.asyncio
    async def test_uses_stored_api_tokens_on_second_turn(self, tmp_path, monkeypatch):
        """On second turn, compaction check uses last API token count, not tiktoken re-estimate."""
        monkeypatch.setattr("sbot.session.SESSIONS_DIR", tmp_path)
        # Clear any stale state
        _session_token_usage.clear()

        bus = MessageBus()
        bus.register_channel("test", lambda msg: None)

        response = AIMessage(content="ok")
        response.response_metadata = {"usage": {"input_tokens": 50000, "output_tokens": 10}}
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=response)

        with patch("sbot.agent.SYSTEM_PROMPT", "s"):
            with patch("sbot.agent.get_skills_prompt", return_value=""):
                # First turn — establishes API token count (50000) in _session_token_usage
                msg1 = InboundMessage(channel="test", chat_id="x", text="hello")
                await _process_message(mock_llm, bus, msg1)

        # After first turn, stored count is 50000
        assert _session_token_usage.get("test_x", {}).get("input_tokens") == 50000

        # Second turn: patch estimate_tokens to assert it is NOT called for the full history
        # (if it were called and returned a huge number, compaction would fire wrongly)
        with patch("sbot.agent.estimate_tokens") as mock_estimate:
            mock_estimate.return_value = 999_999  # would trigger compaction if called on full history
            with patch("sbot.agent.SYSTEM_PROMPT", "s"):
                with patch("sbot.agent.get_skills_prompt", return_value=""):
                    msg2 = InboundMessage(channel="test", chat_id="x", text="second")
                    await _process_message(mock_llm, bus, msg2)

        # estimate_tokens must NOT have been called on the full history
        # (it may be called with just the new user message for the delta, so check call count vs content)
        for call in mock_estimate.call_args_list:
            msgs_arg = call[0][0]
            # If called, must be with a short list (1-2 msgs), not the full history
            assert len(msgs_arg) <= 2, f"estimate_tokens called on full history ({len(msgs_arg)} msgs)"
