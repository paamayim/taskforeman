"""Tests for WorkerManager — lifecycle, escalation, flow control."""

from __future__ import annotations

import asyncio
import pytest

from taskforeman import WorkerException, WorkerManager, WorkerPoolSettings
from tests.conftest import DummyWorker


async def _succeeds(worker: DummyWorker, store: list, value: int) -> None:
	store.append(value)


async def _always_fails(worker: DummyWorker) -> None:
	raise RuntimeError("always fails")


async def _raises(worker: DummyWorker, exc: WorkerException) -> None:
	raise exc


class TestLifecycle:
	async def test_managed_start_stop(self, settings, dummy_worker_class):
		manager = WorkerManager(dummy_worker_class, settings)
		await manager.start()
		assert len(manager._pool) == 1
		assert manager._pool[0]._running
		await manager.stop()
		assert len(manager._pool) == 0

	async def test_worker_index_assigned(self, settings, dummy_worker_class):
		async with WorkerManager(dummy_worker_class, settings) as manager:
			assert manager._pool[0].index == 0

	async def test_context_manager(self, settings, dummy_worker_class):
		async with WorkerManager(dummy_worker_class, settings) as manager:
			assert len(manager._pool) == 1
		assert len(manager._pool) == 0

	async def test_from_workers(self, settings):
		workers = [DummyWorker(index=0), DummyWorker(index=1)]
		async with WorkerManager.from_workers(workers, settings) as manager:
			assert len(manager._pool) == 2
			assert all(w._running for w in manager._pool)

	async def test_from_workers_preserves_index(self, settings):
		workers = [DummyWorker(index=0), DummyWorker(index=1)]
		async with WorkerManager.from_workers(workers, settings) as manager:
			assert manager._pool[0].index == 0
			assert manager._pool[1].index == 1

	async def test_queue_size(self, settings, dummy_worker_class):
		async with WorkerManager(dummy_worker_class, settings) as manager:
			assert manager.queue_size == 0


class TestTaskExecution:
	async def test_tasks_are_processed(self, settings, dummy_worker_class):
		store = []
		async with WorkerManager(dummy_worker_class, settings) as manager:
			for i in range(5):
				await manager.enqueue(_succeeds, store, i)
			await manager.join()
		assert sorted(store) == [0, 1, 2, 3, 4]

	async def test_retry_on_exception(self, settings, dummy_worker_class):
		attempts = []

		async def _fails_once(worker: DummyWorker) -> None:
			attempts.append(1)
			if len(attempts) == 1:
				raise RuntimeError("first attempt fails")

		async with WorkerManager(dummy_worker_class, settings) as manager:
			await manager.enqueue(_fails_once)
			await manager.join()

		assert len(attempts) == 2

	async def test_from_workers_processes_tasks(self, settings):
		store = []
		workers = [DummyWorker(index=0)]
		async with WorkerManager.from_workers(workers, settings) as manager:
			await manager.enqueue(_succeeds, store, 42)
			await manager.join()
		assert store == [42]


class TestWorkerException:
	async def test_skip_discards_task(self, settings, dummy_worker_class):
		calls = []

		async def _skip(worker: DummyWorker) -> None:
			calls.append(1)
			raise WorkerException(skip=True)

		async with WorkerManager(dummy_worker_class, settings) as manager:
			await manager.enqueue(_skip)
			await manager.join()

		assert len(calls) == 1

	async def test_retry_true_retries(self, settings, dummy_worker_class):
		attempts = []

		async def _retry_once(worker: DummyWorker) -> None:
			attempts.append(1)
			if len(attempts) < 2:
				raise WorkerException(retry=True)

		async with WorkerManager(dummy_worker_class, settings) as manager:
			await manager.enqueue(_retry_once)
			await manager.join()

		assert len(attempts) == 2

	async def test_restart_true_calls_restart(self, settings, dummy_worker_class):
		called = []

		async def _trigger_restart(worker: DummyWorker) -> None:
			called.append(1)
			if len(called) == 1:
				raise WorkerException(restart=True, retry=True)

		async with WorkerManager(dummy_worker_class, settings) as manager:
			await manager.enqueue(_trigger_restart)
			await manager.join()
			assert manager._pool[0].restart_count == 1

	async def test_error_flag_accumulates(self, settings, dummy_worker_class):
		async with WorkerManager(dummy_worker_class, settings) as manager:
			await manager.enqueue(_raises, WorkerException(error=True))
			await manager.join()
			assert manager._escalation._accumulated == 1

	async def test_circuit_breaker_flag_trips_immediately(self, settings, dummy_worker_class):
		async with WorkerManager(dummy_worker_class, settings) as manager:
			await manager.enqueue(_raises, WorkerException(circuit_breaker=True))
			await manager.join()
			assert manager._escalation._cb_trips == 1


class TestRateLimiter:
	async def test_rate_limiter_disabled(self, dummy_worker_class):
		settings = WorkerPoolSettings(max_size=1, worker_start_delay=0.0, rpm=None)
		store = []
		async with WorkerManager(dummy_worker_class, settings) as manager:
			for i in range(3):
				await manager.enqueue(_succeeds, store, i)
			await manager.join()
		assert len(store) == 3

	async def test_rate_limiter_enabled(self, dummy_worker_class):
		settings = WorkerPoolSettings(
			max_size           = 1,
			worker_start_delay = 0.0,
			rpm                = 600,
			burst              = 1,
		)
		store = []
		async with WorkerManager(dummy_worker_class, settings) as manager:
			for i in range(3):
				await manager.enqueue(_succeeds, store, i)
			await manager.join()
		assert len(store) == 3
