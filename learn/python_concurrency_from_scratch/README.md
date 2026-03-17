# Python Concurrency From Scratch — Master Plan

**Philosophy:** "I can't understand what I can't build."
Every module ends with you BUILDING something from scratch that proves you understand the concept.

**Format:** Jupyter notebooks with exercises, questions, and build challenges.
**Time estimate:** ~40–60 hours across all modules. No rush — depth over speed.

---

## The Map

```
Module 00: Iterators & Generators          ← The DNA of everything async
Module 01: Generators as Coroutines        ← yield + send = cooperative tasks (Beazley style)
Module 02: Threading                       ← OS threads, GIL, real concurrency
Module 03: Multiprocessing                 ← True parallelism, escape the GIL
Module 04: concurrent.futures              ← The unified API (ThreadPool + ProcessPool)
Module 05: Build Your Own Event Loop       ← THE key module — build asyncio from scratch
Module 06: asyncio Mastery                 ← Now you UNDERSTAND what asyncio does under the hood
Module 07: Synchronization Primitives      ← Locks, semaphores, events, conditions
Module 08: Real-World Patterns             ← Rate limiter, connection pool, pipeline, backpressure
Module 09: Capstone — Mini-asyncio         ← Build a working async runtime with tasks, sleep, gather
```

## Why This Order?

```
Generators → Coroutines → "I can build a scheduler with yield"
    ↓
Threading → Multiprocessing → "I know what OS-level concurrency looks like"
    ↓
Build Event Loop → "Holy shit, asyncio is just a while-loop + generators"
    ↓
asyncio Deep Dive → "Now I GET why await works this way"
    ↓
Sync Primitives + Patterns → "I can build production-grade concurrent systems"
    ↓
Capstone → "I built my own asyncio. I own this."
```

---

## Module Details

### Module 00 — Iterators & Generators (3–4 hours)
**Why first:** Generators ARE coroutines. `async/await` is syntactic sugar over `yield`. You can't understand async without understanding generators deeply.

| Notebook | What You Build |
|----------|---------------|
| `00_iterators.ipynb` | Your own `range()`, `enumerate()`, `zip()` from scratch |
| `01_generators.ipynb` | Lazy file reader, infinite sequences, generator pipelines |
| `02_generator_pipelines.ipynb` | Unix-pipe-style data pipeline: `grep | count | top_n` |

**Mastery test:** Build a lazy CSV processor that handles a 1GB file with constant memory.

---

### Module 01 — Generators as Coroutines (4–5 hours)
**Why:** This is the bridge between generators and async. David Beazley's key insight: generators can RECEIVE data with `.send()`, making them coroutines.

| Notebook | What You Build |
|----------|---------------|
| `00_yield_send.ipynb` | Coroutines that receive data: running average, state machine |
| `01_yield_from.ipynb` | Delegation with `yield from`, sub-coroutines |
| `02_scheduler.ipynb` | **A cooperative task scheduler using only generators** (no asyncio!) |
| `03_async_await_desugared.ipynb` | Show that `async def` / `await` = `yield from` + magic |

**Mastery test:** Your scheduler runs 1000 "tasks" concurrently on a single thread.

---

### Module 02 — Threading (4–5 hours)
**Why:** You need to understand OS-level concurrency to appreciate WHY asyncio exists (and when threads are actually better).

| Notebook | What You Build |
|----------|---------------|
| `00_threads_basics.ipynb` | Spawn threads, join, daemon threads, thread lifecycle |
| `01_shared_state_bugs.ipynb` | Race conditions live — break a counter, see the chaos |
| `02_thread_safety.ipynb` | Fix with Lock, RLock, see deadlock happen |
| `03_build_thread_pool.ipynb` | **Build your own ThreadPoolExecutor from scratch** |

**Mastery test:** Your thread pool handles 100 concurrent downloads correctly.

---

### Module 03 — Multiprocessing (3–4 hours)
**Why:** When threads can't help (CPU-bound work + GIL), processes are the answer.

| Notebook | What You Build |
|----------|---------------|
| `00_processes_vs_threads.ipynb` | Side-by-side: GIL effect on CPU-bound vs I/O-bound |
| `01_ipc.ipynb` | Pipes, Queues, shared memory between processes |
| `02_build_process_pool.ipynb` | **Build your own ProcessPoolExecutor** |

**Mastery test:** Parallel image resizer — 4x speedup on 4 cores.

---

### Module 04 — concurrent.futures (2–3 hours)
**Why:** The standard library's clean abstraction over threads AND processes.

| Notebook | What You Build |
|----------|---------------|
| `00_futures.ipynb` | What IS a Future? Build one from scratch |
| `01_executors.ipynb` | `map()`, `submit()`, `as_completed()`, exception handling |
| `02_build_future.ipynb` | **Build your own Future class with callbacks** |

**Mastery test:** Your Future supports `.result()`, `.add_done_callback()`, `.cancel()`.

---

