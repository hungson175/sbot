# Module 08 — Real-World Patterns

**When you're ready:** After Module 07 (sync primitives).

These are the patterns used in production concurrent systems.

## What You'll Build

| Notebook | Exercise |
|----------|----------|
| `00_producer_consumer.ipynb` | Multi-producer, multi-consumer with bounded queue (backpressure) |
| `01_worker_pool.ipynb` | Bounded async worker pool with graceful shutdown and error handling |
| `02_pipeline.ipynb` | Multi-stage async pipeline: fetch → parse → store (like sbot's message flow) |
| `03_connection_pool.ipynb` | **Build a reusable async connection pool** with checkout/checkin, max size, health checks |
| `04_retry_circuit_breaker.ipynb` | Retry with exponential backoff + jitter, circuit breaker pattern |

## Key Patterns

1. **Backpressure** — when producers are faster than consumers, use bounded queues to slow producers down
2. **Worker pool** — fixed number of concurrent workers processing from a queue
3. **Pipeline** — chain of stages, each running concurrently (like Unix pipes but async)
4. **Connection pool** — reuse expensive connections (DB, HTTP) across many coroutines
5. **Circuit breaker** — stop calling a failing service, allow recovery

## Mastery Test

Build a web scraper pipeline:
- Stage 1: URL queue → fetch (max 5 concurrent HTTP requests)
- Stage 2: Parse HTML → extract links + data
- Stage 3: Store results to SQLite
- Connection pool for HTTP
- Rate limiting (2 req/sec per domain)
- Circuit breaker (skip domain after 3 consecutive failures)
- Process 1000 pages, handle errors gracefully
