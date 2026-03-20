"""Tests for sbot.session — JSONL persistence + truncation boundary fix.

Coverage target: 85%+ (core)
"""

import json

import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from sbot.session import (
    MAX_HISTORY_MESSAGES,
    _dict_to_msg,
    _msg_to_dict,
    load_last_token_usage,
    load_session,
    save_compact_event,
    save_full_session,
    save_messages,
)


class TestMsgToDict:
    def test_human(self):
        d = _msg_to_dict(HumanMessage(content="hello"))
        assert d == {"type": "human", "content": "hello"}

    def test_ai_no_tools(self):
        d = _msg_to_dict(AIMessage(content="reply"))
        assert d == {"type": "ai", "content": "reply"}
        assert "tool_calls" not in d

    def test_ai_with_tools(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "x"}}],
        )
        d = _msg_to_dict(msg)
        assert d["tool_calls"] == msg.tool_calls

    def test_tool_message(self):
        d = _msg_to_dict(ToolMessage(content="result", tool_call_id="call_1"))
        assert d == {"type": "tool", "content": "result", "tool_call_id": "call_1"}

    def test_system_message_returns_none(self):
        from langchain_core.messages import SystemMessage
        assert _msg_to_dict(SystemMessage(content="sys")) is None


class TestDictToMsg:
    def test_human(self):
        msg = _dict_to_msg({"type": "human", "content": "hi"})
        assert isinstance(msg, HumanMessage)
        assert msg.content == "hi"

    def test_ai(self):
        msg = _dict_to_msg({"type": "ai", "content": "reply", "tool_calls": []})
        assert isinstance(msg, AIMessage)

    def test_ai_with_tool_calls(self):
        tc = [{"id": "c1", "name": "read_file", "args": {"path": "x"}}]
        msg = _dict_to_msg({"type": "ai", "content": "", "tool_calls": tc})
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "read_file"
        assert msg.tool_calls[0]["args"] == {"path": "x"}

    def test_tool(self):
        msg = _dict_to_msg({"type": "tool", "content": "out", "tool_call_id": "c1"})
        assert isinstance(msg, ToolMessage)
        assert msg.tool_call_id == "c1"

    def test_metadata_line_returns_none(self):
        assert _dict_to_msg({"_type": "compact", "summary": "..."}) is None

    def test_unknown_type_returns_none(self):
        assert _dict_to_msg({"type": "unknown", "content": "x"}) is None


class TestSaveMessages:
    def test_save_and_load(self, tmp_sessions):
        msgs = [
            HumanMessage(content="hello"),
            AIMessage(content="world"),
        ]
        save_messages("test_session", msgs)

        loaded, last_consolidated = load_session("test_session")
        assert len(loaded) == 2
        assert isinstance(loaded[0], HumanMessage)
        assert loaded[0].content == "hello"
        assert isinstance(loaded[1], AIMessage)
        assert loaded[1].content == "world"
        assert last_consolidated == 0

    def test_save_empty_list(self, tmp_sessions):
        save_messages("test_session", [])
        loaded, _ = load_session("test_session")
        assert loaded == []

    def test_append_multiple_batches(self, tmp_sessions):
        save_messages("test_session", [HumanMessage(content="a")])
        save_messages("test_session", [AIMessage(content="b")])
        loaded, _ = load_session("test_session")
        assert len(loaded) == 2


class TestSaveCompactEvent:
    def test_compact_event_skipped_on_load(self, tmp_sessions):
        save_messages("test_session", [HumanMessage(content="before")])
        save_compact_event("test_session", 1, "summary of conversation")
        save_messages("test_session", [HumanMessage(content="after")])

        loaded, last_consolidated = load_session("test_session")
        # Only actual messages loaded, compact event skipped
        assert len(loaded) == 2
        assert loaded[0].content == "before"
        assert loaded[1].content == "after"
        assert last_consolidated == 1


