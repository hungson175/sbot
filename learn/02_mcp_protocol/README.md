# Module 2: Understanding MCP by Building It

Learn the Model Context Protocol by implementing a simplified version from scratch.

## What is MCP?

MCP (Model Context Protocol) is like **LSP (Language Server Protocol) but for AI**. Just as LSP lets any editor talk to any language server, MCP lets any AI host talk to any tool/data server using one standard protocol.

**The problem it solves:** Without MCP, every AI app needs custom integration code for every tool. With MCP, you write one server and it works with Claude Desktop, VS Code, your own agent — anything that speaks MCP.

## Lessons (~1.5-2 hours)

| # | Notebook | What You Build | Time |
|---|----------|---------------|------|
| 01 | `01_json_rpc_basics.ipynb` | JSON-RPC 2.0 message parser + dispatcher | 20 min |
| 02 | `02_stdio_transport.ipynb` | Stdin/stdout transport layer (read/write JSON lines) | 15 min |
| 03 | `03_mcp_server.ipynb` | Minimal MCP server with tools (handshake + tools/list + tools/call) | 30 min |
| 04 | `04_mcp_client.ipynb` | MCP client that launches server as subprocess and calls tools | 25 min |
| 05 | `05_real_mcp_sdk.ipynb` | Use the official `mcp` Python SDK (FastMCP) — see how your DIY version maps | 15 min |

## Prerequisites

- Completed Module 1 (async/await basics)
- Python 3.11+

## Architecture Overview

```
┌──────────────┐         stdio          ┌──────────────┐
│  MCP Client  │ ───── stdin/stdout ──── │  MCP Server  │
│  (your agent)│                         │  (tools/data)│
└──────────────┘                         └──────────────┘

Messages: JSON-RPC 2.0, one JSON object per line
Lifecycle: initialize → initialized → tools/list → tools/call → ...
```

## What You'll Understand After This Module

1. JSON-RPC 2.0 — the message format under MCP
2. How client and server handshake (capability negotiation)
3. How tools are discovered and called
4. Why stdio transport works (newline-delimited JSON over stdin/stdout)
5. How the official SDK abstracts all of this
6. How sbot Layer 9 will use MCP to connect to external tool servers