### Module 05 — Build Your Own Event Loop (6–8 hours) ⭐ THE KEY MODULE
**Why:** This is where everything clicks. You build asyncio from scratch, so you KNOW what it does.

| Notebook | What You Build |
|----------|---------------|
| `00_callback_loop.ipynb` | Simplest event loop: callback queue + `call_later()` |
| `01_coroutine_loop.ipynb` | Event loop that runs generator-coroutines |
| `02_add_io.ipynb` | Add `select()`-based I/O polling to the loop |
| `03_add_sleep.ipynb` | Add timer heap for `sleep()` |
| `04_add_tasks.ipynb` | Add `Task` wrapper, `gather()` |
| `05_full_loop.ipynb` | **Complete event loop: tasks + I/O + timers + gather** |

**Mastery test:** Your event loop runs a concurrent HTTP client that fetches 10 URLs simultaneously.

**Key resources:**
- [David Beazley — Curious Course on Coroutines](https://www.dabeaz.com/coroutines/)
- [bolu.dev — asyncio from scratch](https://bolu.dev/python/programming/2024/05/23/asyncio-from-scratch.html)
- [Jacob Padilla — Recreating asyncio](https://jacobpadilla.com/articles/recreating-asyncio)

---

### Module 06 — asyncio Mastery (4–5 hours)
**Why:** Now that you've BUILT an event loop, asyncio's API makes perfect sense.

| Notebook | What You Build |
|----------|---------------|
| `00_tasks_vs_coroutines.ipynb` | `create_task` vs `await` vs `gather` vs `TaskGroup` |
| `01_error_handling.ipynb` | Exception propagation, `shield()`, cancellation |
| `02_streams.ipynb` | TCP server/client with `asyncio.open_connection` |
| `03_subprocess.ipynb` | Async subprocess management |
| `04_build_chat_server.ipynb` | **Build a concurrent TCP chat server** |

**Mastery test:** Chat server handles 50 simultaneous clients, graceful shutdown.

---

### Module 07 — Synchronization Primitives (3–4 hours)
**Why:** Concurrency without synchronization = data corruption. Build each primitive to understand why it exists.

| Notebook | What You Build |
|----------|---------------|
| `00_the_need.ipynb` | Break things first — show WHY you need sync primitives |
| `01_build_lock.ipynb` | **Build asyncio.Lock from scratch** (using a deque) |
| `02_build_semaphore.ipynb` | **Build asyncio.Semaphore** (Lock + counter) |
| `03_build_event.ipynb` | **Build asyncio.Event** (flag + waiters list) |
| `04_build_condition.ipynb` | **Build asyncio.Condition** (Lock + Event) |
| `05_build_rate_limiter.ipynb` | **Token bucket rate limiter using your Semaphore** |

**Mastery test:** Rate limiter that enforces 10 req/sec across 100 concurrent tasks.

---

### Module 08 — Real-World Patterns (4–5 hours)
**Why:** These are the patterns you'll use in production. Each one is a design problem.

| Notebook | What You Build |
|----------|---------------|
| `00_producer_consumer.ipynb` | Multi-producer multi-consumer with backpressure |
| `01_worker_pool.ipynb` | Bounded worker pool with graceful shutdown |
| `02_pipeline.ipynb` | Multi-stage async pipeline (fetch → parse → store) |
| `03_connection_pool.ipynb` | **Build a reusable async connection pool** |
| `04_retry_circuit_breaker.ipynb` | Retry with exponential backoff + circuit breaker |

**Mastery test:** A web scraper pipeline that fetches → parses → stores 1000 pages with connection pooling, rate limiting, and circuit breakers.

---

### Module 09 — Capstone: Mini-asyncio (6–8 hours) ⭐
**Why:** You prove you own Python concurrency by building a working async runtime.

**Build:** `miniasync` — a ~300-line async runtime that supports:
- `async def` / `await` (via generators internally)
- `miniasync.run()` — bootstrap the event loop
- `miniasync.sleep(seconds)` — timer-based sleep
- `miniasync.create_task()` — schedule a coroutine as a task
- `miniasync.gather()` — wait for multiple tasks
- `miniasync.Queue()` — async producer/consumer queue
- I/O polling — async socket read/write

**Test it by running a concurrent TCP echo server on YOUR runtime.**

---

## How to Use This

1. **Go in order.** Each module builds on the previous one.
2. **Run every cell.** Don't just read — predict the output, then verify.
3. **Answer every question** before looking at the explanation.
4. **Build every "mastery test"** — that's how you know you actually understand.
5. **When stuck:** Read the code you built in earlier modules. The answer is usually there.

## Prerequisites

- Basic Python (functions, classes, loops, decorators)
- Jupyter: `pip install jupyter`
- That's it. Everything else is built from scratch.

## What You Already Know (from 01_concurrency_python/)

Your existing notebooks cover asyncio usage (why async, event loop basics, Queue, create_task, the sbot bug). This plan goes DEEPER — you'll understand the machinery underneath.

After this plan, your existing notebooks will feel like "oh, that's just the surface."
