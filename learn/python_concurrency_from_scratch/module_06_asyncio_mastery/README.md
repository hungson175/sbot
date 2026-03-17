# Module 06 — asyncio Mastery

**When you're ready:** After Module 05 (you've built your own event loop).

Now asyncio isn't magic — it's the polished version of what you built.

## What You'll Build

| Notebook | Exercise |
|----------|----------|
| `00_tasks_vs_coroutines.ipynb` | `create_task` vs `await` vs `gather` vs `TaskGroup` — when to use which |
| `01_error_handling.ipynb` | Exception propagation in tasks, `shield()`, cancellation, `asyncio.timeout()` |
| `02_streams.ipynb` | TCP server/client with `asyncio.open_connection`, `StreamReader/Writer` |
| `03_subprocess.ipynb` | `asyncio.create_subprocess_exec()`, pipe communication |
| `04_build_chat_server.ipynb` | **Build a concurrent TCP chat server** — handles 50 clients, broadcast, graceful shutdown |

## Key Concepts

- `TaskGroup` (Python 3.11+) — structured concurrency, auto-cancels on error
- `asyncio.timeout()` — context manager for timeouts
- `asyncio.shield()` — protect a coroutine from cancellation
- `asyncio.to_thread()` — run sync functions in thread pool
- Streams API — high-level TCP without raw sockets

## Mastery Test

A TCP chat server where:
- Clients connect, choose a username
- Messages broadcast to all connected clients
- Handles 50 simultaneous clients
- Graceful shutdown (SIGINT → notify clients → close)
- `/kick`, `/list`, `/dm` commands
