"""Configuration and environment loading."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
API_BASE = "https://api.minimax.io/anthropic"
MODEL = "MiniMax-M2.5-highspeed"

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_BASE_PROMPT = (_PROMPTS_DIR / "system.txt").read_text().strip()

# Bootstrap files — loaded from workspace and appended to the base prompt
_BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]


def load_system_prompt() -> str:
    parts = [_BASE_PROMPT]
    for name in _BOOTSTRAP_FILES:
        p = Path(name)
        if p.exists():
            content = p.read_text().strip()
            if content:
                parts.append(f"## {name}\n\n{content}")
    return "\n\n---\n\n".join(parts)


SYSTEM_PROMPT = load_system_prompt()
