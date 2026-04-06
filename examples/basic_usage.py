"""Basic taskforeman usage example.

Demonstrates a minimal worker implementation and both construction styles.
Run with: python examples/basic_usage.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from taskforeman import (
	BaseWorker,
	PoolSettings,
	RateLimitSettings,
	RetrySettings,
	WorkerException,
	WorkerManager,
	WorkerPoolSettings,
	WorkerSettings,
)


@dataclass
class MyWorkerSettings(WorkerSettings):
	"""Per-worker configuration supplied by the user."""
	proxy: str = ""
	name: str = "worker"


class EchoWorker(BaseWorker):
	"""A trivial worker that holds no external resources."""

	async def start(self) -> None:
		self._running = True
		import requests
		self.network = requests

	async def stop(self) -> None:
		self._running = False


async def process(worker: EchoWorker, value: int) -> None:
	"""Task callable — receives the worker and any additional arguments."""
	if value == 3:
		raise WorkerException("skipping 3", skip=True)
	print(f"[worker-{worker.index}] processed {value} -> {value * 2}")


async def named_process(worker: EchoWorker, value: int) -> None:
	"""Task callable that uses per-worker configuration."""
	if value == 3:
		raise WorkerException("skipping 3", skip=True)
	print(f"[{worker.index}:{worker.worker_settings.name}] processed {value} -> {value * 2}")
	res = worker.network.get("https://api.weversetools.com/status.php")
	if res.text == "ERROR":
		raise WorkerException("skipping ERROR", retry=True)


async def managed_example() -> None:
	"""Manager owns the full worker lifecycle."""
	pool_settings = WorkerPoolSettings(
		pool       = PoolSettings(max_size=2),
		retry      = RetrySettings(max_attempts=2),
		rate_limit = RateLimitSettings(requests_per_minute=120, burst=5),
	)

	async with WorkerManager(EchoWorker, pool_settings) as manager:
		for i in range(6):
			await manager.enqueue(process, i)
		await manager.join()


async def from_workers_example() -> None:
	"""Pre-constructed workers with individual per-worker configuration."""
	pool_settings = WorkerPoolSettings(
		retry      = RetrySettings(max_attempts=4),
		rate_limit = RateLimitSettings(requests_per_minute=60, burst=12),
	)

	workers = [
		EchoWorker(MyWorkerSettings(proxy="residential-1.example.com", name="worker-0")),
		EchoWorker(MyWorkerSettings(proxy="residential-2.example.com", name="worker-1")),
	]

	async with WorkerManager.from_workers(workers, pool_settings) as manager:
		for i in range(6):
			await manager.enqueue(named_process, i)
		await manager.join()


if __name__ == "__main__":
	try:
		# print("=== Managed example ===")
		# asyncio.run(managed_example())
		print("\n=== From-workers example ===")
		asyncio.run(from_workers_example())
	except KeyboardInterrupt:
		pass
