"""Skill discovery, frontmatter parsing, and content loading."""

from dataclasses import dataclass
from pathlib import Path

# Discovery paths (later paths win on name conflict)
_SKILL_DIRS = [
    Path.home() / ".claude" / "skills",   # user global (Claude Code compat)
    Path.cwd() / ".claude" / "skills",     # project-level
]



@dataclass
class SkillInfo:
    name: str
    description: str
    path: Path             # path to skill directory
    skill_md_path: Path    # path to SKILL.md


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Parse YAML frontmatter between --- markers. Simple key: value only."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    result: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in block.split("\n"):
        if ":" in line and not line[0] in (" ", "\t"):
            if current_key:
                result[current_key] = "\n".join(current_lines).strip().strip('"').strip("'")
            key, _, val = line.partition(":")
            current_key = key.strip()
            val = val.strip()
            current_lines = [] if val in ("|", ">", "") else [val.strip('"').strip("'")]
        elif current_key:
            current_lines.append(line)
    if current_key:
        result[current_key] = "\n".join(current_lines).strip().strip('"').strip("'")
    return result


def _strip_frontmatter(text: str) -> str:
    """Return text body after frontmatter (everything after second ---)."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].strip()
    return text


def discover_skills() -> list[SkillInfo]:
    """Find all skills from discovery paths. Later paths win on name conflict."""
    seen: dict[str, SkillInfo] = {}
    for skill_dir in _SKILL_DIRS:
        if not skill_dir.is_dir():
            continue
        for entry in sorted(skill_dir.iterdir()):
            skill_md = entry / "SKILL.md"
            if not entry.is_dir() or not skill_md.exists():
                continue
            fm = _parse_frontmatter(skill_md.read_text(errors="replace"))
            name = fm.get("name", entry.name)
            desc = fm.get("description", "")
            if name and desc:
                seen[name] = SkillInfo(
                    name=name, description=desc,
                    path=entry, skill_md_path=skill_md,
                )
    return list(seen.values())


def load_skill_content(skill: SkillInfo) -> str:
    """Load full SKILL.md body (everything after frontmatter).
    Also lists available reference files so the agent knows they exist."""
    text = _strip_frontmatter(skill.skill_md_path.read_text(errors="replace"))

    # Append list of available resources
    resources = []
    for subdir in ("references", "reference", "scripts", "assets"):
        d = skill.path / subdir
        if d.is_dir():
            files = sorted(
                f.name for f in d.iterdir()
                if f.is_file() and f.name != "__pycache__"
            )
            if files:
                resources.append(f"  {subdir}/: {', '.join(files)}")
    if resources:
        text += "\n\n## Bundled Resources\n" + "\n".join(resources)
        text += f"\n\nUse read_file to load any resource from: {skill.path}"

    return f"# Skill: {skill.name}\n\n{text}"


# Module-level cache (discovered once, reused)
_skills_cache: list[SkillInfo] | None = None
_skills_by_name: dict[str, SkillInfo] = {}
_skills_prompt: str = ""


def get_skills() -> list[SkillInfo]:
    global _skills_cache, _skills_by_name, _skills_prompt
    if _skills_cache is None:
        _skills_cache = discover_skills()
        _skills_by_name = {s.name: s for s in _skills_cache}
        _skills_prompt = _format_skills_for_prompt(_skills_cache)
    return _skills_cache


def get_skill_by_name(name: str) -> SkillInfo | None:
    get_skills()  # ensure cache populated
    return _skills_by_name.get(name)


def get_skills_prompt() -> str:
    """Get cached formatted skills text for system prompt injection."""
    get_skills()  # ensure cache populated
    return _skills_prompt


def _format_skills_for_prompt(skills: list[SkillInfo]) -> str:
    """Format skill metadata for system prompt injection."""
    if not skills:
        return ""
    lines = [
        "## Available Skills",
        "",
        "Use the `skill` tool to load a skill's full instructions when needed.",
        "",
    ]
    for s in skills:
        lines.append(f"- **{s.name}**: {s.description}")
    return "\n".join(lines)
