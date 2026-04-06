"""Tests for BaseWorker lifecycle."""

from __future__ import annotations

import pytest

from taskforeman import WorkerSettings


class TestBaseWorker:
	async def test_start_sets_running(self, dummy_worker_class):
		w = dummy_worker_class()
		assert not w._running
		await w.start()
		assert w._running
		await w.stop()

	async def test_stop_clears_running(self, dummy_worker_class):
		w = dummy_worker_class()
		await w.start()
		await w.stop()
		assert not w._running

	async def test_healthy_reflects_running(self, dummy_worker_class):
		w = dummy_worker_class()
		assert not await w.healthy()
		await w.start()
		assert await w.healthy()
		await w.stop()
		assert not await w.healthy()

	async def test_restart_increments_counter(self, dummy_worker_class):
		w = dummy_worker_class()
		await w.start()
		await w.restart()
		assert w.restart_count == 1
		assert w.start_count == 2
		assert w.stop_count == 1
		await w.stop()

	async def test_context_manager(self, dummy_worker_class):
		w = dummy_worker_class()
		async with w:
			assert w._running
		assert not w._running

	async def test_index_stored(self, dummy_worker_class):
		w = dummy_worker_class(index=3)
		assert w.index == 3

	async def test_worker_settings_stored(self, dummy_worker_class):
		ws = WorkerSettings(extra={"proxy": "http://proxy.example.com"})
		w = dummy_worker_class(worker_settings=ws)
		assert w.worker_settings.extra["proxy"] == "http://proxy.example.com"

	async def test_default_worker_settings(self, dummy_worker_class):
		w = dummy_worker_class()
		assert w.worker_settings is not None
		assert w.index == 0
