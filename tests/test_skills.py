"""Tests for sbot.skills — discovery, frontmatter parsing, content loading.

Coverage target: 80%+ (service layer)
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from sbot.skills import (
    SkillInfo,
    _format_skills_for_prompt,
    _parse_frontmatter,
    _strip_frontmatter,
    discover_skills,
    load_skill_content,
)


class TestParseFrontmatter:
    def test_basic(self):
        text = '---\nname: my-skill\ndescription: Does things\n---\nBody here'
        fm = _parse_frontmatter(text)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "Does things"

    def test_no_frontmatter(self):
        assert _parse_frontmatter("No frontmatter here") == {}

    def test_unclosed_frontmatter(self):
        assert _parse_frontmatter("---\nname: broken\n") == {}

    def test_quoted_values(self):
        text = '---\nname: "quoted-name"\ndescription: \'single quoted\'\n---\n'
        fm = _parse_frontmatter(text)
        assert fm["name"] == "quoted-name"
        assert fm["description"] == "single quoted"

    def test_extra_fields(self):
        text = '---\nname: test\ndescription: desc\nallowed-tools: Bash(*)\n---\n'
        fm = _parse_frontmatter(text)
        assert fm["allowed-tools"] == "Bash(*)"

    def test_multiline_pipe(self):
        text = '---\nname: test\ndescription: |\n  line1\n  line2\n---\n'
        fm = _parse_frontmatter(text)
        assert "line1" in fm["description"]
        assert "line2" in fm["description"]


class TestStripFrontmatter:
    def test_with_frontmatter(self):
        text = '---\nname: test\n---\n\nBody content'
        assert _strip_frontmatter(text) == "Body content"

    def test_without_frontmatter(self):
        text = "Just body text"
        assert _strip_frontmatter(text) == "Just body text"

    def test_unclosed(self):
        text = "---\nname: broken\nstill going"
        assert _strip_frontmatter(text) == text


class TestDiscoverSkills:
    def test_discovers_valid_skills(self, skill_dirs):
        with patch("sbot.skills._SKILL_DIRS", [skill_dirs]):
            # Reset cache
            import sbot.skills
            sbot.skills._skills_cache = None
            sbot.skills._skills_by_name = {}
            sbot.skills._skills_prompt = ""

            skills = discover_skills()

        names = {s.name for s in skills}
        assert "test-skill" in names
        assert "rich-skill" in names
        # no-desc should be skipped (missing description)
        assert "no-desc" not in names
        # not-a-skill should be skipped (no SKILL.md)
        assert "not-a-skill" not in names

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty_skills"
        empty.mkdir()
        with patch("sbot.skills._SKILL_DIRS", [empty]):
            skills = discover_skills()
        assert skills == []

    def test_nonexistent_dir(self):
        with patch("sbot.skills._SKILL_DIRS", [Path("/nonexistent/path")]):
            skills = discover_skills()
        assert skills == []

    def test_later_path_wins_on_name_conflict(self, tmp_path):
        dir1 = tmp_path / "global"
        dir1.mkdir()
        s1 = dir1 / "my-skill"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\nname: my-skill\ndescription: Global version\n---\nGlobal")

        dir2 = tmp_path / "project"
        dir2.mkdir()
        s2 = dir2 / "my-skill"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("---\nname: my-skill\ndescription: Project version\n---\nProject")

        with patch("sbot.skills._SKILL_DIRS", [dir1, dir2]):
            skills = discover_skills()

        assert len(skills) == 1
        assert skills[0].description == "Project version"


class TestLoadSkillContent:
    def test_loads_body(self, skill_dirs):
        skill = SkillInfo(
            name="test-skill",
            description="A test skill",
            path=skill_dirs / "test-skill",
            skill_md_path=skill_dirs / "test-skill" / "SKILL.md",
        )
        content = load_skill_content(skill)
        assert "# Skill: test-skill" in content
        assert "# Test Skill" in content
        assert "Do test things." in content
        # Frontmatter should be stripped
        assert "---" not in content.split("# Skill:")[1].split("\n\n")[0]

    def test_lists_resources(self, skill_dirs):
        skill = SkillInfo(
            name="rich-skill",
            description="Has resources",
            path=skill_dirs / "rich-skill",
            skill_md_path=skill_dirs / "rich-skill" / "SKILL.md",
        )
        content = load_skill_content(skill)
        assert "## Bundled Resources" in content
        assert "guide.md" in content
        assert "api.md" in content
        assert "read_file" in content

    def test_no_resources_section_when_empty(self, skill_dirs):
        skill = SkillInfo(
            name="test-skill",
            description="A test skill",
            path=skill_dirs / "test-skill",
            skill_md_path=skill_dirs / "test-skill" / "SKILL.md",
        )
        content = load_skill_content(skill)
        assert "## Bundled Resources" not in content


class TestFormatSkillsForPrompt:
    def test_empty(self):
        assert _format_skills_for_prompt([]) == ""

    def test_formats_skills(self):
        skills = [
            SkillInfo(name="a", description="Skill A desc", path=Path("."), skill_md_path=Path(".")),
            SkillInfo(name="b", description="Skill B desc", path=Path("."), skill_md_path=Path(".")),
        ]
        result = _format_skills_for_prompt(skills)
        assert "## Available Skills" in result
        assert "**a**" in result
        assert "**b**" in result
        assert "Skill A desc" in result

    def test_truncates_long_descriptions(self):
        long_desc = "x" * 300
        skills = [
            SkillInfo(name="long", description=long_desc, path=Path("."), skill_md_path=Path(".")),
        ]
        result = _format_skills_for_prompt(skills)
        assert "..." in result
        assert len(long_desc) > 200  # confirm it was actually long