class TestLoadSession:
    def test_nonexistent_session(self, tmp_sessions):
        loaded, lc = load_session("nonexistent")
        assert loaded == []
        assert lc == 0

    def test_truncation_respects_message_boundary(self, tmp_sessions):
        """When truncation cuts into a tool call sequence, it walks forward
        to the first HumanMessage to avoid orphaned ToolMessages."""
        # Build a history that exceeds MAX_HISTORY_MESSAGES
        msgs = []
        # Start with an AI+Tool pair (these should get cut)
        msgs.append(AIMessage(
            content="",
            tool_calls=[{"id": "call_old", "name": "read_file", "args": {"path": "x"}}],
        ))
        msgs.append(ToolMessage(content="old result", tool_call_id="call_old"))

        # Fill with enough human/ai pairs to exceed limit
        for i in range(MAX_HISTORY_MESSAGES):
            msgs.append(HumanMessage(content=f"msg_{i}"))
            msgs.append(AIMessage(content=f"reply_{i}"))

        save_messages("test_session", msgs)
        loaded, _ = load_session("test_session")

        # First message should be a HumanMessage (not the orphaned ToolMessage)
        assert isinstance(loaded[0], HumanMessage)

    def test_empty_lines_skipped(self, tmp_sessions):
        path = tmp_sessions / "test_session.jsonl"
        path.write_text(
            '{"type":"human","content":"hello"}\n\n{"type":"ai","content":"world"}\n'
        )
        loaded, _ = load_session("test_session")
        assert len(loaded) == 2

    def test_malformed_json_skipped(self, tmp_sessions):
        path = tmp_sessions / "test_session.jsonl"
        path.write_text(
            '{"type":"human","content":"hello"}\nnot json\n{"type":"ai","content":"world"}\n'
        )
        loaded, _ = load_session("test_session")
        assert len(loaded) == 2


class TestSaveFullSession:
    def test_creates_file(self, tmp_sessions):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        save_full_session("s1", msgs)
        assert (tmp_sessions / "s1.jsonl").exists()

    def test_loadable(self, tmp_sessions):
        msgs = [
            HumanMessage(content="q"),
            AIMessage(content="a"),
            ToolMessage(content="result", tool_call_id="c1"),
        ]
        save_full_session("s1", msgs)
        loaded, _ = load_session("s1")
        assert len(loaded) == 3
        assert loaded[0].content == "q"
        assert loaded[1].content == "a"
        assert loaded[2].content == "result"

    def test_overwrites_existing(self, tmp_sessions):
        """save_full_session replaces prior content — pruning becomes permanent."""
        save_messages("s1", [HumanMessage(content="old1"), HumanMessage(content="old2")])
        save_full_session("s1", [HumanMessage(content="pruned")])
        loaded, _ = load_session("s1")
        assert len(loaded) == 1
        assert loaded[0].content == "pruned"

    def test_empty_list_clears_file(self, tmp_sessions):
        save_messages("s1", [HumanMessage(content="old")])
        save_full_session("s1", [])
        loaded, _ = load_session("s1")
        assert loaded == []

    def test_persists_token_usage(self, tmp_sessions):
        save_full_session("s1", [HumanMessage(content="hi")], token_usage=12345)
        assert load_last_token_usage("s1") == 12345

    def test_zero_token_usage_not_persisted(self, tmp_sessions):
        save_full_session("s1", [HumanMessage(content="hi")], token_usage=0)
        assert load_last_token_usage("s1") == 0


class TestLoadLastTokenUsage:
    def test_returns_zero_for_nonexistent(self, tmp_sessions):
        assert load_last_token_usage("no_session") == 0

    def test_returns_zero_when_no_usage_record(self, tmp_sessions):
        save_messages("s1", [HumanMessage(content="hi")])
        assert load_last_token_usage("s1") == 0

    def test_returns_latest_usage(self, tmp_sessions):
        save_full_session("s1", [HumanMessage(content="hi")], token_usage=999)
        assert load_last_token_usage("s1") == 999

    def test_returns_last_usage_when_multiple(self, tmp_sessions):
        """Only the last usage record matters."""
        save_full_session("s1", [HumanMessage(content="hi")], token_usage=100)
        save_full_session("s1", [HumanMessage(content="hi"), AIMessage(content="yo")], token_usage=200)
        assert load_last_token_usage("s1") == 200
