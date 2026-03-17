# Module 03 — Multiprocessing: True Parallelism

**When you're ready:** After completing Module 02 (Threading).

## What You'll Build

| Notebook | Exercise |
|----------|----------|
| `00_processes_vs_threads.ipynb` | CPU-bound benchmark: threads (GIL) vs processes (true parallel) |
| `01_ipc.ipynb` | Inter-Process Communication: Pipe, Queue, shared memory, Manager |
| `02_build_process_pool.ipynb` | **Build your own ProcessPoolExecutor** using `multiprocessing.Process` + `Queue` |

## Key Concepts

- Processes have SEPARATE memory spaces (no GIL, no shared state by default)
- IPC is required to communicate between processes
- Serialization overhead (pickle) — can't share arbitrary objects
- `multiprocessing.Pool` / `ProcessPoolExecutor` — the standard abstractions

## Mastery Test

Build a parallel image resizer:
- Read 20 large images
- Resize each in a separate process
- Demonstrate ~4x speedup on 4 cores
- Compare with threading (should be ~1x for CPU-bound work)

## Key Insight

```
Threads: shared memory, GIL, easy to share data, easy to corrupt data
Processes: separate memory, no GIL, hard to share data, impossible to corrupt
asyncio: single thread, no GIL, no shared state issues, but can't do CPU work
```

Choose based on your workload:
- I/O-bound → asyncio
- CPU-bound → multiprocessing
- Mixed → asyncio + ProcessPoolExecutor
