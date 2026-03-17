# Module 09 — Capstone: Build Mini-asyncio

**The final boss.** Build a working async runtime from scratch.

## What You'll Build

A ~300-line async runtime called `miniasync` that supports:

```python
import miniasync

async def main():
    # Create tasks
    t1 = miniasync.create_task(worker("A"))
    t2 = miniasync.create_task(worker("B"))

    # Gather results
    results = await miniasync.gather(t1, t2)

    # Use a queue
    q = miniasync.Queue()
    await q.put("hello")
    item = await q.get()

    # Sleep
    await miniasync.sleep(1)

    # I/O: async socket operations
    reader, writer = await miniasync.open_connection("example.com", 80)
    writer.write(b"GET / HTTP/1.0\r\n\r\n")
    data = await reader.read(1024)

miniasync.run(main())
```

## Components to Build

| Component | Description |
|-----------|-------------|
| `EventLoop` | Ready queue + timer heap + I/O poll (select) |
| `Task` | Wraps coroutine, drives with `.send()`, tracks completion |
| `Future` | Result placeholder, supports `await` |
| `sleep(seconds)` | Timer-based suspension |
| `create_task(coro)` | Schedule coroutine |
| `gather(*coros)` | Wait for multiple tasks |
| `Queue` | Async producer/consumer queue |
| `Lock` / `Semaphore` | Sync primitives |
| I/O layer | `select()`-based socket read/write |
| `run(coro)` | Bootstrap the event loop |

## Validation

Test your runtime by running a concurrent TCP echo server:

```python
async def handle_client(reader, writer):
    data = await reader.read(1024)
    writer.write(data)

async def server():
    # Accept connections, spawn handler for each
    ...

miniasync.run(server())
```

If 10 clients can connect simultaneously and each gets their echo response concurrently — you've built a working async runtime.

## You Made It

After this module, you can truthfully say: "I understand Python concurrency because I built it from scratch."

```
Module 00: I built iterators         → I understand lazy evaluation
Module 01: I built a scheduler       → I understand cooperative multitasking
Module 02: I built a thread pool     → I understand OS threads and the GIL
Module 03: I built a process pool    → I understand true parallelism
Module 04: I built Future            → I understand result placeholders
Module 05: I built an event loop     → I understand asyncio's core
Module 06: I mastered asyncio        → I can use it fluently
Module 07: I built sync primitives   → I understand coordination
Module 08: I built real patterns     → I can design concurrent systems
Module 09: I built mini-asyncio      → I OWN this.
```
