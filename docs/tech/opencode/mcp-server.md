# OpenCode: MCP Server Implementation

Reference: `sample_code/opencode/packages/opencode/src/mcp/`

## Overview

OpenCode uses Anthropic's Model Context Protocol SDK (`@modelcontextprotocol/sdk`) to connect to external MCP servers as a **client**. MCP tools are discovered from connected servers and merged into the agent's tool registry alongside built-in tools.

## Connection Types

### Local MCP Servers (`McpLocal`)
- Launched via `StdioClientTransport` — spawns a subprocess
- Config: `command` + `args` array + optional `environment`
- Graceful shutdown kills the entire process tree (handles grandchild processes like Chrome)

### Remote MCP Servers (`McpRemote`)
- Dual-transport fallback: `StreamableHTTPClientTransport` → `SSEClientTransport`
- Built-in OAuth support (auto-detected unless `oauth: false`)
- Custom headers, URL-based config

## Configuration (`opencode.json`)

```json
{
  "mcp": {
    "my-local": {
      "type": "local",
      "command": ["opencode", "x", "@modelcontextprotocol/server-filesystem"],
      "environment": { "KEY": "value" },
      "timeout": 5000,
      "enabled": true
    },
    "my-remote": {
      "type": "remote",
      "url": "https://example.com/mcp",
      "headers": { "Authorization": "Bearer token" },
      "oauth": { "clientId": "...", "clientSecret": "..." },
      "timeout": 5000
    }
  }
}
```

## Tool Discovery Flow

1. MCP clients connect to configured servers
2. `MCP.tools()` lists all tools from all connected servers
3. Each MCP tool is converted to AI SDK `Tool` format via `convertMcpTool()`
4. Tool names sanitized (special chars removed)
5. Per-server timeout applied
6. Listens for `ToolListChangedNotification` for dynamic updates

## Capabilities Exposed

| Capability | Method | Description |
|-----------|--------|-------------|
| Tools | `MCP.tools()` | Returns AI SDK Tool objects from all servers |
| Prompts | `MCP.prompts()` | List prompts from servers |
| Resources | `MCP.resources()` | Access structured data |

## Connection States

```
connected → working normally
disabled  → explicitly turned off in config
failed    → connection error (with error message)
needs_auth → OAuth required
needs_client_registration → Dynamic client registration needed
```

## CLI Commands

```bash
opencode mcp list           # Show configured servers
opencode mcp add            # Interactive wizard to add server
opencode mcp auth [name]    # OAuth authentication
opencode mcp auth list      # Show auth status
opencode mcp logout [name]  # Remove credentials
opencode mcp debug <name>   # Test connection
```

## Key Design Patterns

- **Instance state management**: `Instance.state()` handles init/cleanup lifecycle
- **Namespace pattern**: `MCP.tools()`, `MCP.prompts()` — clean API surface
- **Lazy initialization**: MCP clients only connect when first used
- **Event bus integration**: `MCP.ToolsChanged` event published when server tools change

## Integration with Tool Registry

```
ToolRegistry.tools(model, agent)
  ├── Built-in tools (bash, read, write, edit, grep, glob, ...)
  ├── Custom tools (.opencode/tool/*.ts)
  ├── Plugin tools
  └── MCP.tools() ← from all connected MCP servers
```

All tool sources are merged into a single flat namespace. MCP tools are indistinguishable from built-in tools at the agent level.

## Relevance to sbot

**What to adopt:**
- Config-driven MCP server definitions (JSON config, not code)
- Lazy connection with graceful cleanup
- Merging MCP tools into existing tool registry seamlessly
- Connection state tracking for user feedback

**What to simplify:**
- Skip OAuth/remote servers initially — start with local `stdio` transport only
- Skip CLI wizard — config file is enough
- sbot uses LangChain tools, so conversion is MCP → LangChain `@tool` format
