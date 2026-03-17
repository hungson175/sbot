# OpenCode: Skills & Commands System

Reference: `sample_code/opencode/packages/opencode/src/skill/` and `src/command/`

## Overview

OpenCode has two complementary systems:
- **Skills** — markdown files that teach the agent how to use external tools/CLIs
- **Commands** — user-invocable slash commands (built-in, config, MCP prompts, or skills)

## Skills System

### Skill Format (SKILL.md)

```markdown
---
name: my-skill
description: Clear description of what this skill does
---

# Skill Content
Full instructions, workflows, references...
```

Skills are **not executable tools** — they're context documents injected into the prompt so the model knows how to use external CLIs via `exec_cmd`.

### Skill Discovery (Priority Order)

1. Global: `~/.claude/skills/` or `~/.agents/skills/` (lowest precedence)
2. Project: `.claude/skills/` or `.agents/skills/` (searches up dir tree)
3. Config dirs: `.opencode/skill/` or `.opencode/skills/`
4. Config paths: `skills.paths` array
5. Remote URLs: `skills.urls` — downloads `index.json` + files (highest precedence)

Higher precedence overrides lower when names conflict.

### Remote Skill Loading

```json
// index.json format
{
  "skills": [
    {
      "name": "skill-name",
      "description": "...",
      "files": ["SKILL.md", "reference.md", "script.sh"]
    }
  ]
}
```

Skills downloaded from URLs are cached in `~/.opencode/cache/skills/`.

### Skill Tool

Skills are exposed to the agent via a `skill` tool:
- Lists available skills in the tool description
- Agent invokes by name → full skill content loaded into context
- Includes up to 10 bundled resource files

### Size Limits

| Limit | Default |
|-------|---------|
| Max candidates per root | 300 |
| Max skills per source | 200 |
| Max skills in prompt | 150 |
| Max skill file bytes | 256KB |

If total skill text exceeds char budget, binary search finds the largest prefix that fits.

## Commands System

### Command Sources (merged into single namespace)

1. **Built-in**: `init` (create AGENTS.md), `review` (commit/PR review)
2. **Config commands**: markdown templates in config
3. **MCP prompts**: auto-wrapped as commands (prompt name → command name)
4. **Skills**: skills exposed as invokable commands

### Command Format (Markdown)

```markdown
---
description: Short description
agent: build          # optional: which agent runs this
model: opencode/model # optional: model override
subtask: true         # optional: nested execution
---

# Instructions with $1, $2 placeholders
Do something with $ARGUMENTS...
```

### Template Variables

- `$1`, `$2`, `$3` — positional arguments
- `$ARGUMENTS` — all arguments as a string
- MCP prompt arguments auto-mapped to `$1, $2, ...`

### Command Info Schema

```typescript
{
  name: string
  description?: string
  source: "command" | "mcp" | "skill"
  template: Promise<string> | string
  subtask?: boolean
  hints: string[]      // Template variables
  agent?: string
  model?: string
}
```

## Tool Management

### Tool Registry

Built-in tools + custom tools + plugin tools + MCP tools — all merged into one registry.

```
ToolRegistry.tools(model, agent)
  ├── Built-in (bash, read, write, edit, grep, glob, skill, task, ...)
  ├── Custom (.opencode/tool/*.ts via ESM import)
  ├── Plugin (installed packages)
  └── MCP (from connected servers)
```

### Custom Tool Format (Plugin)

```typescript
// .opencode/tool/my-tool.ts
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "What this tool does",
  args: {
    param1: tool.schema.string().describe("..."),
    param2: tool.schema.number().optional(),
  },
  async execute(args, ctx) {
    return "output text"
  },
})
```

### Model-Aware Filtering

Some tools are conditional on model/provider:
- `websearch`/`codesearch`: only with OpenCode provider or `OPENCODE_ENABLE_EXA`
- `apply_patch`: only for GPT models
- `edit`/`write`: all other models

## Key Design Patterns

1. **Skills ≠ Tools**: Skills are documentation (context), tools are executable functions
2. **Multi-source discovery**: Skills loaded from many directories with precedence
3. **Lazy loading**: Skills discovered async, tool descriptions loaded on demand
4. **Template commands**: Markdown with variable substitution, reusable
5. **Event bus**: `Command.Event.Executed` for tracking

## Relevance to sbot

### What to adopt for sbot:

**Skills (Layer 10):**
- SKILL.md format: markdown frontmatter + body (sbot already uses `.txt` for tool descriptions — extend this pattern)
- Multi-source discovery: project `skills/` + user `~/.sbot/skills/`
- A `skill` tool that lists available skills and loads them into context on demand
- Size limits to prevent prompt bloat

**Commands (Layer 10):**
- Slash commands as markdown templates with `$ARGUMENTS` substitution
- Commands directory: `.sbot/commands/` or `sbot/commands/`
- Built-in commands: `/compact` (force compact), `/status` (context status), `/plan` (show plan)

### What to simplify:
- Skip remote skill URLs (unnecessary complexity for now)
- Skip MCP prompt → command auto-wrapping (wait until MCP is solid)
- Skip model-aware tool filtering (sbot uses one model)
- Skip plugin system (custom tools via config is enough)
