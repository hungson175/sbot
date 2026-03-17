"""Shared fixtures for sbot tests."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sbot.bus import InboundMessage, MessageBus, MsgType, OutboundMessage
from sbot.compact import CompactSummary, CompactTurn


@pytest.fixture
def tmp_sessions(tmp_path, monkeypatch):
    """Redirect sessions directory to a temp path."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr("sbot.session.SESSIONS_DIR", sessions_dir)
    return sessions_dir


@pytest.fixture
def bus():
    """Fresh MessageBus instance."""
    return MessageBus()


@pytest.fixture
def captured_messages(bus):
    """Register a handler that captures all outbound messages."""
    messages = []
    bus.register_channel("test", lambda msg: messages.append(msg))
    return messages


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a simple AIMessage with no tool calls."""
    from langchain_core.messages import AIMessage

    llm = AsyncMock()
    response = AIMessage(content="Mock response")
    response.response_metadata = {
        "usage": {"input_tokens": 1000, "output_tokens": 50}
    }
    llm.ainvoke = AsyncMock(return_value=response)
    llm.with_structured_output = MagicMock(return_value=llm)
    return llm


@pytest.fixture
def sample_compact_summary():
    """Sample CompactSummary for testing rebuild_history."""
    return CompactSummary(
        session_summary="User asked about Python. Bot helped with code.",
        turns=[
            CompactTurn(user_query="How do I read a file?", bot_response="Use open()"),
        ],
        files_touched=["main.py", "config.py"],
        plan_state=None,
        memory_update="User prefers concise answers.",
        history_entry="[2026-03-16] User asked about file I/O.",
    )


@pytest.fixture
def skill_dirs(tmp_path):
    """Create temp skill directories with test skills."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Skill with valid frontmatter
    s1 = skills_dir / "test-skill"
    s1.mkdir()
    (s1 / "SKILL.md").write_text(
        '---\nname: test-skill\ndescription: A test skill for unit testing\n---\n\n# Test Skill\n\nDo test things.'
    )

    # Skill with resources
    s2 = skills_dir / "rich-skill"
    s2.mkdir()
    (s2 / "SKILL.md").write_text(
        '---\nname: rich-skill\ndescription: Skill with bundled resources\n---\n\n# Rich Skill\n\nHas resources.'
    )
    refs = s2 / "references"
    refs.mkdir()
    (refs / "guide.md").write_text("# Guide")
    (refs / "api.md").write_text("# API")

    # Skill missing description (should be skipped)
    s3 = skills_dir / "no-desc"
    s3.mkdir()
    (s3 / "SKILL.md").write_text("---\nname: no-desc\n---\n\nNo description.")

    # Not a skill (no SKILL.md)
    s4 = skills_dir / "not-a-skill"
    s4.mkdir()
    (s4 / "README.md").write_text("Not a skill")

    return skills_dir
