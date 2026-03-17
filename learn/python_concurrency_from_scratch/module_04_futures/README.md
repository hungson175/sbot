# Module 04 — concurrent.futures: The Unified API

**When you're ready:** After completing Module 03 (Multiprocessing).

## What You'll Build

| Notebook | Exercise |
|----------|----------|
| `00_futures.ipynb` | What IS a Future? Inspect it, understand states (pending → running → done) |
| `01_executors.ipynb` | `ThreadPoolExecutor` + `ProcessPoolExecutor`: `submit()`, `map()`, `as_completed()` |
| `02_build_future.ipynb` | **Build your own Future class** with `.result()`, `.add_done_callback()`, `.cancel()`, `.exception()` |

## Key Concepts

- `Future` = a placeholder for a result that isn't ready yet
- `Executor.submit(fn, *args)` → returns Future immediately
- `future.result()` → blocks until result is available
- `as_completed(futures)` → yields futures as they complete (fastest first)
- `future.add_done_callback(fn)` → called when future completes

## Mastery Test

Build a complete Future class that:
1. Supports `.result(timeout=)`, `.exception()`, `.cancel()`, `.cancelled()`
2. Supports `.add_done_callback(fn)` — multiple callbacks
3. Is thread-safe (uses Lock internally)
4. Passes the same tests as `concurrent.futures.Future`

## Connection to asyncio

`asyncio.Future` is almost identical to `concurrent.futures.Future` — but works with `await` instead of `.result()`.
```python
# concurrent.futures:
future = executor.submit(fn)
result = future.result()  # blocks thread

# asyncio:
future = loop.create_future()
result = await future  # suspends coroutine (non-blocking)
```
