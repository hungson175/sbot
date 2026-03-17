"""Integration test fixtures — real code, recorded HTTP responses.

Uses VCR (pytest-recording) to record/replay LLM API calls.
First run with --record-mode=once hits the real API and saves cassettes.
Subsequent runs replay from cassettes — zero cost, deterministic.

Usage:
    # First time: record real responses (needs ANTHROPIC_AUTH_TOKEN)
    pytest tests/integration/ --record-mode=once

    # After recording: replay from cassettes (no API key needed)
    pytest tests/integration/

    # Re-record all cassettes (e.g. after changing prompts)
    pytest tests/integration/ --record-mode=all
"""

import asyncio
from pathlib import Path

import pytest

from sbot.bus import MessageBus, MsgType, OutboundMessage


@pytest.fixture
def integration_bus():
    """MessageBus with a capturing handler on a 'test' channel."""
    bus = MessageBus()
    captured = []
    bus.register_channel("test", lambda msg: captured.append(msg))
    return bus, captured


@pytest.fixture
def integration_sessions(tmp_path, monkeypatch):
    """Redirect session storage to tmp dir."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr("sbot.session.SESSIONS_DIR", sessions_dir)
    return sessions_dir


@pytest.fixture
def real_llm():
    """Build real LLM (ChatAnthropic bound with tools).
    VCR intercepts the HTTP calls — no actual API cost during replay."""
    from sbot.app import _build_llm
    return _build_llm()


def extract_responses(captured: list[OutboundMessage]) -> dict:
    """Helper: extract typed messages from captured bus output."""
    return {
        "thinking": [m for m in captured if m.message_type == MsgType.THINKING],
        "tool_calls": [m for m in captured if m.message_type == MsgType.TOOL_CALL],
        "tool_results": [m for m in captured if m.message_type == MsgType.TOOL_RESULT],
        "responses": [m for m in captured if m.message_type == MsgType.RESPONSE],
        "errors": [m for m in captured if m.message_type == MsgType.ERROR],
    }
