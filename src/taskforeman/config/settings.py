"""taskforeman.config.settings — Configuration dataclasses for WorkerManager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WorkerSettings:
	"""User-defined per-worker configuration.

	Pass an instance to each worker in the from_workers() path to supply
	per-worker configuration such as proxies, credentials, or browser
	profiles. The framework never reads this object — it is purely for
	the user's own worker implementation.

	Subclass freely to add typed fields, or use the extra dict for
	unstructured config.

	Attributes:
		extra: Arbitrary key-value pairs for worker-specific options.

	Example::

		class MyWorkerSettings(WorkerSettings):
			proxy: str = ""
			headless: bool = True

		workers = [
			MyWorker(MyWorkerSettings(proxy="residential-1.example.com"), index=0),
			MyWorker(MyWorkerSettings(proxy="residential-2.example.com"), index=1),
		]
	"""

	extra: dict = field(default_factory=dict)


@dataclass
class PoolSettings:
	"""Controls worker pool sizing and rotation.

	Attributes:
		max_size: Maximum number of concurrent workers.
		restart_every: Restart a worker after this many completed tasks.
			None disables rotation.
	"""

	max_size: int = 4
	restart_every: Optional[int] = None


@dataclass
class RetrySettings:
	"""Controls per-task retry behaviour.

	Attributes:
		max_attempts: Maximum number of attempts before the retry budget
			is exhausted and the failure is escalated.
		timeout: Base wait time in seconds between attempts.
		backoff: Multiplier applied to timeout on each successive attempt.
	"""

	max_attempts: int = 3
	timeout: float = 5.0
	backoff: float = 2.0


@dataclass
class ErrorSettings:
	"""Controls error accumulation before a circuit breaker trip.

	Attributes:
		max_accumulated: Number of retry exhaustions that must accumulate
			before a circuit breaker trip fires. Resets after each trip.
	"""

	max_accumulated: int = 3


@dataclass
class RateLimitSettings:
	"""Controls per-worker request rate limiting via a token bucket.

	Each worker maintains its own independent token bucket. Tokens refill
	continuously at a rate derived from requests_per_minute. burst controls
	how many tokens the bucket can hold, allowing short bursts above the
	sustained rate before throttling kicks in.

	Set requests_per_minute to None to disable rate limiting entirely.

	Attributes:
		requests_per_minute: Sustained request rate per worker. Defaults to
			120. Set to None to disable rate limiting entirely.
		burst: Maximum number of tokens the bucket can accumulate. A burst
			of 1 enforces a strict uniform rate with no bursting allowed.
	"""

	requests_per_minute: Optional[float] = 120.0
	burst: int = 1


@dataclass
class CircuitBreakerSettings:
	"""Controls circuit breaker trip behaviour.

	Attributes:
		max_attempts: Number of trips allowed before the program exits.
		timeout: Base pause duration in seconds when the breaker opens.
		backoff: Multiplier applied to timeout on each successive trip.
	"""

	max_attempts: int = 3
	timeout: float = 10.0
	backoff: float = 2.0


@dataclass
class WorkerPoolSettings:
	"""Top-level pipeline configuration for WorkerManager.

	Can be constructed either with explicit nested dataclasses (recommended
	for production) or with flat keyword arguments (convenient for scripts).

	Flat kwargs are mapped to their nested counterparts by name:
		- max_size, restart_every               -> PoolSettings
		- retry_max_attempts, retry_timeout,
		  retry_backoff                         -> RetrySettings
		- max_accumulated                       -> ErrorSettings
		- rpm, burst                            -> RateLimitSettings
		- cb_max_attempts, cb_timeout,
		  cb_backoff                            -> CircuitBreakerSettings

	Attributes:
		task_timeout: Per-task execution timeout in seconds.
		queue_maxsize: Maximum number of tasks held in the queue.
			Callers block on enqueue when the queue is full.
		worker_start_delay: Seconds to wait between starting successive
			workers during initialisation.
		pool: Pool sizing and rotation settings.
		retry: Retry budget and backoff settings.
		error: Error accumulation settings.
		rate_limit: Per-worker rate limiting settings.
		circuit_breaker: Circuit breaker trip settings.

	Example nested (production)::

		settings = WorkerPoolSettings(
			task_timeout    = 30.0,
			pool            = PoolSettings(max_size=4, restart_every=50),
			retry           = RetrySettings(max_attempts=3, timeout=5.0, backoff=2.0),
			error           = ErrorSettings(max_accumulated=2),
			rate_limit      = RateLimitSettings(requests_per_minute=60, burst=5),
			circuit_breaker = CircuitBreakerSettings(
				max_attempts=3, timeout=10.0, backoff=2.0,
			),
		)

	Example flat (scripts)::

		settings = WorkerPoolSettings(max_size=4, retry_max_attempts=3, rpm=60)
	"""

	task_timeout: float = 30.0
	queue_maxsize: int = 100
	worker_start_delay: float = 2.0
	pool: PoolSettings = field(default_factory=PoolSettings)
	retry: RetrySettings = field(default_factory=RetrySettings)
	error: ErrorSettings = field(default_factory=ErrorSettings)
	rate_limit: RateLimitSettings = field(default_factory=RateLimitSettings)
	circuit_breaker: CircuitBreakerSettings = field(default_factory=CircuitBreakerSettings)

	def __init__(self, **kwargs) -> None:
		self.task_timeout       = kwargs.pop("task_timeout", 30.0)
		self.queue_maxsize      = kwargs.pop("queue_maxsize", 100)
		self.worker_start_delay = kwargs.pop("worker_start_delay", 2.0)

		self.pool = kwargs.pop("pool", PoolSettings(
			max_size      = kwargs.pop("max_size", 4),
			restart_every = kwargs.pop("restart_every", None),
		))

		self.retry = kwargs.pop("retry", RetrySettings(
			max_attempts = kwargs.pop("retry_max_attempts", 3),
			timeout      = kwargs.pop("retry_timeout", 5.0),
			backoff      = kwargs.pop("retry_backoff", 2.0),
		))

		self.error = kwargs.pop("error", ErrorSettings(
			max_accumulated = kwargs.pop("max_accumulated", 3),
		))

		self.rate_limit = kwargs.pop("rate_limit", RateLimitSettings(
			requests_per_minute = kwargs.pop("rpm", 120.0),
			burst               = kwargs.pop("burst", 1),
		))

		self.circuit_breaker = kwargs.pop("circuit_breaker", CircuitBreakerSettings(
			max_attempts = kwargs.pop("cb_max_attempts", 3),
			timeout      = kwargs.pop("cb_timeout", 10.0),
			backoff      = kwargs.pop("cb_backoff", 2.0),
		))

		if kwargs:
			raise TypeError(
				f"WorkerPoolSettings received unexpected keyword arguments: {list(kwargs)}"
			)
