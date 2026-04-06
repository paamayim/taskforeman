"""Tests for WorkerPoolSettings construction — nested and flat."""

from __future__ import annotations

import pytest

from taskforeman import (
	CircuitBreakerSettings,
	ErrorSettings,
	PoolSettings,
	RateLimitSettings,
	RetrySettings,
	WorkerPoolSettings,
	WorkerSettings,
)


class TestWorkerSettings:
	def test_defaults(self):
		s = WorkerSettings()
		assert s.extra == {}

	def test_extra(self):
		s = WorkerSettings(extra={"proxy": "http://proxy.example.com"})
		assert s.extra["proxy"] == "http://proxy.example.com"

	def test_subclassable(self):
		class MySettings(WorkerSettings):
			proxy: str = ""

		s = MySettings()
		assert hasattr(s, "extra")


class TestNestedConstruction:
	def test_defaults(self):
		s = WorkerPoolSettings()
		assert s.task_timeout == 30.0
		assert s.queue_maxsize == 100
		assert s.worker_start_delay == 2.0
		assert s.pool.max_size == 4
		assert s.pool.restart_every is None
		assert s.retry.max_attempts == 3
		assert s.retry.timeout == 5.0
		assert s.retry.backoff == 2.0
		assert s.error.max_accumulated == 3
		assert s.rate_limit.requests_per_minute == 120.0
		assert s.rate_limit.burst == 1
		assert s.circuit_breaker.max_attempts == 3
		assert s.circuit_breaker.timeout == 10.0
		assert s.circuit_breaker.backoff == 2.0

	def test_nested_dataclasses(self):
		s = WorkerPoolSettings(
			task_timeout     = 10.0,
			pool             = PoolSettings(max_size=2, restart_every=10),
			retry            = RetrySettings(max_attempts=5, timeout=1.0, backoff=3.0),
			error            = ErrorSettings(max_accumulated=4),
			rate_limit       = RateLimitSettings(requests_per_minute=60, burst=3),
			circuit_breaker  = CircuitBreakerSettings(max_attempts=4, timeout=5.0, backoff=1.5),
		)
		assert s.task_timeout == 10.0
		assert s.pool.max_size == 2
		assert s.pool.restart_every == 10
		assert s.retry.max_attempts == 5
		assert s.retry.timeout == 1.0
		assert s.retry.backoff == 3.0
		assert s.error.max_accumulated == 4
		assert s.rate_limit.requests_per_minute == 60
		assert s.rate_limit.burst == 3
		assert s.circuit_breaker.max_attempts == 4
		assert s.circuit_breaker.timeout == 5.0
		assert s.circuit_breaker.backoff == 1.5


class TestFlatConstruction:
	def test_flat_kwargs(self):
		s = WorkerPoolSettings(
			max_size            = 2,
			restart_every       = 10,
			retry_max_attempts  = 5,
			retry_timeout       = 1.0,
			retry_backoff       = 3.0,
			max_accumulated     = 4,
			rpm                 = 60.0,
			burst               = 3,
			cb_max_attempts     = 4,
			cb_timeout          = 5.0,
			cb_backoff          = 1.5,
		)
		assert s.pool.max_size == 2
		assert s.pool.restart_every == 10
		assert s.retry.max_attempts == 5
		assert s.error.max_accumulated == 4
		assert s.rate_limit.requests_per_minute == 60.0
		assert s.rate_limit.burst == 3
		assert s.circuit_breaker.max_attempts == 4

	def test_rate_limit_disabled(self):
		s = WorkerPoolSettings(rpm=None)
		assert s.rate_limit.requests_per_minute is None

	def test_unexpected_kwarg_raises(self):
		with pytest.raises(TypeError, match="unexpected keyword arguments"):
			WorkerPoolSettings(nonexistent_key=True)
