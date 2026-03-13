"""
sbot — Layer 1: bare-bones agent loop in a single file.

Run:
    ANTHROPIC_AUTH_TOKEN=sk-... python3 sbot.py "What's 2+2?"
    ANTHROPIC_AUTH_TOKEN=sk-... python3 sbot.py   # interactive mode
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

# ── Config ──────────────────────────────────────────────────────────────────

API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
API_BASE = "https://api.minimax.io/anthropic"
MODEL = "MiniMax-M2.5-highspeed"
MAX_TOOL_ITERATIONS = 20

SYSTEM_PROMPT = """You are sbot, a helpful AI assistant with tool-calling capabilities.
Use tools when needed. Be concise and direct."""

# ── Tools ───────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file and return its contents with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and directories at a given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path", "default": "."},
            },
        },
    },
    {
        "name": "exec",
        "description": "Execute a shell command and return stdout+stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
]


async def run_tool(name: str, args: dict) -> str:
    """Execute a tool by name and return its result as a string."""
    if name == "read_file":
        p = Path(args["path"]).expanduser()
        if not p.exists():
            return f"Error: file not found: {p}"
        lines = p.read_text(errors="replace").splitlines()
        numbered = [f"{i+1}\t{line}" for i, line in enumerate(lines[:2000])]
        return "\n".join(numbered) or "(empty file)"

    elif name == "list_dir":
        p = Path(args.get("path", ".")).expanduser()
        if not p.exists():
            return f"Error: path not found: {p}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        return "\n".join(f"{e.name}{'/' if e.is_dir() else ''}" for e in entries) or "(empty)"

    elif name == "exec":
        proc = await asyncio.create_subprocess_shell(
            args["command"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = stdout.decode(errors="replace")
        if len(output) > 16000:
            output = output[:16000] + "\n...(truncated)"
        return output or f"(exit code {proc.returncode})"

    return f"Unknown tool: {name}"


# ── Agent Loop ──────────────────────────────────────────────────────────────

async def agent_turn(llm, history: list, user_text: str) -> str:
    """Process one user message through the agent loop. Returns assistant reply."""
    history.append(HumanMessage(content=user_text))

    for _ in range(MAX_TOOL_ITERATIONS):
        response: AIMessage = await llm.ainvoke(history)
        history.append(response)

        # No tool calls → we're done
        if not response.tool_calls:
            # Extract text from content (may be str or list of blocks)
            if isinstance(response.content, str):
                return response.content
            return "\n".join(
                b["text"] for b in response.content
                if isinstance(b, dict) and b.get("type") == "text"
            )

        # Execute tool calls, append results
        for tc in response.tool_calls:
            print(f"  [tool] {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)[:80]})")
            result = await run_tool(tc["name"], tc["args"])
            history.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    return "(max tool iterations reached)"


# ── Main ────────────────────────────────────────────────────────────────────

async def main():
    if not API_KEY:
        print("Set ANTHROPIC_AUTH_TOKEN env var")
        sys.exit(1)

    llm = ChatAnthropic(
        model=MODEL,
        api_key=API_KEY,
        base_url=API_BASE,
        max_tokens=4096,
    )
    llm = llm.bind_tools(TOOLS)

    history = [SystemMessage(content=SYSTEM_PROMPT)]

    # Single message mode
    if len(sys.argv) > 1:
        reply = await agent_turn(llm, history, " ".join(sys.argv[1:]))
        print(reply)
        return

    # Interactive mode
    print("sbot — interactive mode (Ctrl+C to exit)\n")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input:
            continue
        reply = await agent_turn(llm, history, user_input)
        print(f"\nsbot> {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
