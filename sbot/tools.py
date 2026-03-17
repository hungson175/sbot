"""Tool definitions using LangChain @tool decorator."""

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from .skills import get_skill_by_name, get_skills, load_skill_content


_PROMPTS_DIR = Path(__file__).parent / "prompts" / "tools"
_MAX_CHARS = 128_000
_DEFAULT_LIMIT = 2000


def _load_description(name: str) -> str:
    """Load tool description from prompts/tools/<name>.txt."""
    return (_PROMPTS_DIR / f"{name}.txt").read_text().strip()


@tool(description=_load_description("read_file"))
def read_file(path: str, offset: int = 1, limit: int = _DEFAULT_LIMIT) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: file not found: {p}"
    if not p.is_file():
        return f"Error: not a file: {p}"

    all_lines = p.read_text(errors="replace").splitlines()
    total = len(all_lines)
    if total == 0:
        return f"(empty file: {p})"

    offset = max(1, offset)
    if offset > total:
        return f"Error: offset {offset} is beyond end of file ({total} lines)"

    start = offset - 1
    end = min(start + limit, total)
    numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
    result = "\n".join(numbered)

    # Trim if too large
    if len(result) > _MAX_CHARS:
        trimmed, chars = [], 0
        for line in numbered:
            chars += len(line) + 1
            if chars > _MAX_CHARS:
                break
            trimmed.append(line)
        end = start + len(trimmed)
        result = "\n".join(trimmed)

    if end < total:
        result += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
    else:
        result += f"\n\n(End of file — {total} lines total)"
    return result


@tool(description=_load_description("list_dir"))
def list_dir(path: str = ".") -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: path not found: {p}"
    entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    return "\n".join(f"{e.name}{'/' if e.is_dir() else ''}" for e in entries) or "(empty)"


@tool(description=_load_description("write_file"))
def write_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content.encode('utf-8'))} bytes to {p}"


@tool(description=_load_description("edit_file"))
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: file not found: {p}"
    content = p.read_text(encoding="utf-8")
    count = content.count(old_text)
    if count == 0:
        return f"Error: old_text not found in {p}"
    if count > 1 and not replace_all:
        return f"Error: found {count} occurrences. Provide more context to match uniquely, or set replace_all=true."
    if replace_all:
        new_content = content.replace(old_text, new_text)
    else:
        new_content = content.replace(old_text, new_text, 1)
    p.write_text(new_content, encoding="utf-8")
    replaced = count if replace_all else 1
    return f"Replaced {replaced} occurrence(s) in {p}"


@tool(description=_load_description("exec_cmd"))
def exec_cmd(command: str, background: bool = False, timeout: int = 120) -> str:
    if background:
        proc = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Started in background (PID {proc.pid})"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    if len(output) > 16000:
        output = output[:16000] + "\n...(truncated)"
    return output or f"(exit code {result.returncode})"


@tool(description=_load_description("search_files"))
def search_files(pattern: str, path: str = ".", include: str = "", max_results: int = 50) -> str:
    cmd = ["rg", "-n", "--glob", include, pattern, path] if include else ["rg", "-n", pattern, path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout
    except subprocess.TimeoutExpired:
        return "Error: search timed out after 30s"
    if not output:
        return f"No matches found for '{pattern}' in {path}"
    lines = output.splitlines()
    total = len(lines)
    truncated = lines[:max_results]
    result_text = "\n".join(truncated)
    if total > max_results:
        result_text += f"\n\n({total} total matches, showing first {max_results})"
    return result_text



@tool(description=_load_description("context_status"))
def context_status() -> str:
    from .agent import get_current_token_usage
    from .compact import format_token_usage
    usage = get_current_token_usage()
    if not usage or not usage.get("input_tokens"):
        return "No token data yet — usage is tracked after the first API response."
    in_tokens = usage["input_tokens"]
    max_tokens = usage["context_window"]
    remaining_k = round((max_tokens - in_tokens) / 1000, 1)
    return f"Context: {format_token_usage(in_tokens, max_tokens)} — {remaining_k}k remaining"


_exa_client = None


def _get_exa():
    """Lazy singleton Exa client — reuses HTTP connection pool across calls."""
    global _exa_client
    if _exa_client is None:
        from .config import EXA_API_KEY
        if not EXA_API_KEY:
            return None
        from exa_py import Exa
        _exa_client = Exa(api_key=EXA_API_KEY)
    return _exa_client


@tool(description=_load_description("web_search"))
def web_search(query: str, num_results: int = 5, category: str = "") -> str:
    exa = _get_exa()
    if not exa:
        return "Error: EXA_API_KEY not set. Add it to .env"
    kwargs = {
        "query": query,
        "type": "auto",
        "num_results": min(num_results, 20),
        "highlights": {"max_characters": 4000},
    }
    if category:
        kwargs["category"] = category
    try:
        results = exa.search_and_contents(**kwargs)
    except Exception as e:
        return f"Error: web search failed: {e}"
    lines = []
    for r in results.results:
        lines.append(f"### {r.title}")
        lines.append(f"URL: {r.url}")
        if hasattr(r, "highlights") and r.highlights:
            for h in r.highlights[:3]:
                lines.append(f"> {h[:500]}")
        lines.append("")
    return "\n".join(lines) if lines else f"No results found for '{query}'"


@tool(description=_load_description("web_fetch"))
def web_fetch(url: str, max_characters: int = 10000) -> str:
    exa = _get_exa()
    if not exa:
        return "Error: EXA_API_KEY not set. Add it to .env"
    try:
        results = exa.get_contents(
            urls=[url],
            text={"max_characters": min(max_characters, 50000)},
        )
    except Exception as e:
        return f"Error: web fetch failed: {e}"
    if not results.results:
        return f"Error: could not fetch content from {url}"
    r = results.results[0]
    title = f"# {r.title}\n\n" if hasattr(r, "title") and r.title else ""
    text = r.text if hasattr(r, "text") and r.text else "(no content)"
    return f"{title}{text}"


@tool(description=_load_description("plan"))
def plan(todo_list: list[dict]) -> str:
    _STATE_ICONS = {"pending": "⬚", "in_progress": "▶", "done": "✓"}
    lines = []
    counts = {"pending": 0, "in_progress": 0, "done": 0}
    for task in todo_list:
        state = task.get("state", "pending")
        desc = task.get("description", "")
        counts[state] = counts.get(state, 0) + 1
        icon = _STATE_ICONS.get(state, "?")
        lines.append(f"  {icon} [{state}] {desc}")
    total = len(todo_list)
    summary = f"Plan: {counts['done']}/{total} done, {counts['in_progress']} in progress, {counts['pending']} pending"
    return summary + "\n" + "\n".join(lines)


@tool(description=_load_description("skill"))
def skill(name: str = "") -> str:
    if not name:
        skills = get_skills()
        if not skills:
            return "No skills found."
        lines = [f"Available skills ({len(skills)}):"]
        for s in skills:
            lines.append(f"  - {s.name}: {s.description[:150]}")
        return "\n".join(lines)

    found = get_skill_by_name(name)
    if not found:
        return f"Skill '{name}' not found. Call skill() with no args to list available skills."
    return load_skill_content(found)


TOOLS = [read_file, list_dir, write_file, edit_file, search_files, exec_cmd, plan, context_status, web_search, web_fetch, skill]
TOOL_MAP = {t.name: t for t in TOOLS}
