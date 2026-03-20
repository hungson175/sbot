"""Tests for sbot.compact — token estimation, pruning, rebuild, memory store.

Coverage target: 85%+ (core)
LLM calls: mocked
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from sbot.compact import (
    CONTEXT_WINDOW,
    CompactSummary,
    CompactTurn,
    MemoryStore,
    _find_turn_boundaries,
    count_recent_messages,
    estimate_tokens,
    format_token_usage,
    prune_tool_outputs,
    raw_archive,
    rebuild_history,
)


class TestEstimateTokens:
    def test_simple_messages(self):
        msgs = [
            SystemMessage(content="system"),
            HumanMessage(content="hello"),
            AIMessage(content="world"),
        ]
        tokens = estimate_tokens(msgs, include_tools=False)
        assert tokens > 0

    def test_with_tool_calls(self):
        msgs = [
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "x"}}],
            ),
            ToolMessage(content="file content", tool_call_id="c1"),
        ]
        tokens = estimate_tokens(msgs, include_tools=False)
        assert tokens > 0

    def test_with_list_content(self):
        msgs = [
            AIMessage(content=[
                {"type": "text", "text": "hello"},
                {"type": "thinking", "thinking": "reasoning..."},
            ]),
        ]
        tokens = estimate_tokens(msgs, include_tools=False)
        assert tokens > 0

    def test_includes_tools_by_default(self):
        msgs = [HumanMessage(content="hi")]
        with_tools = estimate_tokens(msgs, include_tools=True)
        without_tools = estimate_tokens(msgs, include_tools=False)
        assert with_tools > without_tools

    def test_tool_use_block_not_double_counted(self):
        """tool_use content blocks must NOT be counted — args are already in tool_calls."""
        large_args = {"content": "x" * 1000}
        # With tool_use block in content (how MiniMax/Anthropic returns it)
        msgs_with_block = [
            AIMessage(
                content=[
                    {"type": "text", "text": "writing file"},
                    {"type": "tool_use", "id": "c1", "name": "write_file", "input": large_args},
                ],
                tool_calls=[{"id": "c1", "name": "write_file", "args": large_args, "type": "tool_call"}],
            ),
        ]
        # Without tool_use block (same data, just missing the redundant block)
        msgs_without_block = [
            AIMessage(
                content=[{"type": "text", "text": "writing file"}],
                tool_calls=[{"id": "c1", "name": "write_file", "args": large_args, "type": "tool_call"}],
            ),
        ]
        tokens_with = estimate_tokens(msgs_with_block, include_tools=False)
        tokens_without = estimate_tokens(msgs_without_block, include_tools=False)
        # Must be identical — tool_use block adds nothing
        assert tokens_with == tokens_without


class TestFindTurnBoundaries:
    def test_basic(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        boundaries = _find_turn_boundaries(msgs)
        assert boundaries == [1, 3]

    def test_no_human_messages(self):
        msgs = [SystemMessage(content="sys"), AIMessage(content="a")]
        assert _find_turn_boundaries(msgs) == []


class TestCountRecentMessages:
    def test_keep_1_turn(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        count = count_recent_messages(msgs, 1)
        assert count == 2  # q2 + a2

    def test_keep_all(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
        ]
        count = count_recent_messages(msgs, 5)
        assert count == 2  # all except system


class TestPruneToolOutputs:
    def test_prunes_old_tool_messages(self):
        msgs = [
            SystemMessage(content="sys"),
            # Turn 1 (old — will be pruned)
            HumanMessage(content="q1"),
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "x"}}],
            ),
            ToolMessage(content="x" * 500, tool_call_id="c1"),
            AIMessage(content="result1"),
            # Turn 2 (old — will be pruned)
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            # Turn 3 (old — will be pruned)
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
            # Turn 4 (old — will be pruned)
            HumanMessage(content="q4"),
            AIMessage(content="a4"),
            # Turns 5-7 (recent — protected, keep_recent=3)
            HumanMessage(content="q5"),
            AIMessage(content="a5"),
            HumanMessage(content="q6"),
            AIMessage(content="a6"),
            HumanMessage(content="q7"),
            AIMessage(content="a7"),
        ]
        pruned, freed = prune_tool_outputs(msgs)
        assert freed > 0
        # The old ToolMessage should be replaced with [pruned: N chars]
        tool_msgs = [m for m in pruned if isinstance(m, ToolMessage)]
        old_tool = [m for m in tool_msgs if "pruned" in m.content]
        assert len(old_tool) == 1

    def test_nothing_to_prune(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
        ]
        pruned, freed = prune_tool_outputs(msgs)
        assert freed == 0
        assert pruned == msgs

    def test_preserves_short_tool_content(self):
        msgs = [
            SystemMessage(content="sys"),
            # Turn 1 (old)
            HumanMessage(content="q1"),
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "x", "args": {}}],
            ),
            ToolMessage(content="short", tool_call_id="c1"),
            AIMessage(content="r1"),
            # Turns 2-4 (recent, protected)
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
            HumanMessage(content="q4"),
            AIMessage(content="a4"),
        ]
        pruned, freed = prune_tool_outputs(msgs)
        assert freed == 0  # "short" is under 100 chars


class TestRebuildHistory:
    def test_basic_rebuild(self, sample_compact_summary):
        history = rebuild_history(sample_compact_summary, [], "System prompt here")
        assert isinstance(history[0], SystemMessage)
        assert history[0].content == "System prompt here"
        assert isinstance(history[1], HumanMessage)
        assert "Session Summary" in history[1].content
        assert isinstance(history[2], AIMessage)
        assert "context from our previous conversation" in history[2].content

    def test_with_recent_messages(self, sample_compact_summary):
        recent = [HumanMessage(content="new q"), AIMessage(content="new a")]
        history = rebuild_history(sample_compact_summary, recent, "sys")
        # sys + summary HumanMsg + summary AIMsg + 2 recent = 5
        assert len(history) == 5
        assert history[-1].content == "new a"

    def test_includes_turns(self, sample_compact_summary):
        history = rebuild_history(sample_compact_summary, [], "sys")
        summary_text = history[1].content
        assert "How do I read a file?" in summary_text
        assert "Use open()" in summary_text

    def test_includes_files_touched(self, sample_compact_summary):
        history = rebuild_history(sample_compact_summary, [], "sys")
        summary_text = history[1].content
        assert "main.py" in summary_text
        assert "config.py" in summary_text

    def test_includes_plan_state(self):
        summary = CompactSummary(
            session_summary="test",
            plan_state=[{"description": "task1", "state": "done"}],
        )
        history = rebuild_history(summary, [], "sys")
        assert "Plan state" in history[1].content


class TestMemoryStore:
    def test_read_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sbot.compact.Path", lambda *a: tmp_path)
        store = MemoryStore("test_session")
        # Override dir to use tmp_path
        store.dir = tmp_path
        store._memory_path = tmp_path / "MEMORY.md"
        store._history_path = tmp_path / "HISTORY.md"
        assert store.read_memory() == ""

    def test_write_and_read(self, tmp_path):
        store = MemoryStore("test")
        store.dir = tmp_path
        store._memory_path = tmp_path / "MEMORY.md"
        store._history_path = tmp_path / "HISTORY.md"

        store.write_memory("User likes Python")
        assert store.read_memory() == "User likes Python"

    def test_append_history(self, tmp_path):
        store = MemoryStore("test")
        store.dir = tmp_path
        store._memory_path = tmp_path / "MEMORY.md"
        store._history_path = tmp_path / "HISTORY.md"

        store.append_history("Entry 1")
        store.append_history("Entry 2")

        content = store._history_path.read_text()
        assert "Entry 1" in content
        assert "Entry 2" in content
        assert "---" in content

    def test_write_empty_memory_skipped(self, tmp_path):
        store = MemoryStore("test")
        store.dir = tmp_path
        store._memory_path = tmp_path / "MEMORY.md"
        store._history_path = tmp_path / "HISTORY.md"

        store.write_memory("   ")
        assert not store._memory_path.exists()

    def test_append_empty_history_skipped(self, tmp_path):
        store = MemoryStore("test")
        store.dir = tmp_path
        store._memory_path = tmp_path / "MEMORY.md"
        store._history_path = tmp_path / "HISTORY.md"

        store.append_history("   ")
        assert not store._history_path.exists()


class TestRawArchive:
    def test_formats_messages(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="hello"),
            AIMessage(content="world"),
        ]
        result = raw_archive(msgs)
        assert "[Human] hello" in result
        assert "[AI] world" in result
        assert "[System]" not in result  # SystemMessage skipped

    def test_truncates_long_content(self):
        msgs = [HumanMessage(content="x" * 1000)]
        result = raw_archive(msgs)
        assert len(result) < 1000


class TestFormatTokenUsage:
    def test_basic(self):
        result = format_token_usage(50000, 200000)
        assert "50.0k" in result
        assert "200.0k" in result
        assert "25.0%" in result

    def test_default_context_window(self):
        result = format_token_usage(100000)
        assert f"{CONTEXT_WINDOW // 1000}.0k" in result


class TestCompactWithLlm:
    @pytest.mark.asyncio
    async def test_structured_output_success(self):
        from sbot.compact import compact_with_llm

        expected = CompactSummary(
            session_summary="Test summary",
            memory_update="user likes tests",
            history_entry="did testing",
        )
        mock_llm = AsyncMock()
        structured_llm = AsyncMock()
        structured_llm.ainvoke = AsyncMock(return_value=expected)
        mock_llm.with_structured_output = MagicMock(return_value=structured_llm)

        result = await compact_with_llm(mock_llm, [HumanMessage(content="test")])
        assert result.session_summary == "Test summary"

    @pytest.mark.asyncio
    async def test_fallback_to_json_parse(self):
        from sbot.compact import compact_with_llm

        mock_llm = MagicMock()
        # Structured output returns an LLM whose ainvoke raises (simulates provider not supporting it)
        structured_llm = AsyncMock()
        structured_llm.ainvoke = AsyncMock(side_effect=NotImplementedError("not supported"))
        mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
        # Regular invoke returns JSON
        json_response = json.dumps({
            "session_summary": "Fallback summary",
            "turns": [],
            "files_touched": [],
            "memory_update": "",
            "history_entry": "fallback",
        })
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(content=f"```json\n{json_response}\n```")
        )

        result = await compact_with_llm(mock_llm, [HumanMessage(content="test")])
        assert result.session_summary == "Fallback summary"

    @pytest.mark.asyncio
    async def test_fallback_to_minimal_summary(self):
        from sbot.compact import compact_with_llm

        mock_llm = MagicMock()
        structured_llm = AsyncMock()
        structured_llm.ainvoke = AsyncMock(side_effect=NotImplementedError("nope"))
        mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="This is not valid JSON at all")
        )

        result = await compact_with_llm(mock_llm, [HumanMessage(content="test")])
        assert "This is not valid JSON" in result.session_summary
