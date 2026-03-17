"""Integration tests for agent message flow.

Tests the FULL pipeline: message → agent → LLM → tools → session → response.
Real code everywhere, only HTTP calls are recorded/replayed via VCR cassettes.

Recording cassettes (first time, needs ANTHROPIC_AUTH_TOKEN):
    pytest tests/integration/test_agent_flow.py --record-mode=once -v

Replaying (no API key needed):
    pytest tests/integration/test_agent_flow.py -v
"""

import pytest

from sbot.agent import _process_message
from sbot.bus import InboundMessage, MsgType
from sbot.session import load_session

from .conftest import extract_responses


@pytest.mark.vcr()
class TestSimpleConversation:
    """Agent receives a simple question, responds without tools."""

    @pytest.mark.asyncio
    async def test_greeting(self, real_llm, integration_bus, integration_sessions):
        bus, captured = integration_bus
        msg = InboundMessage(channel="test", chat_id="integ_1", text="Hi, what are you?")

        await _process_message(real_llm, bus, msg)

        result = extract_responses(captured)
        assert len(result["responses"]) == 1
        assert len(result["errors"]) == 0
        # Agent should identify itself
        response_text = result["responses"][0].text.lower()
        assert "sbot" in response_text or "assistant" in response_text

    @pytest.mark.asyncio
    async def test_session_persisted(self, real_llm, integration_bus, integration_sessions):
        bus, captured = integration_bus
        msg = InboundMessage(channel="test", chat_id="integ_2", text="Say hello")

        await _process_message(real_llm, bus, msg)

        # Session should be saved
        messages, _ = load_session("test_integ_2")
        assert len(messages) >= 2  # at least HumanMessage + AIMessage


@pytest.mark.vcr()
class TestToolUsage:
    """Agent uses tools to answer questions."""

    @pytest.mark.asyncio
    async def test_list_dir_tool(self, real_llm, integration_bus, integration_sessions):
        """Ask agent to list files — should use list_dir tool."""
        bus, captured = integration_bus
        msg = InboundMessage(
            channel="test", chat_id="integ_3",
            text="List the files in the current directory using list_dir tool",
        )

        await _process_message(real_llm, bus, msg)

        result = extract_responses(captured)
        assert len(result["responses"]) == 1
        assert len(result["errors"]) == 0
        # Should have made at least one tool call
        assert len(result["tool_calls"]) >= 1
        # Should have used list_dir
        tool_names = [m.text for m in result["tool_calls"]]
        assert any("list_dir" in t for t in tool_names)

    @pytest.mark.asyncio
    async def test_read_file_tool(self, real_llm, integration_bus, integration_sessions):
        """Ask agent to read a specific file — should use read_file tool."""
        bus, captured = integration_bus
        msg = InboundMessage(
            channel="test", chat_id="integ_4",
            text="Read the file pyproject.toml using read_file tool and tell me the project name",
        )

        await _process_message(real_llm, bus, msg)

        result = extract_responses(captured)
        assert len(result["responses"]) == 1
        assert len(result["errors"]) == 0
        assert len(result["tool_calls"]) >= 1
        # Response should mention the project name
        assert "sbot" in result["responses"][0].text.lower()


@pytest.mark.vcr()
class TestSkillTool:
    """Agent can list and load skills."""

    @pytest.mark.asyncio
    async def test_list_skills(self, real_llm, integration_bus, integration_sessions):
        """Ask what skills are available — agent should call skill() or answer from system prompt."""
        bus, captured = integration_bus
        msg = InboundMessage(
            channel="test", chat_id="integ_5",
            text="What skills do you have? Use the skill tool to list them.",
        )

        await _process_message(real_llm, bus, msg)

        result = extract_responses(captured)
        assert len(result["responses"]) == 1
        assert len(result["errors"]) == 0


@pytest.mark.vcr()
class TestMultiTurnConversation:
    """Agent maintains context across multiple messages in the same session."""

    @pytest.mark.asyncio
    async def test_remembers_context(self, real_llm, integration_bus, integration_sessions):
        """Send two messages — second should reference context from first."""
        bus, captured = integration_bus

        # First message
        msg1 = InboundMessage(channel="test", chat_id="integ_6", text="My name is TestUser")
        await _process_message(real_llm, bus, msg1)

        # Clear captured for clean second check
        captured.clear()

        # Second message — should remember the name
        msg2 = InboundMessage(channel="test", chat_id="integ_6", text="What is my name?")
        await _process_message(real_llm, bus, msg2)

        result = extract_responses(captured)
        assert len(result["responses"]) == 1
        assert "testuser" in result["responses"][0].text.lower()


@pytest.mark.vcr()
class TestErrorHandling:
    """Agent handles edge cases gracefully."""

    @pytest.mark.asyncio
    async def test_empty_message(self, real_llm, integration_bus, integration_sessions):
        """Empty message shouldn't crash the agent."""
        bus, captured = integration_bus
        msg = InboundMessage(channel="test", chat_id="integ_7", text="")

        await _process_message(real_llm, bus, msg)

        result = extract_responses(captured)
        # Should get a response or error, but not crash
        assert len(result["responses"]) + len(result["errors"]) >= 1
