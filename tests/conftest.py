"""Shared fixtures for taskforeman tests."""

from __future__ import annotations

import pytest

from taskforeman import BaseWorker, WorkerPoolSettings, WorkerSettings


class DummyWorker(BaseWorker):
	"""Minimal worker that records start/stop calls for assertions."""

	def __init__(self, worker_settings=None, index=0, **kwargs):
		super().__init__(worker_settings, index, **kwargs)
		self.start_count   = 0
		self.stop_count    = 0
		self.restart_count = 0

	async def start(self) -> None:
		self.start_count += 1
		self._running = True

	async def stop(self) -> None:
		self.stop_count += 1
		self._running = False

	async def restart(self) -> None:
		self.restart_count += 1
		await super().restart()


@pytest.fixture
def settings() -> WorkerPoolSettings:
	return WorkerPoolSettings(
		max_size            = 1,
		worker_start_delay  = 0.0,
		task_timeout        = 5.0,
		retry_max_attempts  = 2,
		retry_timeout       = 0.0,
		retry_backoff       = 1.0,
		max_accumulated     = 2,
		cb_max_attempts     = 2,
		cb_timeout          = 0.01,
		cb_backoff          = 1.0,
		rpm                 = None,
	)


@pytest.fixture
def dummy_worker_class():
	return DummyWorker
