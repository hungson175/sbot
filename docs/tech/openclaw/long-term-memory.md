# OpenClaw Long-Term Memory — Deep Implementation Study

Reference: `sample_code/openclaw/src/memory/`
This document is derived from reading the full source code. It is detailed enough to reimplement the system from scratch.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [SQLite Schema](#2-sqlite-schema)
3. [MemoryIndexManager — Core Class](#3-memoryindexmanager--core-class)
4. [Chunking Algorithm](#4-chunking-algorithm)
5. [Embedding Batching](#5-embedding-batching)
6. [Embedding Cache](#6-embedding-cache)
7. [File Sync and Watching](#7-file-sync-and-watching)
8. [Session Memory Indexing (Experimental)](#8-session-memory-indexing-experimental)
9. [Search Implementation](#9-search-implementation)
10. [Hybrid Search Merge Algorithm](#10-hybrid-search-merge-algorithm)
11. [MMR Re-ranking](#11-mmr-re-ranking)
12. [Temporal Decay](#12-temporal-decay)
13. [Agent-Facing Tools](#13-agent-facing-tools)
14. [Pre-Compaction Memory Flush](#14-pre-compaction-memory-flush)
15. [QMD Backend](#15-qmd-backend)
16. [QMD Output Parsing](#16-qmd-output-parsing)
17. [QMD Scope Enforcement](#17-qmd-scope-enforcement)
18. [Embedding Providers and Auto-Selection](#18-embedding-providers-and-auto-selection)
19. [Readonly Recovery](#19-readonly-recovery)
20. [Multimodal Memory](#20-multimodal-memory)
21. [Configuration Reference](#21-configuration-reference)
22. [Key Constants Summary](#22-key-constants-summary)
23. [Relevance to sbot](#23-relevance-to-sbot)

---

## 1. Architecture Overview

OpenClaw memory is **file-first**: Markdown files on disk are the canonical source of truth. The search index is derived and always rebuildable.

Two backend implementations share the `MemorySearchManager` interface:

```
              ┌─────────────────────────────────┐
              │      MemorySearchManager         │
              │  (interface: search, readFile,   │
              │   status, sync, close)           │
              └──────────┬──────────────┬────────┘
                         │              │
              ┌──────────▼──┐    ┌──────▼──────────┐
              │  Builtin     │    │  QMD Backend    │
              │  SQLite mgr  │    │  (subprocess)   │
              └──────────────┘    └─────────────────┘
```

**Builtin backend**: `MemoryIndexManager` extends `MemoryManagerEmbeddingOps` extends `MemoryManagerSyncOps`. Three-level class hierarchy.

**QMD backend**: `QmdMemoryManager` — shells out to the `qmd` CLI tool. Auto-falls back to builtin if `qmd` fails.

**Manager cache**: A module-level `Map<string, MemoryIndexManager>` (`INDEX_CACHE`) ensures one manager per `{agentId}:{workspaceDir}:{settingsJSON}` key. Construction is guarded by a second map (`INDEX_CACHE_PENDING`) to prevent concurrent creates.

---

## 2. SQLite Schema

Source: `src/memory/memory-schema.ts`

Database path default: `~/.openclaw/memory/{agentId}.sqlite` (configurable via `memorySearch.store.path`, supports `{agentId}` token).

### Tables

**`meta`** — key/value store for index metadata:
```sql
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```
The single metadata row uses key `"memory_index_meta_v1"` and stores JSON:
```typescript
type MemoryIndexMeta = {
  model: string;        // embedding model name
  provider: string;     // provider id (openai, gemini, etc.)
  providerKey?: string; // SHA-256 of provider config (detects endpoint changes)
  sources?: MemorySource[]; // ["memory"] or ["memory","sessions"]
  scopeHash?: string;   // hash of source file paths (detects extraPaths changes)
  chunkTokens: number;  // chunking config
  chunkOverlap: number;
  vectorDims?: number;  // embedding dimensions (for sqlite-vec table)
};
```

**`files`** — tracks indexed source files:
```sql
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,      -- workspace-relative path
  source TEXT NOT NULL DEFAULT 'memory',  -- 'memory' | 'sessions'
  hash TEXT NOT NULL,         -- SHA-256 of file content
  mtime INTEGER NOT NULL,     -- mtimeMs from fs.stat()
  size INTEGER NOT NULL       -- bytes
);
```

**`chunks`** — text chunks with embeddings:
```sql
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,        -- SHA-256 hash of source:path:startLine:endLine:chunkHash:model
  path TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'memory',
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  hash TEXT NOT NULL,         -- SHA-256 of chunk text
  model TEXT NOT NULL,        -- embedding model name
  text TEXT NOT NULL,
  embedding TEXT NOT NULL,    -- JSON array of floats
  updated_at INTEGER NOT NULL -- Date.now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
```

**`chunks_vec`** — virtual vector table (sqlite-vec extension, created lazily):
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
  id TEXT PRIMARY KEY,
  embedding FLOAT[{dimensions}]  -- dimensions set on first embedding
);
```
This table is created or recreated whenever `ensureVectorReady(dimensions)` is called and the dimension count has changed.

**`chunks_fts`** — FTS5 full-text virtual table:
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text,
  id UNINDEXED,
  path UNINDEXED,
  source UNINDEXED,
  model UNINDEXED,
  start_line UNINDEXED,
  end_line UNINDEXED
);
```
Only `text` is indexed for full-text search; other columns are stored but not indexed.

**`embedding_cache`** — persists computed embeddings:
```sql
CREATE TABLE IF NOT EXISTS embedding_cache (
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  provider_key TEXT NOT NULL,   -- SHA-256 of provider config
  hash TEXT NOT NULL,           -- SHA-256 of chunk text
  embedding TEXT NOT NULL,      -- JSON array of floats
  dims INTEGER,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (provider, model, provider_key, hash)
);
CREATE INDEX IF NOT EXISTS idx_embedding_cache_updated_at ON embedding_cache(updated_at);
```

### Schema migration

`ensureColumn()` is called after table creation to add `source` column to existing `files` and `chunks` tables (backward compatibility). Uses `PRAGMA table_info()` to check if column exists before `ALTER TABLE`.

### Database open options

```typescript
new DatabaseSync(dbPath, { allowExtension: settings.store.vector.enabled })
db.exec("PRAGMA busy_timeout = 5000")  // 5s retry on SQLITE_BUSY
```

---

## 3. MemoryIndexManager — Core Class

Source: `src/memory/manager.ts`

### Class hierarchy

```
MemoryManagerSyncOps (abstract, manager-sync-ops.ts)
  └── MemoryManagerEmbeddingOps (abstract, manager-embedding-ops.ts)
        └── MemoryIndexManager (concrete, manager.ts)
```

### Static factory: `MemoryIndexManager.get()`

```typescript
static async get(params: {
  cfg: OpenClawConfig;
  agentId: string;
  purpose?: "default" | "status";
}): Promise<MemoryIndexManager | null>
```

Returns null if memory search is not configured (`resolveMemorySearchConfig` returns null). Otherwise uses the `INDEX_CACHE` / `INDEX_CACHE_PENDING` pattern to ensure singleton per key.

Cache key: `${agentId}:${workspaceDir}:${JSON.stringify(settings)}`

### Constructor behavior (private)

Order of operations:
1. Store all settings
2. `openDatabase()` — create SQLite at configured path, set `busy_timeout = 5000`
3. `computeProviderKey()` — SHA-256 of provider config (used for cache isolation)
4. `ensureSchema()` — create tables, attempt FTS5 virtual table
5. `readMeta()` — load previous `memory_index_meta_v1` row
6. `ensureWatcher()` — start chokidar file watcher (if `sync.watch` enabled)
7. `ensureSessionListener()` — subscribe to session transcript events
8. `ensureIntervalSync()` — set interval timer
9. `dirty = sources.has("memory") && (statusOnly ? !meta : true)` — new manager is dirty unless status-only with existing meta
10. `batch = resolveBatchConfig()` — resolve batch embedding config

### `search()` method

```typescript
async search(
  query: string,
  opts?: { maxResults?: number; minScore?: number; sessionKey?: string }
): Promise<MemorySearchResult[]>
```

Full algorithm:
1. Call `warmSession(opts?.sessionKey)` (fire-and-forget)
2. If `sync.onSearch && (dirty || sessionsDirty)`: fire-and-forget `sync({ reason: "search" })`
3. Trim query; return `[]` if empty
4. Resolve `minScore`, `maxResults`, `hybrid` config
5. Compute `candidates = min(200, max(1, floor(maxResults * candidateMultiplier)))`
6. **FTS-only mode** (no embedding provider): extract keywords via `extractKeywords()`, search each keyword separately, merge and deduplicate by highest score
7. **Hybrid mode** (provider available):
   - If hybrid enabled and FTS available: `searchKeyword(cleaned, candidates)`
   - Embed query: `embedQueryWithTimeout(cleaned)` — check if non-zero vector
   - `searchVector(queryVec, candidates)` (only if non-zero vector)
   - If hybrid not enabled or FTS unavailable: filter by minScore and return vector results
   - `mergeHybridResults(...)` with MMR and temporal decay settings
   - Apply `minScore` filter; if no results but keyword results exist, use `relaxedMinScore = min(minScore, hybrid.textWeight)`

### `readFile()` method

```typescript
async readFile(params: {
  relPath: string;
  from?: number;
  lines?: number;
}): Promise<{ text: string; path: string }>
```

Security checks before reading:
- Resolve absolute path, compute workspace-relative path
- Accept if `inWorkspace && isMemoryPath(relPath)` (must start with `memory/` or be `MEMORY.md`)
- Otherwise check `extraPaths`: each extra path is `lstat()`-checked (symlinks rejected), directory or exact `.md` file match required
- File must end in `.md`
- Returns `{ text: "", path }` instead of throwing if file missing (graceful degradation)
- Line slicing: `lines.slice(from-1, from-1+count).join("\n")`

---

## 4. Chunking Algorithm

Source: `src/memory/internal.ts`, function `chunkMarkdown()`

```typescript
function chunkMarkdown(
  content: string,
  chunking: { tokens: number; overlap: number }
): MemoryChunk[]
```

**Token-to-char conversion**: `maxChars = max(32, tokens * 4)`, `overlapChars = max(0, overlap * 4)`.

Default settings: `tokens = 400`, `overlap = 80`, so `maxChars = 1600`, `overlapChars = 320`.

**Algorithm**:

1. Split content by `\n` to get lines array
2. For each line:
   - If line is longer than `maxChars`, split into `maxChars`-sized segments
   - For each segment, compute `lineSize = segment.length + 1`
   - If `currentChars + lineSize > maxChars && current.length > 0`: flush chunk, carry overlap
   - Add segment to current buffer
3. Final `flush()` after all lines
4. Each chunk gets:
   - `startLine`: 1-indexed line number of first line
   - `endLine`: 1-indexed line number of last line
   - `text`: joined lines
   - `hash`: `SHA-256(text)`
   - `embeddingInput`: `buildTextEmbeddingInput(text)` (wraps text in `{ text, parts: [{ type: "text", text }] }`)

**Overlap carry** (`carryOverlap()`): After flush, walk the current chunk backward from the end, accumulating lines until `acc >= overlapChars`. Keep those lines in `current` for the next chunk.

**Chunk ID format**: `SHA-256("${source}:${path}:${startLine}:${endLine}:${chunkHash}:${model}")`

After chunking, `enforceEmbeddingMaxInputTokens()` is called to drop chunks that exceed the embedding provider's per-item token limit. The batch limit is `EMBEDDING_BATCH_MAX_TOKENS = 8000` (estimated chars, not actual tokens).

---

## 5. Embedding Batching

Source: `src/memory/manager-embedding-ops.ts`

### Constants

| Constant | Value |
|----------|-------|
| `EMBEDDING_BATCH_MAX_TOKENS` | 8000 (estimated chars) |
| `EMBEDDING_INDEX_CONCURRENCY` | 4 |
| `EMBEDDING_RETRY_MAX_ATTEMPTS` | 3 |
| `EMBEDDING_RETRY_BASE_DELAY_MS` | 500 |
| `EMBEDDING_RETRY_MAX_DELAY_MS` | 8000 |
| `BATCH_FAILURE_LIMIT` | 2 |
| `EMBEDDING_QUERY_TIMEOUT_REMOTE_MS` | 60,000 (1 min) |
| `EMBEDDING_QUERY_TIMEOUT_LOCAL_MS` | 300,000 (5 min) |
| `EMBEDDING_BATCH_TIMEOUT_REMOTE_MS` | 120,000 (2 min) |
| `EMBEDDING_BATCH_TIMEOUT_LOCAL_MS` | 600,000 (10 min) |

### Batch building: `buildEmbeddingBatches()`

Groups chunks into batches where each batch's total estimated bytes does not exceed `EMBEDDING_BATCH_MAX_TOKENS`:

- Size estimate: `estimateStructuredEmbeddingInputBytes(embeddingInput)` for multimodal, `estimateUtf8Bytes(text)` for text
- A chunk larger than `EMBEDDING_BATCH_MAX_TOKENS` on its own gets its own single-item batch
- New batch created when adding a chunk would exceed the limit

### Retry logic: `embedBatchWithRetry()`

```typescript
async embedBatchWithRetry(texts: string[]): Promise<number[][]>
```

Retryable error pattern (case-insensitive):
```
/(rate[_ ]limit|too many requests|429|resource has been exhausted|5\d\d|cloudflare|tokens per day)/i
```

Retry jitter: `waitMs = min(MAX_DELAY, round(delayMs * (1 + random() * 0.2)))`.

Delay doubles each attempt: 500ms → 1000ms → 2000ms (capped at 8000ms).

### Batch failure circuit-breaker

`batchFailureCount` increments on failure. When `batchFailureCount >= BATCH_FAILURE_LIMIT` (2), `batch.enabled = false` permanently for the lifetime of this manager instance.

Immediate disable (skip incrementing): when error message matches `/asyncBatchEmbedContent not available/i`.

On batch success: `batchFailureCount` resets to 0, `batchFailureLastError` and `batchFailureLastProvider` cleared.

Fallback path: when batch disabled or fails, falls back to `embedChunksInBatches()` (sync batching with retry).

### Provider-specific batch paths

- **OpenAI**: `OPENAI_BATCH_ENDPOINT`, POST body `{ model, input: chunk.text }`
- **Gemini**: async `asyncBatchEmbedContent` endpoint, `RETRIEVAL_DOCUMENT` task type; multimodal chunks skipped (use sync path)
- **Voyage**: voyage-specific batch format

### Embedding encoding for storage

Embeddings stored in `chunks` table as `JSON.stringify(embedding)` (string). Stored in `chunks_vec` as `Buffer.from(new Float32Array(embedding).buffer)` (Float32 binary blob).

### Embedding decoding

```typescript
function parseEmbedding(raw: string): number[] {
  try {
    return JSON.parse(raw) as number[];
  } catch {
    return [];
  }
}
```

### Cosine similarity (JS fallback when sqlite-vec unavailable)

```typescript
function cosineSimilarity(a: number[], b: number[]): number {
  // dot / (sqrt(normA) * sqrt(normB))
  // Returns 0 if either vector is zero-norm
}
```

---

## 6. Embedding Cache

Source: `src/memory/manager-embedding-ops.ts`

### Cache key

Primary key in `embedding_cache` table: `(provider, model, provider_key, hash)`.

- `provider`: provider id string (`"openai"`, `"gemini"`, etc.)
- `model`: model name string
- `provider_key`: SHA-256 computed by `computeProviderKey()`
- `hash`: SHA-256 of chunk text

### Provider key computation: `computeProviderKey()`

For OpenAI: `SHA-256(JSON.stringify({ provider, baseUrl, model, headers }))` where headers excludes `Authorization` and are sorted alphabetically.

For Gemini: excludes `authorization` and `x-goog-api-key` headers, includes `outputDimensionality`.

For others: `SHA-256(JSON.stringify({ provider, model }))`.

FTS-only mode (no provider): `SHA-256(JSON.stringify({ provider: "none", model: "fts-only" }))`.

### Cache loading: `loadEmbeddingCache()`

Loads in batches of 400 hashes at a time (to stay within SQLite placeholder limits). Returns `Map<hash, embedding>`.

### Cache eviction: `pruneEmbeddingCacheIfNeeded()`

Called after indexing. If `count > maxEntries`, deletes `excess = count - maxEntries` oldest entries ordered by `updated_at ASC`.

### Cache upsert: `upsertEmbeddingCache()`

Uses `INSERT ... ON CONFLICT DO UPDATE SET` to upsert. Updates `updated_at` to `Date.now()` on every write (used for LRU eviction).

### Flow during indexing

1. `collectCachedEmbeddings(chunks)`: load cache for all chunk hashes
2. Return cached embeddings immediately; collect `missing` list with index positions
3. For missing chunks: group into batches, call provider, store results in cache
4. `pruneEmbeddingCacheIfNeeded()` after sync

---

## 7. File Sync and Watching

Source: `src/memory/manager-sync-ops.ts`

### File watcher: `ensureWatcher()`

Uses **chokidar** to watch:
- `{workspaceDir}/MEMORY.md`
- `{workspaceDir}/memory.md`
- `{workspaceDir}/memory/**/*.md`
- Each `extraPath` directory: `**/*.md` (plus multimodal extensions if enabled)
- Each `extraPath` file: if `.md` or classified multimodal

Ignored directories: `.git`, `node_modules`, `.pnpm-store`, `.venv`, `venv`, `.tox`, `__pycache__`.

Watcher options:
```typescript
{
  ignoreInitial: true,
  awaitWriteFinish: {
    stabilityThreshold: settings.sync.watchDebounceMs,  // default 1500ms
    pollInterval: 100
  }
}
```

On `add`, `change`, `unlink`: set `this.dirty = true` and call `scheduleWatchSync()`.

`scheduleWatchSync()` debounces: cancels previous timer, sets new `setTimeout` for `watchDebounceMs`. On fire: `sync({ reason: "watch" })`.

### Sync triggers

| Trigger | Reason string | Notes |
|---------|---------------|-------|
| File watcher | `"watch"` | Does not sync sessions |
| Session start | `"session-start"` | Does not sync sessions |
| Search call | `"search"` | Syncs sessions if dirty |
| Interval timer | `"interval"` | Syncs everything |
| Session delta | `"session-delta"` | Targeted or full sessions sync |
| Queued session files | `"queued-session-files"` | Post-sync targeted files |
| Explicit call | (caller-set reason) | |

### runSync() — full sync flow

```typescript
protected async runSync(params?: {
  reason?: string;
  force?: boolean;
  sessionFiles?: string[];
  progress?: (update: MemorySyncProgressUpdate) => void;
})
```

1. `ensureVectorReady()` — attempt to load sqlite-vec extension
2. `readMeta()` — load stored index metadata
3. Compute `needsFullReindex`:
   - `params.force && !hasTargetSessionFiles`
   - No meta stored
   - Model changed
   - Provider changed
   - Provider key changed (endpoint/headers changed)
   - Sources list changed
   - Scope hash changed (extraPaths changed)
   - Chunk tokens or overlap changed
4. If `needsFullReindex`:
   - Run **safe reindex**: create new temp SQLite DB, index everything into it, seed cache from old DB, swap files atomically
5. Else:
   - `syncMemoryFiles({ needsFullReindex: false, progress })`
   - `syncSessionFiles(...)` if sessions enabled and dirty

### Safe reindex: `runSafeReindex()`

Creates temp DB at `{dbPath}.tmp-{uuid}`, indexes everything fresh, then calls `swapIndexFiles(targetPath, tempPath)`:

1. Move existing DB to `{dbPath}.backup-{uuid}` (moves `.sqlite`, `.sqlite-wal`, `.sqlite-shm`)
2. Move temp DB to final path
3. On failure: restore backup
4. Remove backup

### Memory file sync: `syncMemoryFiles()`

1. `listMemoryFiles(workspaceDir, extraPaths, multimodal)` — collect all qualifying files
2. Build `MemoryFileEntry` for each file (reads content hash, mtime, size)
3. For each entry: check `files` table hash — skip if unchanged and not full reindex
4. `indexFile(entry, { source: "memory" })` for changed files
5. Prune stale file records (files deleted from disk)

### indexFile() — per-file indexing

```typescript
protected async indexFile(
  entry: MemoryFileEntry | SessionFileEntry,
  options: { source: MemorySource; content?: string }
)
```

1. Skip entirely in FTS-only mode (no provider)
2. For multimodal files: `buildMultimodalChunkForIndexing(entry)` — single chunk with base64-encoded binary + text label
3. For Markdown: `chunkMarkdown(content, settings.chunking)` → `enforceEmbeddingMaxInputTokens()`
4. Session files: `remapChunkLines(chunks, entry.lineMap)` to fix line numbers
5. `embedChunksWithBatch()` or `embedChunksInBatches()` depending on `batch.enabled`
6. `clearIndexedFileData(path, source)` — delete old chunks, FTS rows, vector rows for this file
7. For each chunk: INSERT into `chunks`, `chunks_vec` (if vector ready), `chunks_fts`
8. `upsertFileRecord(entry, source)` — update `files` table

---

## 8. Session Memory Indexing (Experimental)

Source: `src/memory/manager-sync-ops.ts`, `src/memory/session-files.ts`

Enabled by:
```json5
{ experimental: { sessionMemory: true }, sources: ["memory", "sessions"] }
```

### Session event subscription: `ensureSessionListener()`

Subscribes to `onSessionTranscriptUpdate` — an event emitted by the gateway whenever a session JSONL file is appended. Filters to only the agent's own session files.

On update: call `scheduleSessionDirty(sessionFile)`.

### Session delta debouncing

`scheduleSessionDirty()` uses a `SESSION_DIRTY_DEBOUNCE_MS = 5000ms` debounce. After 5 seconds of quiet, `processSessionDeltaBatch()` fires.

### Session delta tracking: `updateSessionDelta()`

Tracks per-file byte and message counts:
```typescript
type Delta = { lastSize: number; pendingBytes: number; pendingMessages: number }
```

- Reads current file `stat.size`
- `deltaBytes = max(0, size - lastSize)` (handles file truncation too)
- `pendingMessages` counted by scanning bytes `[lastSize..size]` for newline (`0x0a`) characters in 64 KB chunks (`SESSION_DELTA_READ_CHUNK_BYTES = 65536`)
- Thresholds checked: `pendingBytes >= deltaBytes || pendingMessages >= deltaMessages`
- Default thresholds: `deltaBytes = 100000` (~100 KB), `deltaMessages = 50` JSONL lines

### Session file building: `buildSessionEntry()`

Reads the JSONL session file, extracts User/Assistant turns as plain text. Returns a `SessionFileEntry` with:
- `path`: session-relative path (e.g., `sessions/abc.jsonl`)
- `content`: flattened text of turns
- `lineMap`: maps content-relative line numbers back to original JSONL line numbers (for `remapChunkLines()`)
- `hash`: SHA-256 of content
- `size`, `mtimeMs`

### Session file path

Stored in the index as `sessionPathForFile(absPath)` — a normalized relative-like path. The `files` table `source = "sessions"`.

### Session memory scope

Session indexing is isolated per agent — only that agent's own session JSONL files (`~/.openclaw/agents/{agentId}/sessions/*.jsonl`) are indexed.

---

## 9. Search Implementation

Source: `src/memory/manager-search.ts`

### Vector search: `searchVector()`

**Primary path** (sqlite-vec available):
```sql
SELECT c.id, c.path, c.start_line, c.end_line, c.text, c.source,
       vec_distance_cosine(v.embedding, ?) AS dist
  FROM chunks_vec v
  JOIN chunks c ON c.id = v.id
 WHERE c.model = ?{sourceFilter}
 ORDER BY dist ASC
 LIMIT ?
```
- Query vector: `Buffer.from(new Float32Array(queryVec).buffer)` (Float32 binary)
- Score: `1 - dist` (cosine similarity in [0, 1])
- Snippet: `truncateUtf16Safe(text, 700)` — truncate at 700 chars

**Fallback path** (no sqlite-vec):
- Load all chunks from DB: `SELECT id, path, start_line, end_line, text, embedding, source FROM chunks WHERE model = ?{sourceFilter}`
- Compute `cosineSimilarity(queryVec, parseEmbedding(row.embedding))` for each
- Sort descending, return top `limit`

### Keyword search: `searchKeyword()`

```sql
SELECT id, path, source, start_line, end_line, text,
       bm25(chunks_fts) AS rank
  FROM chunks_fts
 WHERE chunks_fts MATCH ?{modelClause}{sourceFilter}
 ORDER BY rank ASC
 LIMIT ?
```

Note: `rank ASC` because BM25 returns negative scores (more negative = more relevant).

FTS-only mode (no provider): `modelClause` is omitted, searching all models.

**FTS query building** (`buildFtsQuery()`):
1. Tokenize: `raw.match(/[\p{L}\p{N}_]+/gu)` — Unicode letters, numbers, underscores
2. Quote each token: `"token"` (strip any embedded double-quotes)
3. Join with ` AND `
4. Return null if no tokens (empty/punctuation-only query)

**BM25 score normalization** (`bm25RankToScore()`):
```typescript
function bm25RankToScore(rank: number): number {
  if (!Number.isFinite(rank)) return 1 / (1 + 999);
  if (rank < 0) {
    const relevance = -rank;
    return relevance / (1 + relevance);  // maps negative BM25 to (0, 1)
  }
  return 1 / (1 + rank);  // rank >= 0 means no match or degenerate
}
```

---

## 10. Hybrid Search Merge Algorithm

Source: `src/memory/hybrid.ts`, function `mergeHybridResults()`

### Input

- `vector: HybridVectorResult[]` — results with `{ id, path, startLine, endLine, source, snippet, vectorScore }`
- `keyword: HybridKeywordResult[]` — results with `{ id, path, startLine, endLine, source, snippet, textScore }`
- `vectorWeight: number` (default 0.7)
- `textWeight: number` (default 0.3)

Note: `vectorWeight + textWeight` should sum to 1.0 (config resolution normalizes them).

### Merge

Union by `id`:
1. Insert all vector results into `byId` map with `textScore = 0`
2. For keyword results: if id exists, update `textScore` (and snippet if non-empty); if not, insert with `vectorScore = 0`

### Score formula

```typescript
const score = vectorWeight * entry.vectorScore + textWeight * entry.textScore;
```

### Post-processing pipeline

```
Vector + Keyword → Weighted Merge → Temporal Decay → Sort DESC → MMR → Top-K
```

1. `mergeHybridResults()` calls `applyTemporalDecayToHybridResults()` (even if disabled — returns unchanged array)
2. `toSorted((a, b) => b.score - a.score)` — stable descending sort
3. If MMR enabled: `applyMMRToHybridResults(sorted, mmrConfig)`
4. Return sorted/MMR list (caller applies `minScore` and `slice(0, maxResults)`)

### Fallback for keyword-only results

After merging, if `strict.length === 0` but `keywordResults.length > 0`:
- `relaxedMinScore = min(minScore, hybrid.textWeight)` — keyword-only hits cap at `textWeight` (0.3), so if `minScore = 0.35` they'd be filtered out unfairly
- Re-filter merged list to only entries that appear in keyword results, at the relaxed score

---

## 11. MMR Re-ranking

Source: `src/memory/mmr.ts`

### Algorithm

Maximal Marginal Relevance (Carbonell & Goldstein, 1998):

```
MMR_score = λ * relevance - (1-λ) * max_similarity_to_already_selected
```

### Implementation: `mmrRerank<T extends MMRItem>()`

```typescript
type MMRItem = { id: string; score: number; content: string }
type MMRConfig = { enabled: boolean; lambda: number }
const DEFAULT_MMR_CONFIG = { enabled: false, lambda: 0.7 }
```

Steps:
1. Pre-tokenize all items: `tokenize(text)` → `Set<string>` of lowercase alphanumeric tokens (`/[a-z0-9_]+/g`)
2. **Score normalization**: `normalizedRelevance = (score - minScore) / (maxScore - minScore)` across all candidates. If `scoreRange == 0`, all scores become 1.
3. Clamp `lambda` to [0, 1]; if `lambda == 1`, return sorted by relevance
4. Iterative selection:
   - Start with empty `selected` set, full `remaining` set
   - Each iteration: for each candidate, compute `maxSimilarityToSelected(candidate, selected, tokenCache)` using Jaccard similarity
   - Pick candidate with highest `MMR_score = λ * normalizedRelevance - (1-λ) * maxSim`
   - Tiebreak: highest original score wins
   - Move winner from `remaining` to `selected`
5. Return `selected` in selection order

### Jaccard similarity

```typescript
function jaccardSimilarity(setA: Set<string>, setB: Set<string>): number {
  // |A ∩ B| / |A ∪ B|
  // Both empty → 1.0; one empty → 0.0
}
```

Applied to tokenized snippet content for diversity computation.

### `applyMMRToHybridResults()`

Adapter that converts `{ score, snippet, path, startLine }` to `MMRItem { id: "${path}:${startLine}:${index}", score, content: snippet }`, runs MMR, then maps back.

---

## 12. Temporal Decay

Source: `src/memory/temporal-decay.ts`

### Config

```typescript
type TemporalDecayConfig = { enabled: boolean; halfLifeDays: number }
const DEFAULT_TEMPORAL_DECAY_CONFIG = { enabled: false, halfLifeDays: 30 }
```

### Decay formula

```typescript
lambda = ln(2) / halfLifeDays        // e.g. 0.693 / 30 = 0.0231
multiplier = exp(-lambda * ageInDays)
decayedScore = score * multiplier
```

With `halfLifeDays = 30`:

| Age | Multiplier |
|-----|-----------|
| 0 days | 1.000 (100%) |
| 7 days | ~0.857 (86%) |
| 30 days | 0.500 (50%) |
| 90 days | 0.125 (12.5%) |
| 180 days | ~0.016 (1.6%) |

### Timestamp extraction: `extractTimestamp()`

Priority order:
1. **Dated memory path**: regex `/(?:^|\/)memory\/(\d{4})-(\d{2})-(\d{2})\.md$/` — parse YYYY-MM-DD from filename. Uses `Date.UTC(year, month-1, day)` and validates round-trip
2. **Evergreen files**: `MEMORY.md`, `memory.md`, or any `memory/` file that is NOT a dated file → return `null` (no decay, score kept at 100%)
3. **File mtime**: `fs.stat(absPath).mtimeMs` → `new Date(mtimeMs)` (for session transcripts and other sources)

Evergreen check:
```typescript
function isEvergreenMemoryPath(filePath: string): boolean {
  if (normalized === "MEMORY.md" || normalized === "memory.md") return true;
  if (!normalized.startsWith("memory/")) return false;
  return !DATED_MEMORY_PATH_RE.test(normalized);
}
```

### `applyTemporalDecayToHybridResults()`

- Uses `timestampPromiseCache: Map<string, Promise<Date | null>>` keyed by `"${source}:${path}"` to avoid redundant `fs.stat` calls within a single search
- Processes all results concurrently with `Promise.all()`

---

## 13. Agent-Facing Tools

Source: `src/agents/tools/memory-tool.ts`

### `memory_search` tool

```typescript
name: "memory_search"
description: "Mandatory recall step: semantically search MEMORY.md + memory/*.md (and optional session transcripts) before answering questions about prior work, decisions, dates, people, preferences, or todos; returns top snippets with path + lines. If response has disabled=true, memory retrieval is unavailable and should be surfaced to the user."
parameters: {
  query: string       // required
  maxResults?: number
  minScore?: number
}
```

**Return type** (JSON):
```typescript
{
  results: Array<{
    path: string;
    startLine: number;
    endLine: number;
    score: number;
    snippet: string;    // up to 700 chars
    source: "memory" | "sessions";
    citation?: string;  // e.g. "memory/2026-03-16.md#L12-L25"
  }>;
  provider: string;
  model?: string;
  fallback?: { from: string; reason?: string };
  citations: "auto" | "on" | "off";
  mode?: string;  // "hybrid" or "fts-only"
}
```

**On error**:
```typescript
{
  results: [],
  disabled: true,
  unavailable: true,
  error: string,
  warning: string,  // human-readable explanation
  action: string    // what to do to fix it
}
```

### `memory_get` tool

```typescript
name: "memory_get"
description: "Safe snippet read from MEMORY.md or memory/*.md with optional from/lines; use after memory_search to pull only the needed lines and keep context small."
parameters: {
  path: string    // required; workspace-relative
  from?: number   // 1-indexed starting line
  lines?: number  // number of lines to return
}
```

**Return type** (JSON):
```typescript
{ text: string; path: string }
// or on error:
{ path: string; text: ""; disabled: true; error: string }
```

### Citations mode

Controlled by `memory.citations` config (`"auto"` | `"on"` | `"off"`). Default: `"auto"`.

- `"auto"`: include citations only in direct (DM) chat sessions; suppress in groups/channels
- `"on"`: always include
- `"off"`: never include

When citations included, snippet is mutated: `snippet = "${snippet.trim()}\n\nSource: ${path}#L${startLine}-L${endLine}"`.

Chat type detection from session key: split by `:`, check for `"channel"` or `"group"` tokens.

### QMD `maxInjectedChars` clamping

For QMD backend only: `clampResultsByInjectedChars(results, resolved.qmd?.limits.maxInjectedChars)` — truncates snippets to fit within a character budget.

### Extension registration (memory-core plugin)

Source: `extensions/memory-core/index.ts`

```typescript
{
  id: "memory-core",
  kind: "memory",
  register(api) {
    api.registerTool((ctx) => {
      const searchTool = api.runtime.tools.createMemorySearchTool({ config, agentSessionKey });
      const getTool = api.runtime.tools.createMemoryGetTool({ config, agentSessionKey });
      return [searchTool, getTool];
    }, { names: ["memory_search", "memory_get"] });
    api.registerCli(({ program }) => api.runtime.tools.registerMemoryCli(program), { commands: ["memory"] });
  }
}
```

Both tools return `null` if memory is not configured for the agent, causing them to be excluded from the agent's tool list.

---

## 14. Pre-Compaction Memory Flush

Source: `src/auto-reply/reply/memory-flush.ts`

### Purpose

When a session approaches the context window limit, OpenClaw triggers a **silent agentic turn** to prompt the model to write important information to disk before compaction erases the context.

### Trigger condition: `shouldRunMemoryFlush()`

```typescript
function shouldRunMemoryFlush(params: {
  entry: Pick<SessionEntry, "totalTokens" | "totalTokensFresh" | "compactionCount" | "memoryFlushCompactionCount">;
  tokenCount?: number;            // override for fresh token count
  contextWindowTokens: number;
  reserveTokensFloor: number;
  softThresholdTokens: number;
}): boolean
```

Trigger threshold formula:
```
threshold = contextWindow - reserveTokensFloor - softThresholdTokens
```

Flush triggers when `totalTokens >= threshold` AND no flush has happened for the current compaction cycle.

**Default values**:
- `softThresholdTokens = 4000` (flush 4000 tokens before `reserveTokensFloor`)
- `forceFlushTranscriptBytes = 2 * 1024 * 1024` (2 MB transcript size also triggers)

**Compaction cycle guard**: `hasAlreadyFlushedForCurrentCompaction()` checks `memoryFlushCompactionCount === compactionCount`. Only one flush per compaction cycle.

### Flush prompts

**Default user prompt** (injected into session):
```
Pre-compaction memory flush. Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed). Treat workspace bootstrap/reference files such as MEMORY.md, SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them. If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries. Do NOT create timestamped variant files (e.g., YYYY-MM-DD-HHMM.md); always use the canonical YYYY-MM-DD.md filename. If nothing to store, reply with NO_REPLY.
```

**Default system prompt**:
```
Pre-compaction memory flush turn. The session is near auto-compaction; capture durable memories to disk. Store durable memories only in memory/YYYY-MM-DD.md. Treat workspace bootstrap/reference files as read-only. If memory/YYYY-MM-DD.md already exists, APPEND only. You may reply, but usually NO_REPLY is correct.
```

Both prompts enforce three required safety hints that are always appended even if custom prompts are provided:
1. `"Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed)."`
2. `"If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite existing entries."`
3. `"Treat workspace bootstrap/reference files such as MEMORY.md, SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them."`

### Date stamp resolution

`resolveMemoryFlushRelativePathForRun()` uses `Intl.DateTimeFormat` with the configured timezone (`agents.defaults.timezone`) to get the correct local date. Falls back to ISO slice if formatting fails.

Result: `"memory/2026-03-16.md"`.

The `YYYY-MM-DD` placeholder in the prompt is replaced with the actual date string.

### Workspace access guard

If the session has `workspaceAccess: "ro"` or `"none"`, the flush is skipped (model cannot write files).

---

## 15. QMD Backend

Source: `src/memory/qmd-manager.ts`

### What is QMD?

QMD (https://github.com/tobi/qmd) is a local-first semantic search sidecar. It runs as a subprocess, maintains its own SQLite index, and uses GGUF models (downloaded on first use) for embeddings and reranking. No separate Ollama daemon required.

### `QmdMemoryManager` construction

```typescript
static async create(params: {
  cfg: OpenClawConfig;
  agentId: string;
  resolved: ResolvedMemoryBackendConfig;
  mode?: "full" | "status";
}): Promise<QmdMemoryManager | null>
```

The manager creates its own isolated XDG home:
```
~/.openclaw/agents/{agentId}/qmd/
  xdg-config/    # QMD_CONFIG_DIR + XDG_CONFIG_HOME
  xdg-cache/
    qmd/
      index.sqlite    # QMD's index DB
      models/         # symlinked from ~/.cache/qmd/models/
  sessions/      # exported session transcripts (if enabled)
```

Environment for QMD subprocess:
```typescript
{
  XDG_CONFIG_HOME: xdgConfigHome,
  QMD_CONFIG_DIR: xdgConfigHome,   // bug workaround: qmd doesn't always respect XDG_CONFIG_HOME
  XDG_CACHE_HOME: xdgCacheHome,
  NO_COLOR: "1",
}
```

Model symlink: on init, symlinks `~/.cache/qmd/models/` into the agent-specific XDG cache so models are shared across agents/collections without re-downloading.

### Collection management

**Managed collection names**: scoped to agent with suffix `-{sanitizedAgentId}`.

Legacy migration: if a collection with the un-scoped name exists at the same path+pattern, remove it and let the new scoped name be created.

**Add collection**:
```bash
qmd collection add {path} --name {name} --mask {pattern}
```

**Remove collection**:
```bash
qmd collection remove {name}
```

**List collections**:
```bash
qmd collection list --json
```
Output is parsed as JSON array of `{ name, path, pattern }` objects. Falls back to line-based parsing if JSON unavailable (older QMD versions).

**Conflict resolution**: if `qmd collection add` fails with "already exists" error, scan listed collections for matching `path+pattern`, remove the conflict, and re-add with the correct name.

**Null-byte repair**: if update fails with ENOTDIR error containing null-byte markers, rebuild all collections once.

**Duplicate document repair**: if update fails with SQLite `UNIQUE constraint failed: documents.collection, documents.path`, rebuild collections once.

### Update/embed scheduling

Controlled by `memory.qmd.update.*`:
- `onBoot: true` — run `qmd update` + `qmd embed` on init (default: background, `waitForBootSync: false`)
- `intervalMs > 0` — periodic `setInterval` for `qmd update` + `qmd embed`
- `embedInterval` — separate interval for just `qmd embed`

**Embed backoff**: when embed fails, `embedBackoffUntil` is set to `now + backoff`. Backoff doubles each failure: `min(QMD_EMBED_BACKOFF_BASE_MS * 2^failures, QMD_EMBED_BACKOFF_MAX_MS)` = min(60s * 2^n, 1 hour).

**Embed queue lock**: `runWithQmdEmbedLock()` ensures only one `qmd embed` runs at a time using a promise-chained queue.

### QMD search execution

```typescript
async search(query: string, opts?: { maxResults?, minScore?, sessionKey? }): Promise<MemorySearchResult[]>
```

1. Check scope (`isQmdScopeAllowed`) — return `[]` if denied
2. Wait for pending update if any (`SEARCH_PENDING_UPDATE_WAIT_MS = 500ms`)
3. Build collection list
4. Choose search path:
   - **MCporter** (`memory.qmd.mcporter.enabled`): use MCP tool interface
   - **Multi-collection**: run search per-collection, merge results
   - **Single collection**: `qmd {searchMode} {query} --json -c {collection} --limit {n}`
5. Parse JSON output with `parseQmdQueryJson(stdout, stderr)`
6. Convert `QmdQueryResult[]` to `MemorySearchResult[]`

**Search mode** (`memory.qmd.searchMode`):
- `"search"` → `qmd search --json`
- `"vsearch"` → `qmd vsearch --json`
- `"query"` → `qmd query --json`

If `searchMode != "query"` and QMD rejects the flags, falls back to `qmd query` automatically.

**Output limit**: `MAX_QMD_OUTPUT_CHARS = 200,000` chars; stdout truncated at this size.

**Han CJK normalization**: queries with CJK characters are tokenized via `extractKeywords()`, then filtered to bigrams+ (unigrams too broad for BM25), joined with spaces, capped at `QMD_BM25_HAN_KEYWORD_LIMIT = 12` keywords.

**Snippet parsing**: QMD returns a `@@` diff-style header like `@@ -42,15` to indicate start line + length. Regex: `/@@\s*-([0-9]+),([0-9]+)/`.

---

## 16. QMD Output Parsing

Source: `src/memory/qmd-query-parser.ts`

### `parseQmdQueryJson(stdout, stderr)`

```typescript
type QmdQueryResult = {
  docid?: string;
  score?: number;
  collection?: string;
  file?: string;
  snippet?: string;
  body?: string;
};
```

**Parse flow**:
1. Check for "no results" marker in stdout or stderr: regex on normalized lines matching `"no results found"` or prefixed with log-level labels
2. If stdout empty: throw error (logged as warning)
3. Try `JSON.parse(trimmedStdout)` — if array, return it
4. If not array: scan for first JSON array using bracket-depth state machine (`extractFirstJsonArray()`) and try parsing that
5. Throw if still not an array

**Null-byte detection**: if `qmd update` or `qmd embed` fails with NUL markers in error (`/(?:\^@|\\0|\\x00|\\u0000|null\s*byte|nul\s*byte)/i`), triggers null-byte repair.

---

## 17. QMD Scope Enforcement

Source: `src/memory/qmd-scope.ts`

### `isQmdScopeAllowed(scope, sessionKey)`

```typescript
type ResolvedQmdScopeRule = {
  action: "allow" | "deny";
  match?: {
    channel?: string;
    chatType?: "channel" | "group" | "direct";
    keyPrefix?: string;    // normalized key prefix (lowercased, `agent:<id>:` stripped)
    rawKeyPrefix?: string; // raw key prefix (lowercased, includes `agent:<id>:`)
  };
}

type ResolvedQmdScope = {
  rules?: ResolvedQmdScopeRule[];
  default?: "allow" | "deny";
}
```

**Evaluation**:
1. If `scope` is null/undefined: allow all
2. Parse session key to extract `{ channel, chatType, normalizedKey, rawKey }`
3. For each rule in `scope.rules`: check all match conditions (all must match if present)
   - `match.channel`: compare to derived channel (e.g., `"telegram"`, `"discord"`)
   - `match.chatType`: `"channel"` | `"group"` | `"direct"`
   - `match.keyPrefix`: compared against normalized key (lowercased, `agent:<id>:` prefix stripped); legacy behavior: if prefix starts with `"agent:"`, compare against raw key
   - `match.rawKeyPrefix`: compared against raw key (lowercased, full key including `agent:<id>:`)
4. First matching rule wins, return `rule.action === "allow"`
5. If no rule matches: `scope.default ?? "allow"`

**Session key parsing**: `parseQmdSessionScope(key)`:
- Strip `agent:<id>:` prefix via `parseAgentSessionKey()`
- Lowercase
- Subagent keys (`"subagent:"` prefix after normalization) → return empty (no scope info)
- Split by `:`, check parts[1] for `"group"` | `"channel"` | `"direct"` | `"dm"`

**Default scope** (QMD config default): deny everything except direct chats.

---

## 18. Embedding Providers and Auto-Selection

Source: `src/memory/embeddings.ts`, provider-specific files

### Auto-selection priority

When `provider = "auto"` or not set:
1. `local` — if `local.modelPath` is configured and file exists
2. `openai` — if OpenAI API key can be resolved
3. `gemini` — if Gemini API key can be resolved
4. `voyage` — if Voyage API key can be resolved
5. `mistral` — if Mistral API key can be resolved
6. Otherwise: provider = `null` (FTS-only mode)

`"ollama"` is never auto-selected — must be explicitly configured.

### Provider interface

```typescript
type EmbeddingProvider = {
  id: "openai" | "local" | "gemini" | "voyage" | "mistral" | "ollama";
  model: string;
  embedQuery(text: string): Promise<number[]>;
  embedBatch(texts: string[]): Promise<number[][]>;
  embedBatchInputs?(inputs: EmbeddingInput[]): Promise<number[][]>;  // multimodal only
}
```

### Default models

| Provider | Default model |
|----------|---------------|
| OpenAI | `text-embedding-3-small` |
| Gemini | `gemini-embedding-001` |
| Voyage | (no default shown) |
| Mistral | (no default shown) |
| Ollama | (no default shown) |
| Local | `hf:ggml-org/embeddinggemma-300m-qat-q8_0-GGUF/embeddinggemma-300m-qat-Q8_0.gguf` (~0.6 GB) |

### FTS-only mode

When no provider is available, `this.provider = null`. In this mode:
- Embedding and vector search are skipped entirely
- FTS5 keyword search still works (searches all models, not filtered by current model)
- `indexFile()` is a no-op
- `probeEmbeddingAvailability()` returns `{ ok: false, error: "No embedding provider available (FTS-only mode)" }`
- Search falls back to keyword extraction + multi-term FTS search

### Fallback provider

`settings.fallback` specifies which provider to fall back to if the primary fails. If fallback activates during a sync, `runSafeReindex()` is triggered with the fallback provider to rebuild the index from scratch.

---

## 19. Readonly Recovery

Source: `src/memory/manager.ts`

When a sync fails with SQLite readonly error:
```
/(attempt to write a readonly database|database is read-only|SQLITE_READONLY)/i
```

Recovery steps:
1. `db.close()`
2. `db = openDatabase()` — reopen the SQLite connection
3. `vectorReady = null; vector.available = null; vector.loadError = undefined`
4. `ensureSchema()` — recreate tables if needed
5. Retry `runSync()` once

Tracked metrics: `readonlyRecoveryAttempts`, `readonlyRecoverySuccesses`, `readonlyRecoveryFailures`, `readonlyRecoveryLastError` — exposed via `status()`.

---

## 20. Multimodal Memory

Source: `src/memory/internal.ts`, `src/memory/multimodal.ts`

### Supported modalities

When `memorySearch.multimodal.enabled = true`:
- **Image**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.heic`, `.heif`
- **Audio**: `.mp3`, `.wav`, `.ogg`, `.opus`, `.m4a`, `.aac`, `.flac`

Only applies to files discovered through `extraPaths`. Default memory roots (`MEMORY.md`, `memory/**/*.md`) are Markdown-only.

### Multimodal file entry

`buildFileEntry()` for multimodal files:
1. Detect MIME type from first 512 bytes
2. Validate MIME starts with `"{modality}/"` (e.g., `"image/"`)
3. Compute `dataHash = SHA-256(fileBuffer)`
4. Generate text label via `buildMemoryMultimodalLabel(modality, path)`
5. Compute chunk hash: `SHA-256(JSON.stringify({ path, contentText, mimeType, dataHash }))`
6. Return `MemoryFileEntry` with `kind = "multimodal"`

### Multimodal embedding

`buildMultimodalChunkForIndexing(entry)` creates a single chunk:
```typescript
{
  chunk: {
    startLine: 1,
    endLine: 1,
    text: entry.contentText,   // text label for the file
    hash: entry.hash,
    embeddingInput: {
      text: contentText,
      parts: [
        { type: "text", text: contentText },
        { type: "inline-data", mimeType, data: base64Buffer }
      ]
    }
  },
  structuredInputBytes: estimateStructuredEmbeddingInputBytes(embeddingInput)
}
```

Only providers supporting `embedBatchInputs()` (currently Gemini) can embed multimodal chunks.

If the multimodal chunk is rejected as too large (413/payload-too-large errors), the file is recorded in `files` table but no chunks are written — prevents repeated retry.

---

## 21. Configuration Reference

All settings under `agents.defaults.memorySearch` (not top-level `memorySearch`).

### Top-level switches

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.provider` | `"auto"` | `"openai"` \| `"gemini"` \| `"voyage"` \| `"mistral"` \| `"ollama"` \| `"local"` \| `"auto"` |
| `memorySearch.model` | provider default | Override model name |
| `memorySearch.outputDimensionality` | — | Gemini: 768/1536/3072 |
| `memorySearch.fallback` | — | Fallback provider on primary failure |

### Chunking

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.chunking.tokens` | 400 | Target chunk size in tokens (1 token ≈ 4 chars) |
| `memorySearch.chunking.overlap` | 80 | Overlap in tokens |

### Hybrid search

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.query.hybrid.enabled` | true | Enable BM25+vector hybrid |
| `memorySearch.query.hybrid.vectorWeight` | 0.7 | Weight for vector scores |
| `memorySearch.query.hybrid.textWeight` | 0.3 | Weight for BM25 scores |
| `memorySearch.query.hybrid.candidateMultiplier` | 4 | `candidates = min(200, maxResults * this)` |
| `memorySearch.query.hybrid.mmr.enabled` | false | MMR diversity re-ranking |
| `memorySearch.query.hybrid.mmr.lambda` | 0.7 | 0=max diversity, 1=max relevance |
| `memorySearch.query.hybrid.temporalDecay.enabled` | false | Recency boost |
| `memorySearch.query.hybrid.temporalDecay.halfLifeDays` | 30 | Score halves every N days |
| `memorySearch.query.minScore` | 0.0 | Minimum score threshold |
| `memorySearch.query.maxResults` | 5 | Maximum results |

### Storage

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.store.path` | `~/.openclaw/memory/{agentId}.sqlite` | SQLite path |
| `memorySearch.store.vector.enabled` | true | Enable sqlite-vec extension |
| `memorySearch.store.vector.extensionPath` | bundled | Override sqlite-vec path |

### Cache

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.cache.enabled` | — | Cache chunk embeddings in SQLite |
| `memorySearch.cache.maxEntries` | — | LRU eviction limit |

### Sync

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.sync.watch` | true | File watcher |
| `memorySearch.sync.watchDebounceMs` | 1500 | Watcher debounce |
| `memorySearch.sync.onSearch` | — | Sync when dirty before search |
| `memorySearch.sync.onSessionStart` | — | Sync on new session |
| `memorySearch.sync.intervalMinutes` | — | Periodic sync interval |
| `memorySearch.sync.sessions.deltaBytes` | 100000 | Session sync byte threshold |
| `memorySearch.sync.sessions.deltaMessages` | 50 | Session sync message threshold |

### Remote/batch

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.remote.apiKey` | — | Override API key |
| `memorySearch.remote.baseUrl` | — | Override base URL |
| `memorySearch.remote.headers` | — | Extra request headers |
| `memorySearch.remote.batch.enabled` | false | Batch embedding API |
| `memorySearch.remote.batch.wait` | true | Wait for batch completion |
| `memorySearch.remote.batch.concurrency` | 2 | Parallel batch jobs |
| `memorySearch.remote.batch.pollIntervalMs` | — | Poll interval |
| `memorySearch.remote.batch.timeoutMinutes` | — | Batch timeout |

### Sources and extra paths

| Config | Default | Description |
|--------|---------|-------------|
| `memorySearch.sources` | `["memory"]` | `"memory"` and/or `"sessions"` |
| `memorySearch.extraPaths` | `[]` | Additional file/dir paths to index |
| `memorySearch.experimental.sessionMemory` | false | Enable session indexing |

### Pre-compaction flush

| Config | Default | Description |
|--------|---------|-------------|
| `agents.defaults.compaction.memoryFlush.enabled` | true | Enable pre-compaction flush |
| `agents.defaults.compaction.memoryFlush.softThresholdTokens` | 4000 | Flush this many tokens before `reserveTokensFloor` |
| `agents.defaults.compaction.memoryFlush.forceFlushTranscriptBytes` | 2097152 | Also flush if transcript exceeds this size |
| `agents.defaults.compaction.memoryFlush.prompt` | (see above) | User message for flush turn |
| `agents.defaults.compaction.memoryFlush.systemPrompt` | (see above) | System message for flush turn |
| `agents.defaults.compaction.reserveTokensFloor` | (from pi-settings) | Tokens reserved for compaction |

---

## 22. Key Constants Summary

| Constant | Value | Location |
|----------|-------|----------|
| `SNIPPET_MAX_CHARS` | 700 | manager.ts |
| `VECTOR_TABLE` | `"chunks_vec"` | manager.ts |
| `FTS_TABLE` | `"chunks_fts"` | manager.ts |
| `EMBEDDING_CACHE_TABLE` | `"embedding_cache"` | manager.ts |
| `BATCH_FAILURE_LIMIT` | 2 | manager-embedding-ops.ts |
| `EMBEDDING_BATCH_MAX_TOKENS` | 8000 | manager-embedding-ops.ts |
| `EMBEDDING_INDEX_CONCURRENCY` | 4 | manager-embedding-ops.ts |
| `EMBEDDING_RETRY_MAX_ATTEMPTS` | 3 | manager-embedding-ops.ts |
| `EMBEDDING_RETRY_BASE_DELAY_MS` | 500 | manager-embedding-ops.ts |
| `EMBEDDING_RETRY_MAX_DELAY_MS` | 8000 | manager-embedding-ops.ts |
| `EMBEDDING_QUERY_TIMEOUT_REMOTE_MS` | 60,000 | manager-embedding-ops.ts |
| `EMBEDDING_QUERY_TIMEOUT_LOCAL_MS` | 300,000 | manager-embedding-ops.ts |
| `EMBEDDING_BATCH_TIMEOUT_REMOTE_MS` | 120,000 | manager-embedding-ops.ts |
| `EMBEDDING_BATCH_TIMEOUT_LOCAL_MS` | 600,000 | manager-embedding-ops.ts |
| `SESSION_DIRTY_DEBOUNCE_MS` | 5,000 | manager-sync-ops.ts |
| `SESSION_DELTA_READ_CHUNK_BYTES` | 65,536 (64 KB) | manager-sync-ops.ts |
| `VECTOR_LOAD_TIMEOUT_MS` | 30,000 | manager-sync-ops.ts |
| `META_KEY` | `"memory_index_meta_v1"` | manager-sync-ops.ts |
| `MAX_QMD_OUTPUT_CHARS` | 200,000 | qmd-manager.ts |
| `SEARCH_PENDING_UPDATE_WAIT_MS` | 500 | qmd-manager.ts |
| `QMD_EMBED_BACKOFF_BASE_MS` | 60,000 | qmd-manager.ts |
| `QMD_EMBED_BACKOFF_MAX_MS` | 3,600,000 (1 hour) | qmd-manager.ts |
| `QMD_BM25_HAN_KEYWORD_LIMIT` | 12 | qmd-manager.ts |
| `DEFAULT_MEMORY_FLUSH_SOFT_TOKENS` | 4,000 | memory-flush.ts |
| `DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES` | 2,097,152 (2 MB) | memory-flush.ts |
| `DEFAULT_MMR_CONFIG.lambda` | 0.7 | mmr.ts |
| `DEFAULT_TEMPORAL_DECAY_CONFIG.halfLifeDays` | 30 | temporal-decay.ts |

---

## 23. Relevance to sbot

Key patterns from OpenClaw's memory system that apply to sbot:

**File-first design**: MEMORY.md as canonical source, index as derived. sbot already writes `MEMORY.md` via `compact_with_llm`. This is the right mental model.

**Chunking**: 400 tokens / 80 overlap, `~1600 chars / ~320 chars overlap`. The `tokens * 4` heuristic is a pragmatic approximation for UTF-8 text.

**Cache key format**: `(provider_id, model_name, provider_key_hash, chunk_text_hash)`. The `provider_key_hash` captures endpoint config changes that would invalidate cached embeddings.

**Pre-compaction flush trigger formula**: `threshold = contextWindow - reserveTokensFloor - softThresholdTokens`. Guard with a per-compaction-cycle counter so it only fires once.

**Session delta thresholds**: Only re-index a session file after it accumulates 100 KB of new data or 50 new messages. Avoids thrashing the embedding API on every message.

**Hybrid search fallback**: if minScore filters out all results but keyword-only results exist, relax the threshold to `min(minScore, textWeight)`. Important correctness edge case.

**FTS-only mode**: always handle the case where no embedding provider is available. BM25 alone is useful and shouldn't be blocked by API setup.

**Scope enforcement for memory**: use session key structure to decide what memory to show. Group/channel sessions get denied by default to prevent personal memory leakage.

**Singleton manager per config**: use a module-level cache keyed by `agentId + settings hash`. Prevents duplicate DB connections, duplicate watchers, duplicate timers.

**Chunk ID stability**: `SHA-256(source:path:startLine:endLine:chunkHash:model)` — chunk IDs are deterministic and stable across syncs. Unchanged chunks skip re-embedding.

**Full reindex trigger conditions**: model change, provider change, endpoint fingerprint change, sources change, extra paths change, chunking config change. Always detect these and rebuild from scratch.
