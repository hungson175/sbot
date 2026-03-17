"""Tests for sbot.tools — all tool functions.

Coverage target: 80%+ (service layer)
LLM/API calls: mocked (Exa API)
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sbot.tools import (
    context_status,
    edit_file,
    exec_cmd,
    list_dir,
    plan,
    read_file,
    search_files,
    skill,
    write_file,
)


class TestReadFile:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = read_file.invoke({"path": str(f)})
        assert "1| line1" in result
        assert "2| line2" in result
        assert "3| line3" in result

    def test_file_not_found(self):
        result = read_file.invoke({"path": "/nonexistent/file.txt"})
        assert "Error: file not found" in result

    def test_not_a_file(self, tmp_path):
        result = read_file.invoke({"path": str(tmp_path)})
        assert "Error: not a file" in result

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = read_file.invoke({"path": str(f)})
        assert "empty file" in result

    def test_offset_and_limit(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line{i}" for i in range(100)))
        result = read_file.invoke({"path": str(f), "offset": 10, "limit": 5})
        assert "10| line9" in result
        assert "14| line13" in result
        assert "Use offset=" in result

    def test_offset_beyond_end(self, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("one line")
        result = read_file.invoke({"path": str(f), "offset": 999})
        assert "Error: offset 999 is beyond end" in result


class TestListDir:
    def test_list_dir(self, tmp_path):
        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()
        result = list_dir.invoke({"path": str(tmp_path)})
        assert "subdir/" in result
        assert "file.txt" in result

    def test_nonexistent(self):
        result = list_dir.invoke({"path": "/nonexistent/dir"})
        assert "Error: path not found" in result

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        result = list_dir.invoke({"path": str(d)})
        assert result == "(empty)"


class TestWriteFile:
    def test_write_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = write_file.invoke({"path": str(f), "content": "hello world"})
        assert "Wrote" in result
        assert f.read_text() == "hello world"

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        write_file.invoke({"path": str(f), "content": "deep"})
        assert f.read_text() == "deep"


class TestEditFile:
    def test_replace_once(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world")
        result = edit_file.invoke({"path": str(f), "old_text": "world", "new_text": "earth"})
        assert "Replaced 1" in result
        assert f.read_text() == "hello earth"

    def test_not_found(self):
        result = edit_file.invoke({"path": "/nonexistent", "old_text": "a", "new_text": "b"})
        assert "Error: file not found" in result

    def test_old_text_not_found(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello")
        result = edit_file.invoke({"path": str(f), "old_text": "xyz", "new_text": "abc"})
        assert "Error: old_text not found" in result

    def test_ambiguous_match(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("aa aa aa")
        result = edit_file.invoke({"path": str(f), "old_text": "aa", "new_text": "bb"})
        assert "found 3 occurrences" in result

    def test_replace_all(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("aa bb aa")
        result = edit_file.invoke({
            "path": str(f), "old_text": "aa", "new_text": "cc", "replace_all": True,
        })
        assert "Replaced 2" in result
        assert f.read_text() == "cc bb cc"


class TestExecCmd:
    def test_simple_command(self):
        result = exec_cmd.invoke({"command": "echo hello"})
        assert "hello" in result

    def test_background(self):
        result = exec_cmd.invoke({"command": "sleep 0.01", "background": True})
        assert "Started in background" in result
        assert "PID" in result

    def test_timeout(self):
        result = exec_cmd.invoke({"command": "sleep 10", "timeout": 1})
        assert "timed out" in result

    def test_exit_code(self):
        result = exec_cmd.invoke({"command": "false"})
        assert "exit code" in result or result.strip() == ""


class TestSearchFiles:
    def test_search_pattern(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\n")
        result = search_files.invoke({"pattern": "def hello", "path": str(tmp_path)})
        assert "def hello" in result

    def test_no_matches(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("nothing here")
        result = search_files.invoke({"pattern": "zzzzzzz", "path": str(tmp_path)})
        assert "No matches" in result


class TestPlan:
    def test_plan_display(self):
        todo = [
            {"description": "Step 1", "state": "done"},
            {"description": "Step 2", "state": "in_progress"},
            {"description": "Step 3", "state": "pending"},
        ]
        result = plan.invoke({"todo_list": todo})
        assert "1/3 done" in result
        assert "1 in progress" in result
        assert "1 pending" in result
        assert "✓" in result
        assert "▶" in result
        assert "⬚" in result


class TestContextStatus:
    def test_no_data(self):
        with patch("sbot.agent.get_current_token_usage", return_value={}):
            result = context_status.invoke({})
        assert "No token data" in result

    def test_with_data(self):
        usage = {"input_tokens": 50000, "context_window": 200000}
        with patch("sbot.agent.get_current_token_usage", return_value=usage):
            result = context_status.invoke({})
        assert "50.0k" in result
        assert "200.0k" in result


class TestSkillTool:
    def test_list_skills(self):
        from sbot.skills import SkillInfo
        mock_skills = [
            SkillInfo(name="s1", description="Skill one", path=Path("."), skill_md_path=Path(".")),
        ]
        with patch("sbot.tools.get_skills", return_value=mock_skills):
            result = skill.invoke({"name": ""})
        assert "Available skills (1)" in result
        assert "s1" in result

    def test_no_skills(self):
        with patch("sbot.tools.get_skills", return_value=[]):
            result = skill.invoke({"name": ""})
        assert "No skills found" in result

    def test_load_specific_skill(self):
        from sbot.skills import SkillInfo
        mock_skill = SkillInfo(
            name="test", description="Test", path=Path("."), skill_md_path=Path("."),
        )
        with patch("sbot.tools.get_skill_by_name", return_value=mock_skill):
            with patch("sbot.tools.load_skill_content", return_value="# Skill content"):
                result = skill.invoke({"name": "test"})
        assert "# Skill content" in result

    def test_skill_not_found(self):
        with patch("sbot.tools.get_skill_by_name", return_value=None):
            result = skill.invoke({"name": "nonexistent"})
        assert "not found" in result


class TestWebSearch:
    def test_no_api_key(self):
        from sbot.tools import web_search
        with patch("sbot.tools._get_exa", return_value=None):
            result = web_search.invoke({"query": "test"})
        assert "EXA_API_KEY not set" in result

    def test_search_success(self):
        from sbot.tools import web_search
        mock_result = MagicMock()
        mock_result.title = "Test Result"
        mock_result.url = "https://example.com"
        mock_result.highlights = ["highlight text"]

        mock_exa = MagicMock()
        mock_exa.search_and_contents.return_value = MagicMock(results=[mock_result])

        with patch("sbot.tools._get_exa", return_value=mock_exa):
            result = web_search.invoke({"query": "test"})
        assert "Test Result" in result
        assert "https://example.com" in result

    def test_search_error(self):
        from sbot.tools import web_search
        mock_exa = MagicMock()
        mock_exa.search_and_contents.side_effect = Exception("API error")

        with patch("sbot.tools._get_exa", return_value=mock_exa):
            result = web_search.invoke({"query": "test"})
        assert "Error: web search failed" in result


class TestWebFetch:
    def test_no_api_key(self):
        from sbot.tools import web_fetch
        with patch("sbot.tools._get_exa", return_value=None):
            result = web_fetch.invoke({"url": "https://example.com"})
        assert "EXA_API_KEY not set" in result

    def test_fetch_success(self):
        from sbot.tools import web_fetch
        mock_result = MagicMock()
        mock_result.title = "Page Title"
        mock_result.text = "Page content here"

        mock_exa = MagicMock()
        mock_exa.get_contents.return_value = MagicMock(results=[mock_result])

        with patch("sbot.tools._get_exa", return_value=mock_exa):
            result = web_fetch.invoke({"url": "https://example.com"})
        assert "Page Title" in result
        assert "Page content here" in result

    def test_fetch_error(self):
        from sbot.tools import web_fetch
        mock_exa = MagicMock()
        mock_exa.get_contents.side_effect = Exception("Network error")

        with patch("sbot.tools._get_exa", return_value=mock_exa):
            result = web_fetch.invoke({"url": "https://example.com"})
        assert "Error: web fetch failed" in result
