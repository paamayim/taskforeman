# workerpool

A bounded, fault-tolerant async worker pipeline for Python 3.11+.

Designed for workloads that require stateful, long-lived workers — browser
automation, database connection pools, API clients, or anything where the
worker itself needs lifecycle management. Failures escalate automatically
through three levels: **retry → error accumulation → circuit breaker**.

---

## Installation

```bash
pip install -e .
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
```

---

## Quick start

```python
import asyncio
from workerpool import BaseWorker, WorkerManager, WorkerSettings, WorkerException

class MyWorker(BaseWorker):
    async def start(self) -> None:
        self.driver = await launch_my_engine()
        self._running = True

    async def stop(self) -> None:
        await self.driver.close()
        self._running = False

async def my_task(worker: MyWorker, url: str) -> None:
    page = await worker.driver.goto(url)
    if page.status == 429:
        raise WorkerException("rate limited", error=True)

async def main():
    settings = WorkerSettings(max_size=4, rpm=60)
    async with WorkerManager(MyWorker, settings) as manager:
        for url in urls:
            await manager.enqueue(my_task, url)
        await manager.join()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

---

## Construction styles

### Managed lifecycle

The manager instantiates and owns all workers:

```python
async with WorkerManager(MyWorker, settings) as manager:
    ...
```

### Bring your own workers

Pre-construct workers with individual configuration, then hand them to the manager:

```python
workers = [
    MyWorker(settings, proxy="residential-1.example.com"),
    MyWorker(settings, proxy="residential-2.example.com"),
    MyWorker(settings, proxy="datacenter-1.example.com"),
]
async with WorkerManager.from_workers(workers, settings) as manager:
    ...
```

---

## Settings

Settings can be provided as nested dataclasses (recommended for production)
or as flat keyword arguments (convenient for scripts).

### Nested

```python
from workerpool import (
    WorkerSettings,
    PoolSettings,
    RetrySettings,
    ErrorSettings,
    RateLimitSettings,
    CircuitBreakerSettings,
)

settings = WorkerSettings(
    task_timeout    = 30.0,
    queue_maxsize   = 100,
    pool            = PoolSettings(max_size=4, restart_every=50),
    retry           = RetrySettings(max_attempts=3, timeout=5.0, backoff=2.0),
    error           = ErrorSettings(max_accumulated=3),
    rate_limit      = RateLimitSettings(requests_per_minute=120, burst=5),
    circuit_breaker = CircuitBreakerSettings(max_attempts=3, timeout=10.0, backoff=2.0),
)
```

### Flat

```python
settings = WorkerSettings(
    max_size           = 4,
    restart_every      = 50,
    retry_max_attempts = 3,
    retry_timeout      = 5.0,
    retry_backoff      = 2.0,
    max_accumulated    = 3,
    rpm                = 120,
    burst              = 5,
    cb_max_attempts    = 3,
    cb_timeout         = 10.0,
    cb_backoff         = 2.0,
)
```

### Reference

| Setting | Default | Description |
|---|---|---|
| `task_timeout` | `30.0` | Per-task execution timeout in seconds |
| `queue_maxsize` | `100` | Max tasks held in queue; callers block when full |
| `worker_start_delay` | `2.0` | Seconds between starting successive workers |
| `pool.max_size` | `4` | Number of concurrent workers |
| `pool.restart_every` | `None` | Restart worker after N completed tasks; None disables |
| `retry.max_attempts` | `3` | Max attempts before escalating to error accumulation |
| `retry.timeout` | `5.0` | Base wait in seconds between retry attempts |
| `retry.backoff` | `2.0` | Multiplier applied to timeout on each attempt |
| `error.max_accumulated` | `3` | Retry exhaustions before a circuit breaker trip fires |
| `rate_limit.requests_per_minute` | `120.0` | Sustained RPM per worker; None disables |
| `rate_limit.burst` | `1` | Token bucket capacity; 1 = strict uniform rate |
| `circuit_breaker.max_attempts` | `3` | Trips allowed before the program exits |
| `circuit_breaker.timeout` | `10.0` | Base pause in seconds when the breaker opens |
| `circuit_breaker.backoff` | `2.0` | Multiplier applied to timeout on each trip |

---

## Flow control

Raise `WorkerException` from inside any task callable to control how the
worker handles the outcome.

```python
from workerpool import WorkerException

# Retry the task (counts against retry budget)
raise WorkerException("busy", retry=True)

# Restart the worker, then retry
raise WorkerException("session expired", restart=True, retry=True)

# Discard the task silently (no error accumulation)
raise WorkerException("not found", skip=True)

# Force one error accumulation, discard task
raise WorkerException("rate limited", error=True)

# Force an immediate circuit breaker trip, discard task
raise WorkerException("proxy dead", circuit_breaker=True)

# Exit the program immediately
raise WorkerException("unrecoverable", quit=True)
```

### Flag priority

`circuit_breaker` > `error` > `quit` > `skip` > `retry`

`restart` is honoured alongside any primary flag.

### Subclassing for readability

```python
class SessionExpired(WorkerException):
    def __init__(self, message=None):
        super().__init__(message, restart=True, retry=True)

class RateLimited(WorkerException):
    def __init__(self, message=None):
        super().__init__(message, error=True)

class ProxyDead(WorkerException):
    def __init__(self, message=None):
        super().__init__(message, circuit_breaker=True)
```

---

## Escalation model

```
retry → error accumulation → circuit breaker
```

1. **Retry** — the task is retried up to `retry.max_attempts` times, with
   exponential backoff between attempts.

2. **Error accumulation** — once the retry budget is exhausted, the failure
   is accumulated. When `error.max_accumulated` failures accumulate, a
   circuit breaker trip fires and the accumulator resets.

3. **Circuit breaker** — all workers pause for `circuit_breaker.timeout`
   seconds (with exponential backoff on each trip) and the task is
   re-enqueued. After `circuit_breaker.max_attempts` trips, the program
   exits.

---

## Running tests

```bash
pytest
```

---

## Project structure

```
src/
  workerpool/
    __init__.py
    config/
      settings.py
    core/
      exceptions.py
      manager.py
      worker.py
tests/
  conftest.py
  test_manager.py
  test_settings.py
  test_worker.py
examples/
  basic_usage.py
pyproject.toml
README.md
```
