"""taskforeman.core.manager — WorkerManager, the central task pipeline."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional, Type

from taskforeman.config.settings import WorkerPoolSettings
from taskforeman.core.exceptions import WorkerException
from taskforeman.core.worker import BaseWorker

logger = logging.getLogger(__name__)


@dataclass
class _Task:
	fn: Callable[..., Coroutine]
	args: tuple = field(default_factory=tuple)
	kwargs: dict = field(default_factory=dict)
	retry_attempts: int = 0


class _EscalationTracker:
	"""Tracks error accumulation and circuit breaker state across all workers.

	Retry exhaustions accumulate up to ErrorSettings.max_accumulated before
	a circuit breaker trip fires. The accumulator resets after each trip.
	After CircuitBreakerSettings.max_attempts trips, the program exits.
	"""

	def __init__(self, settings: WorkerPoolSettings) -> None:
		self._err_cfg = settings.error
		self._cb_cfg  = settings.circuit_breaker
		self._lock    = asyncio.Lock()

		self._accumulated: int     = 0
		self._cb_trips: int        = 0
		self._cb_open: bool        = False
		self._cb_open_until: float = 0.0

	async def record_exhausted(self) -> str:
		"""Increment the error accumulator and conditionally fire a circuit breaker trip.

		Returns:
			'breaker_open' if a trip fired and the task should be re-enqueued,
			'drop' if the accumulation threshold has not yet been reached.
		"""
		async with self._lock:
			self._accumulated += 1
			logger.warning(
				"Retry budget exhausted — accumulated %d/%d before circuit breaker trip",
				self._accumulated,
				self._err_cfg.max_accumulated,
			)

			if self._accumulated < self._err_cfg.max_accumulated:
				return "drop"

			self._accumulated = 0
			return await self._open_breaker()

	async def record_forced_trip(self) -> None:
		"""Fire a circuit breaker trip immediately, bypassing error accumulation.

		The accumulator is left unchanged.
		"""
		async with self._lock:
			await self._open_breaker()

	async def check_breaker(self) -> float:
		"""Return seconds remaining if the breaker is open, or 0.0 if closed."""
		async with self._lock:
			if not self._cb_open:
				return 0.0
			remaining = self._cb_open_until - asyncio.get_event_loop().time()
			if remaining <= 0:
				self._cb_open = False
				return 0.0
			return remaining

	async def _open_breaker(self) -> str:
		"""Increment the trip counter and open the circuit breaker.

		Exits the program if the trip budget is exhausted. Must be called
		with self._lock held.

		Returns:
			'breaker_open' always (program exits instead of returning when
			the budget is exhausted).
		"""
		self._cb_trips += 1
		logger.warning(
			"Circuit breaker trip %d/%d",
			self._cb_trips,
			self._cb_cfg.max_attempts,
		)

		if self._cb_trips >= self._cb_cfg.max_attempts:
			logger.error(
				"Circuit breaker budget exhausted (%d trips) — exiting",
				self._cb_trips,
			)
			os._exit(1)

		timeout = self._cb_cfg.timeout * (self._cb_cfg.backoff ** (self._cb_trips - 1))
		self._cb_open       = True
		self._cb_open_until = asyncio.get_event_loop().time() + timeout
		logger.warning("Circuit breaker open for %.1fs", timeout)
		return "breaker_open"


class _RateLimiter:
	"""Per-worker token bucket rate limiter.

	Tokens accumulate continuously at a rate derived from requests_per_minute.
	The bucket capacity is capped at burst. Callers await acquire() before each
	task; it sleeps only as long as needed to obtain one token.

	Instantiate with requests_per_minute=None for a no-op limiter that never
	sleeps.
	"""

	def __init__(self, requests_per_minute: Optional[float], burst: int) -> None:
		self._disabled = requests_per_minute is None
		if not self._disabled:
			self._rate        = requests_per_minute / 60.0
			self._burst       = float(burst)
			self._tokens      = 1.0
			self._last_refill = asyncio.get_event_loop().time()

	async def acquire(self) -> None:
		"""Block until one token is available, then consume it."""
		if self._disabled:
			return

		loop = asyncio.get_event_loop()

		while True:
			now               = loop.time()
			elapsed           = now - self._last_refill
			self._tokens      = min(self._burst, self._tokens + elapsed * self._rate)
			self._last_refill = now

			if self._tokens >= 1.0:
				self._tokens -= 1.0
				return

			wait = (1.0 - self._tokens) / self._rate
			await asyncio.sleep(wait)


class WorkerManager:
	"""A bounded, continuously-draining async task pipeline.

	Manages a fixed pool of stateful workers. Each worker runs in its own
	asyncio task and pulls work from a shared queue. Failures escalate
	automatically through three levels: retry → error accumulation →
	circuit breaker.

	Use WorkerManager(adapter_class, settings) when the manager should own
	the full worker lifecycle. Use WorkerManager.from_workers(workers, settings)
	when workers are pre-constructed with individual configuration.

	Example — managed lifecycle::

		async with WorkerManager(MyWorker, settings) as manager:
			for item in items:
				await manager.enqueue(my_task, item)
			await manager.join()

	Example — bring your own workers::

		workers = [
			MyWorker(settings, proxy="proxy-1.example.com"),
			MyWorker(settings, proxy="proxy-2.example.com"),
		]
		async with WorkerManager.from_workers(workers, settings) as manager:
			for item in items:
				await manager.enqueue(my_task, item)
			await manager.join()
	"""

	def __init__(
		self,
		adapter_class: Type[BaseWorker],
		settings: WorkerPoolSettings | None = None,
	) -> None:
		self._settings      = settings or WorkerPoolSettings()
		self._adapter_class = adapter_class
		self._owned_workers = True

		self._task_queue: asyncio.Queue[_Task | None] = asyncio.Queue(
			maxsize=self._settings.queue_maxsize,
		)
		self._workers:   list[asyncio.Task] = []
		self._pool:      list[BaseWorker]   = []
		self._escalation = _EscalationTracker(self._settings)

	@classmethod
	def from_workers(
		cls,
		workers: list[BaseWorker],
		settings: WorkerPoolSettings | None = None,
	) -> "WorkerManager":
		"""Construct a WorkerManager from pre-built worker instances.

		The manager calls start() on each worker during its own startup.
		Workers must not have had start() called prior to this.

		Args:
			workers: Pre-constructed worker instances to register.
			settings: Pipeline settings. Defaults are used if omitted.

		Returns:
			A WorkerManager that will manage the provided workers.
		"""
		instance = cls.__new__(cls)
		instance._settings      = settings or WorkerPoolSettings()
		instance._adapter_class = None
		instance._owned_workers = False

		instance._task_queue = asyncio.Queue(
			maxsize=instance._settings.queue_maxsize,
		)
		instance._workers    = []
		instance._pool       = [
			setattr(w, "index", i) or w
			for i, w in enumerate(workers)
		]
		instance._escalation = _EscalationTracker(instance._settings)
		return instance

	async def enqueue(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
		"""Add a task to the pipeline.

		Blocks if the queue is at capacity until a slot becomes available.

		Args:
			fn: Async callable with signature ``(worker, *args, **kwargs)``.
			*args: Positional arguments forwarded to fn.
			**kwargs: Keyword arguments forwarded to fn.
		"""
		await self._task_queue.put(_Task(fn, args, kwargs))

	async def join(self) -> None:
		"""Block until every enqueued task has been processed."""
		await self._task_queue.join()

	@property
	def queue_size(self) -> int:
		"""Current number of tasks waiting in the queue."""
		return self._task_queue.qsize()

	async def start(self) -> None:
		"""Start all workers and begin draining the queue."""
		cfg = self._settings

		if self._owned_workers:
			for i in range(cfg.pool.max_size):
				self._pool.append(self._adapter_class(index=i))

		for i, worker in enumerate(self._pool):
			await worker.start()
			self._workers.append(
				asyncio.create_task(
					self._worker_loop(worker),
					name=f"taskforeman-worker-{i}",
				)
			)
			if i < len(self._pool) - 1:
				await asyncio.sleep(cfg.worker_start_delay)

		logger.info(
			"WorkerManager started — %d workers, queue_maxsize=%d",
			len(self._pool),
			cfg.queue_maxsize,
		)

	async def stop(self) -> None:
		"""Drain the queue gracefully and shut down all workers."""
		for _ in self._workers:
			await self._task_queue.put(None)
		await asyncio.gather(*self._workers, return_exceptions=True)
		await asyncio.gather(*(w.stop() for w in self._pool), return_exceptions=True)
		self._workers.clear()
		self._pool.clear()
		logger.info("WorkerManager stopped")

	async def __aenter__(self) -> "WorkerManager":
		await self.start()
		return self

	async def __aexit__(self, exc_type: Any, *_: Any) -> None:
		if exc_type is asyncio.CancelledError:
			for worker in self._workers:
				worker.cancel()
			await asyncio.gather(*self._workers, return_exceptions=True)
			await asyncio.gather(*(w.stop() for w in self._pool), return_exceptions=True)
			self._workers.clear()
			self._pool.clear()
			logger.info("WorkerManager force-stopped")
		else:
			await self.stop()

	async def _worker_loop(self, worker: BaseWorker) -> None:
		rl_cfg              = self._settings.rate_limit
		rate_limiter        = _RateLimiter(rl_cfg.requests_per_minute, rl_cfg.burst)
		restart_every       = self._settings.pool.restart_every
		tasks_since_restart = 0

		while True:
			wait = await self._escalation.check_breaker()
			if wait > 0:
				logger.warning("Circuit breaker open — waiting %.1fs", wait)
				await asyncio.sleep(wait)
				continue

			task = await self._task_queue.get()

			if task is None:
				self._task_queue.task_done()
				break

			if restart_every and tasks_since_restart >= restart_every:
				logger.debug("Rotating worker after %d tasks", tasks_since_restart)
				await worker.restart()
				tasks_since_restart = 0

			await rate_limiter.acquire()

			task_succeeded = False
			try:
				await self._run_task(task, worker)
				task_succeeded = True
				tasks_since_restart += 1

			except _RetryBudgetExhausted as exc:
				action = await self._escalation.record_exhausted()
				if action == "breaker_open":
					logger.warning(
						"Re-enqueuing task after circuit breaker trip: %s", exc.cause
					)
					await self._task_queue.put(task)

			except _ForceError as exc:
				action = await self._escalation.record_exhausted()
				if action == "breaker_open":
					logger.warning(
						"Re-enqueuing task after forced error accumulation: %s", exc.cause
					)
					await self._task_queue.put(task)

			except _ForceCircuitBreaker as exc:
				await self._escalation.record_forced_trip()
				logger.warning(
					"Re-enqueuing task after forced circuit breaker trip: %s", exc.cause
				)
				await self._task_queue.put(task)

			except _SkipTask:
				pass

			except _QuitWorker:
				logger.error("WorkerException(quit=True) — exiting")
				os._exit(1)

			finally:
				self._task_queue.task_done()

			if not task_succeeded:
				tasks_since_restart = 0

	async def _run_task(self, task: _Task, worker: BaseWorker) -> None:
		"""Execute a task with retry-level backoff.

		Both WorkerException(retry=True) and unhandled exceptions consume
		from the same retry budget. Wait between attempts is calculated as
		RetrySettings.timeout * (backoff ** attempt_number).

		Args:
			task: The task envelope to execute.
			worker: The worker instance passed to the task callable.

		Raises:
			_RetryBudgetExhausted: When retry.max_attempts is reached.
			_ForceError: On WorkerException(error=True).
			_ForceCircuitBreaker: On WorkerException(circuit_breaker=True).
			_SkipTask: When the task should be silently discarded.
			_QuitWorker: On WorkerException(quit=True).
		"""
		cfg   = self._settings
		r_cfg = cfg.retry

		while True:
			try:
				await asyncio.wait_for(
					task.fn(worker, *task.args, **task.kwargs),
					timeout=cfg.task_timeout,
				)
				return

			except WorkerException as exc:
				if exc.circuit_breaker:
					raise _ForceCircuitBreaker(exc)

				if exc.error:
					if exc.restart:
						logger.info("Restarting worker before error accumulation: %s", exc)
						await worker.restart()
					raise _ForceError(exc)

				if exc.quit:
					if exc.restart:
						logger.info("Restarting worker before quit: %s", exc)
						await worker.restart()
					raise _QuitWorker()

				if exc.skip:
					if exc.restart:
						logger.info("Restarting worker before skip: %s", exc)
						await worker.restart()
					raise _SkipTask()

				if exc.restart:
					logger.info("Restarting worker: %s", exc)
					await worker.restart()

				if exc.retry:
					task.retry_attempts += 1
					if task.retry_attempts >= r_cfg.max_attempts:
						raise _RetryBudgetExhausted(exc)
					wait = r_cfg.timeout * (r_cfg.backoff ** (task.retry_attempts - 1))
					logger.warning(
						"WorkerException attempt %d/%d (%s) — retrying in %.1fs",
						task.retry_attempts, r_cfg.max_attempts, exc, wait,
					)
					await asyncio.sleep(wait)
				else:
					raise _SkipTask()

			except (
				_RetryBudgetExhausted,
				_ForceError,
				_ForceCircuitBreaker,
				_SkipTask,
				_QuitWorker,
			):
				raise

			except Exception as exc:
				task.retry_attempts += 1
				if task.retry_attempts >= r_cfg.max_attempts:
					raise _RetryBudgetExhausted(exc)
				wait = r_cfg.timeout * (r_cfg.backoff ** (task.retry_attempts - 1))
				logger.warning(
					"Attempt %d/%d failed (%s) — retrying in %.1fs",
					task.retry_attempts, r_cfg.max_attempts, exc, wait,
				)
				await asyncio.sleep(wait)


class _RetryBudgetExhausted(Exception):
	def __init__(self, cause: Exception) -> None:
		self.cause = cause


class _ForceError(Exception):
	def __init__(self, cause: Exception) -> None:
		self.cause = cause


class _ForceCircuitBreaker(Exception):
	def __init__(self, cause: Exception) -> None:
		self.cause = cause


class _SkipTask(Exception):
	pass


class _QuitWorker(Exception):
	pass
