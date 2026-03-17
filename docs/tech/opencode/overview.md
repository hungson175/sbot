# OpenCode: Architecture Overview

Reference: `sample_code/opencode/`

## What is OpenCode?

Open-source AI coding agent — similar to Claude Code but provider-agnostic. Built with TypeScript + Bun, features a TUI (terminal UI) and client/server architecture.

## Tech Stack

- **Runtime**: Bun 1.3.10
- **AI SDK**: `ai` v5.0 — unified LLM interface for 13+ providers
- **Schemas**: Zod everywhere (events, configs, tool inputs)
- **DB**: SQLite via Drizzle ORM
- **UI**: Solid.js (TUI + web dashboard)
- **Server**: Hono
- **Code parsing**: Tree-sitter

## Package Structure (21 packages)

| Package | Purpose |
|---------|---------|
| `opencode` | Main CLI + agent loop |
| `sdk` | Client/server communication |
| `plugin` | Plugin system for extending tools |
| `console` | TUI interface |
| `app` | Web dashboard |
| `identity` | Auth |
| `containers` | Containerization |
| `extensions` | Third-party extensions |
| `slack` | Slack integration |

## Agent Architecture

Multiple built-in agents with role-based permissions:

| Agent | Type | Capabilities |
|-------|------|-------------|
| `build` | primary | Full access, asks for dangerous ops |
| `plan` | primary | Read-only analysis mode |
| `general` | subagent | Multi-step research, parallel tasks |
| `explore` | subagent | Read-only file search/grep |

Permissions are ruleset-based (allow/deny/ask per tool), configurable per agent.

## Key Design Patterns

1. **Provider abstraction** — `ai` SDK abstracts 13+ providers, swappable without code changes
2. **Instance-scoped state** — `Instance.state()` for project-isolated data
3. **Namespace pattern** — `MCP.tools()`, `Command.list()`, `Skill.all()`
4. **Text-based tool descriptions** — `.txt` files separate from implementation (same as sbot)
5. **Permission-first** — deny-by-default for dangerous operations

## Detailed Docs

- [MCP Server](mcp-server.md) — MCP client implementation, tool discovery
- [Skills & Commands](skills-commands.md) — Skill format, commands, tool registry
