# Extension Guide

How nanobot is designed to be extended. Useful reference for when sbot reaches the package-structure stage.

## Add a New Channel

1. **Create** `nanobot/channels/<name>.py` extending `BaseChannel`:
   - `start()` — connect and listen to platform events
   - `stop()` — close resources
   - `send(msg)` — post outbound message
   - Use `_handle_message()` from BaseChannel for allowlist checks + bus publish

2. **Add config** in `config/schema.py`: define `<Name>Config`, add under `ChannelsConfig`

3. **Enable** via `channels.<name>.enabled = true` in config JSON

No manual registry edit needed — `ChannelManager` auto-discovers channel modules.

## Add a New LLM Provider

1. **Register metadata** in `providers/registry.py` as `ProviderSpec`:
   - `name`, `keywords`, `env_key`
   - optional: `litellm_prefix`, `skip_prefixes`, gateway/local detection, per-model overrides

2. **Add config field** in `ProvidersConfig` (`config/schema.py`)

3. **Choose implementation**:
   - Use `LiteLLMProvider` for standard OpenAI-compatible APIs
   - Add dedicated class for special auth/protocol (OAuth, Azure-specific, custom endpoints)

## Add a New Tool

1. **Implement** under `agent/tools/` extending `Tool`:
   - `name`, `description`, `parameters` (JSON schema), `execute()`

2. **Register** in `AgentLoop._register_default_tools()` or conditionally at runtime

3. **Safety**: return structured errors, keep output bounded, validate inputs

## Add an MCP Server

Purely config-driven via `tools.mcpServers`:

```json
// Stdio transport
{ "tools": { "mcpServers": { "filesystem": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
}}}}

// HTTP/SSE transport
{ "tools": { "mcpServers": { "remote": {
  "url": "https://example.com/mcp/",
  "headers": { "Authorization": "Bearer token" },
  "toolTimeout": 60
}}}}
```

Agent lazily connects and auto-registers discovered tools.

## Add/Override Skills

- Built-in: `nanobot/skills/*/SKILL.md`
- Workspace: `workspace/skills/*/SKILL.md` (overrides built-in)

`SkillsLoader` favors workspace over built-in. Skill metadata can declare requirements; unavailable skills listed with requirement hints.

## Multi-Instance Deployment

Run isolated instances via different `--config` values:
- Runtime dirs (cron, media, logs) derived from config location
- Workspace can be shared or overridden (`--workspace`)

Enables one process per channel/team/tenant with clean state isolation.

## Security Checklist

- Keep `allow_from` explicit (avoid accidental public access)
- Prefer `tools.restrictToWorkspace=true` for constrained deployments
- Sanitize/scope user inputs before shell execution
- Don't leak internal secrets in outbound metadata
- Implement robust reconnect + graceful shutdown for long-running integrations
