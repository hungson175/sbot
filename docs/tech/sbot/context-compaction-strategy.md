# Context Compaction Strategy

## Design: Two-Phase Compaction + Tiered Memory

### Phase 1 — Prune (cheap, no LLM call)

Replace old tool output content with `[pruned: N chars]` while keeping message structure intact.

**Why this beats "summarize into one message":**
- **API validity**: Tool calls are pairs (AIMessage + ToolMessage). You can't delete one side. Pruning keeps pairs valid while gutting the content.
- **Shape preservation**: AI still sees "I called `write_file` at turn 8, then `exec_cmd` at turn 12" — knows what happened even without content.
- **KV cache stability**: Pruned messages are consistent across turns (`[pruned: N chars]` never changes), so the cache prefix stays warm. Summarizing into one new message destroys the entire cache.
- **Scalable for tool-heavy agents**: Most context bloat in coding agents is tool output (file contents, command output, accessibility trees), not human/AI turns.

### Phase 2 — LLM Summary (expensive, only when Phase 1 is insufficient)

When pruning alone can't bring context below threshold (meaning hundreds of human/AI turns have accumulated), use the LLM to generate a structured summary, then rebuild history as:

```
[SystemMessage]
[HumanMessage: "## Session Summary\n..."]
[AIMessage: "Understood. I have the context."]
[...last N recent turns...]
```

The compaction LLM call appends COMPACT_PROMPT at the END of history — reusing the full KV cache of the long conversation. The compaction call itself is cheap.

### Token Estimation — Use API Counts, Not Tiktoken

**Problem discovered**: tiktoken (cl100k_base) overestimates by ~5-6x vs MiniMax's actual tokenizer.

**Solution (learned from Codex)**:
- Use the actual API token count from the previous response (`last_token_usage.total_tokens`) as the accurate base
- Only estimate NEW messages added since the last API response using `bytes/4` heuristic
- Persist the API count in JSONL (`_type: usage`) so it survives bot restarts
- Fall back to full estimate only on the very first turn of a new session

### Pruning Must Be Permanent

**Problem discovered**: if pruning is in-memory only and the JSONL keeps full content, every turn re-prunes the same messages → cache miss every turn for re-pruned messages.

**Solution**: `save_full_session()` overwrites the JSONL with pruned content. Next turn loads the already-pruned messages → KV cache hits for old messages → stable cache prefix.

## Tiered Memory Architecture

### Hot — In-Session (compact.py)
- Pruned message history in the current session
- Managed by Phase 1 + Phase 2 compaction
- Lives in `sessions/{session_key}.jsonl`

### Warm — Cross-Session (MemoryStore)
- `MEMORY.md`: key facts, user preferences, project state
- Injected into system prompt on each session start
- Written during compaction (`memory_update` field)
- **Gap**: not written on clean session end (no compaction trigger) — needs a "session close" hook

### Cold — Searchable Log (HISTORY.md)
- Append-only timestamped paragraphs of what happened
- Written during compaction (`history_entry` field)
- Grep-searchable for recalling past context
- **Future**: vector index for semantic recall

## Future: Day Logs (OpenAI-style)

- Daily conversation summaries, auto-generated
- Stored in a searchable format (daily files or vector DB)
- Used for "what did we do yesterday?" queries
- Complements in-session compaction (compaction = within session, day logs = across sessions)

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `CONTEXT_WINDOW` | 204,000 | MiniMax M2.5 context |
| `COMPACT_TRIGGER` | 0.60 | Phase 1 fires at 60% |
| `POST_COMPACT_TARGET` | 0.40 | Phase 2 target |
| `KEEP_RECENT_TURNS` | 3 | Turns protected from pruning |
| `BYTES_PER_TOKEN` | 4 | Estimation heuristic (Codex) |
