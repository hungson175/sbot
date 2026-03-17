# Module 05 — Build Your Own Event Loop ⭐

**THE key module.** After this, asyncio makes complete sense.

## What You'll Build

| Notebook | What You Build |
|----------|---------------|
| `00_callback_loop.ipynb` ✅ | Callback queue + `call_soon` + `call_later` with timer heap |
| `01_coroutine_loop.ipynb` ✅ | Task class + coroutine driving via `.send()` + `await sleep()` |
| `02_add_io.ipynb` | Add `select()`-based I/O polling — `await sock_recv()`, `await sock_send()` |
| `03_add_tasks.ipynb` | Full `Task` with result, exception, cancellation, `gather()` |
| `04_full_loop.ipynb` | **Complete event loop**: tasks + I/O + timers + gather + run() |

## Key Resources

- [David Beazley — Curious Course on Coroutines](https://www.dabeaz.com/coroutines/)
- [bolu.dev — asyncio from scratch](https://bolu.dev/python/programming/2024/05/23/asyncio-from-scratch.html)
- [Jacob Padilla — Recreating asyncio](https://jacobpadilla.com/articles/recreating-asyncio)
- [PlainEnglish — Build Event Loop from Scratch](https://python.plainenglish.io/build-your-own-event-loop-from-scratch-in-python-da77ef1e3c39)

## Mastery Test

Your event loop runs a concurrent HTTP client fetching 10 URLs simultaneously using raw sockets + your I/O polling. No asyncio, no aiohttp — just your loop + `select()`.
