# Auto-Compact Design

## Problem

Long conversations blow the context window (204k for MiniMax). Need to summarize old history while preserving what matters.

## How nanobot does it

### Trigger
- Token-based: triggers when estimated prompt exceeds full context window
- Target: shrink to 50% of context window
- Checked before each LLM call and after each turn

### Summarization
- Uses the SAME LLM with forced `save_memory` tool call
- Prompt: "You are a memory consolidation agent. Call save_memory with your consolidation."
- Input: current MEMORY.md + formatted old messages
- Output: `{ history_entry: str, memory_update: str }` (structured via tool call)

### What it preserves
- `history_entry` → appended to HISTORY.md (grep-searchable timestamped log)
- `memory_update` → replaces MEMORY.md (long-term facts, injected into system prompt)
- Recent turns stay in history (only old turns get archived)

### Key design: offset-based, not deletion
- Messages are NEVER deleted from session JSONL (append-only for cache friendliness)
- `last_consolidated` offset tracks where archival stopped
- `get_history()` skips messages before the offset
- Consolidation boundary always aligns to USER turn boundaries (no orphaned tool calls)

### Failure handling
- 3 consecutive failures → fall back to raw message dump (no LLM summary)
- Multi-round: up to 5 rounds of incremental consolidation if single pass isn't enough

## sbot's approach (our design)

### Trigger
- Estimate token count before each LLM call
- Trigger at ~70% of context window (conservative, gives room for response)

### Compact summary structure (structured output via Pydantic)

```python
class CompactTurn(BaseModel):
    user_query: str       # full user query
    bot_response: str     # max 200 chars, truncated

class CompactSummary(BaseModel):
    session_summary: str          # 3-4 sentences: what this session is about
    turns: list[CompactTurn]      # compacted old turns (no tool calls/results)
    plan_state: list[dict] | None # current plan todo_list if plan tool was used
    files_touched: list[str]      # files the LLM thinks need re-reading
```

### What to keep in full
- Last 2-3 complete turns (including tool calls/results — these have critical context)
- Current plan state (if plan tool was used)
- Files touched list (LLM decides which need re-reading)

### What to compact
- Older turns: user query (full) + bot response (max 200 chars)
- Strip all tool_call and tool_result content from older turns (too verbose)

### KV cache optimization
- The compact instruction is APPENDED at the END of the existing conversation
- This leverages the KV cache from the full previous conversation
- Do NOT start a new conversation for summarization — that reprocesses everything from scratch

### Compact prompt
Appended as the last user message:
```
Summarize this conversation so far to continue in a new context window.
Return a structured CompactSummary with: session_summary, compacted turns,
current plan state, and files that may need re-reading.
```

### Transition
- LLM generates CompactSummary (structured output parser)
- New history = SystemMessage + CompactSummary as context + last 2-3 full turns
- Save compact event to session JSONL (marked as `_type: compact`)
- Update `last_consolidated` offset

### Two-layer memory (same as nanobot)
- **MEMORY.md** — long-term facts, injected into system prompt every turn
- **HISTORY.md** — timestamped log of all consolidations (grep-searchable)

## Differences from nanobot

| Aspect | nanobot | sbot |
|--------|---------|------|
| Output format | Tool call with 2 string fields | Pydantic structured output |
| What's preserved | Just memory + history text | Structured: turns, plan state, files touched |
| Trigger threshold | 100% of context window | 70% (conservative) |
| Plan awareness | No | Yes — preserves plan tool state |
| KV cache | Not mentioned | Explicit: append at end of conversation |
| Recent turns | Offset-based (all unconsolidated) | Explicitly keep last 2-3 full turns |
