# OpenClaw: Skills System & Tool Management

Reference: `sample_code/openclaw/src/agents/skills/` and `src/plugins/tools.ts`

## Key Finding: No Dynamic Tool Search

OpenClaw does **NOT** have a "tool search tool" where agents discover tools at runtime. Instead:
- All tools are bound upfront when the API request is made
- Skills are pre-compiled into the system prompt via `formatSkillsForPrompt()`
- Eligibility filtering happens at startup, not during conversation

The "tool search" pattern (as seen in Claude Code's `ToolSearch`) is **not present** in OpenClaw.

## Skills System

### What Skills Are

Skills in OpenClaw are **context documents** — markdown files that teach the agent how to use external CLIs. They are NOT executable tools themselves.

Flow: Skill defines how to use CLI → skill text injected into prompt → agent uses `exec` tool to run CLI commands.

### SKILL.md Format

```markdown
---
name: nano-pdf
description: Edit PDFs with natural-language instructions using the nano-pdf CLI.
homepage: https://pypi.org/project/nano-pdf/
metadata:
  {
    "openclaw": {
      "emoji": "📄",
      "requires": { "bins": ["nano-pdf"] },
      "install": [
        {
          "id": "uv",
          "kind": "uv",
          "package": "nano-pdf",
          "bins": ["nano-pdf"],
          "label": "Install nano-pdf (uv)"
        }
      ]
    }
  }
---

# nano-pdf

Use `nano-pdf` to apply edits to PDF files...
```

### Metadata Fields

| Field | Purpose |
|-------|---------|
| `name` | Skill identifier |
| `description` | User/model-facing description |
| `metadata.openclaw.emoji` | Visual indicator |
| `metadata.openclaw.requires.bins` | Required binaries for eligibility |
| `metadata.openclaw.install` | Installation specs (brew/npm/go/uv/download) |
| `metadata.openclaw.primaryEnv` | Primary environment variable |
| `metadata.openclaw.os` | Supported OSes (darwin/linux/win32) |

### Skill Loading Pipeline

1. **Discover** from multiple sources (precedence order):
   - Extra dirs (lowest)
   - Bundled skills (OpenClaw defaults)
   - Managed skills (`~/.openclaw/skills/`)
   - Personal agent skills (`~/.agents/skills/`)
   - Project agent skills (`./.agents/skills/`)
   - Workspace skills (`./skills/`)
   - Highest precedence wins on name conflicts

2. **Filter by eligibility**:
   ```typescript
   type SkillEligibilityContext = {
     remote?: {
       platforms: string[];
       hasBin: (bin: string) => boolean;
       hasAnyBin: (bins: string[]) => boolean;
     };
   };
   ```
   - Checks if required binaries exist on the system
   - Checks OS compatibility
   - Checks environment variables

3. **Truncate if over budget**:
   - Binary search for largest skill prefix that fits char budget
   - Logs warnings when skills are truncated

4. **Compile into prompt**:
   - `formatSkillsForPrompt()` creates the system prompt section
   - All eligible skills sent to model in one batch

### Size Limits

| Limit | Default |
|-------|---------|
| Max candidates per root | 300 |
| Max skills per source | 200 |
| Max skills in prompt | 150 |
| Max skill file bytes | 256KB |

### Skills Snapshot (Versioning)

```typescript
type SkillSnapshot = {
  prompt: string;           // Formatted for system prompt
  skills: Array<{ name, primaryEnv?, requiredEnv? }>;
  resolvedSkills?: Skill[];
  version?: number;         // Cache invalidation
};
```

Version bumped when: skills directory changes (fs.watch), remote node changes, config changes.

### Command Dispatch

Skills can optionally dispatch to tools directly:

```yaml
---
name: my-skill
command-dispatch: tool
command-tool: exec
command-arg-mode: raw
---
```

This lets skills be invoked as CLI commands that call tools, not just context documents.

## Tool Policy System

OpenClaw has sophisticated tool policies (separate from skills):

### Tool Profiles

- `minimal` — bare minimum tools
- `coding` — standard dev tools
- `messaging` — communication tools
- `full` — everything

### Policy Layers

1. Global allow/deny lists
2. Per-provider overrides
3. Per-model overrides
4. Per-sender overrides (in group chats)
5. Tool loop detection (repetition protection)
6. Elevated mode gating

### Tool Resolution

```typescript
function resolvePluginTools(params: {
  context: OpenClawPluginToolContext;
  toolAllowlist?: string[];
  suppressNameConflicts?: boolean;
}): AnyAgentTool[]
```

## MCP Integration (Limited)

OpenClaw uses MCP **only for browser automation** (Chrome DevTools):
- Launches `npx chrome-devtools-mcp@latest` as subprocess
- Connects via `StdioClientTransport`
- Tools: `list_pages`, `new_page`, `take_snapshot`, `click`, `fill`
- NOT used for general tool discovery

## Remote Skill Execution (Nodes)

OpenClaw supports executing skills on remote machines:
- Probes remote macOS nodes for available binaries
- `system.which` / `system.run` to check bin availability
- Updates skill snapshot version when remote capabilities change

## Relevance to sbot

### What to adopt:

**Skills format:**
- SKILL.md with frontmatter — clean, readable, versionable
- Multi-source discovery with precedence
- Eligibility filtering (check if required bins exist)
- Size limits to prevent prompt bloat

**Tool policies (later):**
- Profile-based tool filtering (minimal/full) for different use cases
- Per-channel overrides (Telegram gets fewer tools than CLI)

### What NOT to adopt:

- **No dynamic tool search**: OpenClaw sends all tools upfront. For sbot with many tools, consider Claude Code's `ToolSearch` pattern instead — a meta-tool that searches for and loads tool schemas on demand
- **Remote nodes**: unnecessary complexity for sbot
- **Browser MCP**: too specialized; sbot can add browser tools differently

### Key Insight for sbot's Layer 11 (Tool Search)

Since neither OpenCode nor OpenClaw implements deferred/searchable tools, look at **Claude Code's `ToolSearch`** pattern instead:
1. Agent starts with a small set of always-available tools
2. A `tool_search` meta-tool is available
3. Agent calls `tool_search("slack send")` when it needs a tool
4. Tool schemas are loaded on demand, reducing initial prompt size
5. This is especially valuable when integrating many MCP servers

This is the pattern Anthropic calls "deferred tools" — tools listed by name only until their full schema is fetched.
