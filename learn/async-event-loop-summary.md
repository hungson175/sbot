# Async & Event Loop — Summary & Resources

Companion to `01_concurrency_python/01_why_async.ipynb`. Key concepts + where to go deeper.

---

## 1. Key Concepts

### Blocking vs async

| | `time.sleep(3)` | `await asyncio.sleep(3)` |
|---|----------------|---------------------------|
| Block thread? | Yes — function holds thread until done | No — yields to event loop |
| Can run other tasks? | No (single-threaded) | Yes — event loop runs others |
| Total for 2 tasks (3s + 2s) | 5s sequential | ~3s (max of both) |

### Coroutine

- Function defined with `async def`
- Calling it does **not** run it — returns a coroutine object
- Execution only happens when `await`ed or scheduled by the event loop

### Awaitable

- Any object that can be used with `await`
- Must implement `__await__()`
- Common types: **coroutine**, **Task**, **Future**
- Examples: `asyncio.sleep()`, `my_async_func()` — both return awaitables
- Non-examples: `time.sleep()` returns `None`, not awaitable

### `await asyncio.sleep(0)`

- Yields control to the event loop immediately
- No real wait — “pause me here, run others, then resume me”
- Idiomatic way to create a voluntary yield point
- `time.sleep(0)` cannot be awaited — it’s blocking and not awaitable

### Event loop internals (simplified)

```
┌─────────────────────────────────────────────────────────────────┐
│ READY QUEUE (deque) — coroutines ready to run                     │
├─────────────────────────────────────────────────────────────────┤
│ SCHEDULED TIMERS (heap) — "at time T, put coro X in ready"       │
├─────────────────────────────────────────────────────────────────┤
│ I/O POLL (select/epoll) — sockets ready → resume waiting coros   │
└─────────────────────────────────────────────────────────────────┘
```

**`await asyncio.sleep(3)`:**

1. Coroutine yields
2. Event loop registers a timer: “in 3s, put this coro in ready queue”
3. Event loop runs other ready coroutines
4. When the timer fires, the coroutine is resumed

### Cooperative multitasking

- Task switch happens **only** at `await` points
- Between two `await`s, a coroutine runs without interruption
- Heavy CPU work without `await` freezes everything

---

## 2. GIL and threads

- **GIL** (Global Interpreter Lock): only one Python thread executes bytecode at a time
- During I/O or `time.sleep()`, the thread releases the GIL → other threads can run
- **I/O-bound**: threading can help (GIL is released during I/O)
- **CPU-bound**: GIL limits parallelism → use `multiprocessing`
- **asyncio**: single thread, no GIL contention

---

## 3. Implementing from Scratch

Guides that build an event loop and async-like behavior in Python:

### Recommended order

| Step | Resource | Focus |
|------|----------|--------|
| 1 | **David Beazley — A Curious Course on Coroutines and Concurrency** | Generators (`yield`, `send`, `yield from`) as foundation |
| 2 | **Bolu** or **Jacob Padilla** | Map to `async`/`await` and asyncio-style event loop |
| 3 | **PlainEnglish** | Ready queue and scheduling via full implementation |

### Links

1. **David Beazley — A Curious Course on Coroutines and Concurrency** (Classic)
   - https://www.dabeaz.com/coroutines/
   - Builds event loop from generators (no `async`/`await`)
   - PyCon 2009 material

2. **Let's build an asyncio runtime from scratch** (Bolu)
   - https://bolu.dev/python/programming/2024/05/23/asyncio-from-scratch.html

3. **How Python Asyncio Works: Recreating it from Scratch** (Jacob Padilla)
   - https://jacobpadilla.com/articles/recreating-asyncio

4. **Build Your Own Event Loop from Scratch** (PlainEnglish)
   - https://python.plainenglish.io/build-your-own-event-loop-from-scratch-in-python-da77ef1e3c39
   - Task queue, scheduling, I/O handling

5. **Micro event loop** (Gist)
   - https://gist.github.com/tarruda/5b8c19779c8ff4e8100f0b37eb5981ea
   - Compact educational implementation

---

## 4. One-line takeaways

- **Coroutine** = `async def`, callable that yields
- **Awaitable** = object with `__await__()`
- **`await`** = voluntary yield point — event loop can switch here
- **Event loop** = ready queue + timers + I/O poll
- **Cooperative** = tasks yield; no preemption
