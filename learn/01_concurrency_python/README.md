# Module 1: Concurrency Programming in Python

Learn async/await from zero to debugging real production bugs.

## Lessons (~2 hours)

| # | Notebook | What You Learn |
|---|----------|---------------|
| 01 | `01_why_async.ipynb` | Sequential vs concurrent, `async def`, `await`, `gather()` |
| 02 | `02_event_loop.ipynb` | How the event loop schedules tasks, blocking vs yielding, `run_in_executor` |
| 03 | `03_asyncio_queue_producer_consumer.ipynb` | `asyncio.Queue`, producer/consumer pattern, why producers must yield |
| 04 | `04_create_task_background_work.ipynb` | `create_task`, background loops, `asyncio.Event` signaling |
| 05 | `05_sbot_buffering_bug.ipynb` | Real bug case study: reproduce, debug, and fix the sbot buffering issue |
| 06 | `06_redis_streams_extension.ipynb` | Redis Streams as an external message broker (eliminates in-process buffering) |

## Prerequisites

- Basic Python (functions, classes, loops)
- Jupyter notebook (`pip install jupyter`)

## Key Takeaways

1. `await` = voluntary pause point. Between two `await`s, you run alone.
2. Blocking without `await` freezes the entire event loop.
3. `run_in_executor` wraps blocking code in a thread.
4. Producers must yield between emits or consumers starve.
5. Sync callbacks beat async queues for immediate delivery.
6. External brokers (Redis) eliminate in-process scheduling issues.
