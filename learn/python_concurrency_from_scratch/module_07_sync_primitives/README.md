# Module 07 — Synchronization Primitives

**When you're ready:** After Module 06 (asyncio mastery).

Build each primitive from scratch to understand why it exists.

## What You'll Build

| Notebook | Exercise |
|----------|----------|
| `00_the_need.ipynb` | Break things first — show race conditions WITHIN async code (yield between read and write) |
| `01_build_lock.ipynb` | **Build `asyncio.Lock`** from scratch using a deque of waiting coroutines |
| `02_build_semaphore.ipynb` | **Build `asyncio.Semaphore`** — Lock + counter |
| `03_build_event.ipynb` | **Build `asyncio.Event`** — flag + waiters list |
| `04_build_condition.ipynb` | **Build `asyncio.Condition`** — Lock + Event (wait/notify) |
| `05_build_rate_limiter.ipynb` | **Token bucket rate limiter** using your Semaphore |

## Key Insight

Asyncio code is safe between `await` points. But if you read a variable, `await` something, then write based on the old value — that's a race condition even in async code.

```python
# RACE CONDITION in async:
balance = await get_balance()    # read
await asyncio.sleep(0)           # yield — another coroutine might change balance!
await set_balance(balance + 10)  # write stale value
```

## Mastery Test

Rate limiter that enforces 10 requests/second across 100 concurrent coroutines. Must be fair (FIFO), accurate (no bursts beyond limit), and efficient (no busy-waiting).
