"""Session persistence — save/load conversation history as JSONL."""

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

SESSIONS_DIR = Path("sessions")
MAX_HISTORY_MESSAGES = 0  # 0 = no cap; compaction manages context size

# Ensure sessions dir exists once at import time
SESSIONS_DIR.mkdir(exist_ok=True)


def _msg_to_dict(msg) -> dict | None:
    """Serialize a LangChain message to a JSON-safe dict. Skip SystemMessage."""
    if isinstance(msg, HumanMessage):
        return {"type": "human", "content": msg.content}
    if isinstance(msg, AIMessage):
        d = {"type": "ai", "content": msg.content}
        if msg.tool_calls:
            d["tool_calls"] = msg.tool_calls
        return d
    if isinstance(msg, ToolMessage):
        return {"type": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id}
    return None


def _dict_to_msg(d: dict):
    """Deserialize a dict back to a LangChain message.
    Returns None for metadata/compact lines (have _type field)."""
    if "_type" in d:
        return None
    t = d.get("type")
    if t == "human":
        return HumanMessage(content=d["content"])
    if t == "ai":
        return AIMessage(content=d["content"], tool_calls=d.get("tool_calls", []))
    if t == "tool":
        return ToolMessage(content=d["content"], tool_call_id=d["tool_call_id"])
    return None


def save_messages(session_name: str, msgs: list):
    """Append multiple messages in one file operation."""
    lines = []
    for msg in msgs:
        d = _msg_to_dict(msg)
        if d is not None:
            lines.append(json.dumps(d, ensure_ascii=False))
    if not lines:
        return
    path = SESSIONS_DIR / f"{session_name}.jsonl"
    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")


def save_compact_event(session_name: str, last_consolidated: int, summary_text: str):
    """Append a compact event line to the session JSONL."""
    path = SESSIONS_DIR / f"{session_name}.jsonl"
    event = {
        "_type": "compact",
        "last_consolidated": last_consolidated,
        "summary": summary_text[:500],
    }
    with open(path, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_session(session_name: str, max_messages: int = MAX_HISTORY_MESSAGES) -> tuple[list, int]:
    """Load recent messages from a session JSONL file.

    Returns (messages, last_consolidated). Caps at max_messages.
    Skips metadata/compact lines (they have _type field).
    """
    path = SESSIONS_DIR / f"{session_name}.jsonl"
    if not path.exists():
        return [], 0
    messages = []
    last_consolidated = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("_type") in ("compact", "metadata"):
            last_consolidated = d.get("last_consolidated", last_consolidated)
            continue
        msg = _dict_to_msg(d)
        if msg:
            messages.append(msg)
    if max_messages and len(messages) > max_messages:
        messages = messages[-max_messages:]
        # Never start on a ToolMessage — its parent AIMessage (with tool_calls) may be cut.
        # Walk forward to the first HumanMessage for a clean boundary.
        start = 0
        for i, m in enumerate(messages):
            if isinstance(m, HumanMessage):
                start = i
                break
        if start > 0:
            messages = messages[start:]
    return messages, last_consolidated
