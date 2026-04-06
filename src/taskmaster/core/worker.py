"""taskforeman.core.worker — Base class for all worker adapters."""

from __future__ import annotations

import abc
from typing import Any

from taskforeman.config.settings import WorkerSettings


class BaseWorker(abc.ABC):
	"""Abstract base class for stateful worker adapters.

	Subclass BaseWorker and implement start() and stop(). Expose the
	underlying driver or connection as self.driver. Task callables receive
	the worker instance directly and interact with self.driver themselves —
	the framework never touches it.

	Attributes:
		worker_settings: User-supplied per-worker configuration. The
			framework never reads this — it is passed through for the
			worker implementation's own use.
		index: The worker's position in the pool. Useful for logging,
			affinity, and distinguishing workers in from_workers() usage.

	Example::

		class MyWorkerSettings(WorkerSettings):
			proxy: str = ""

		class MyWorker(BaseWorker):
			async def start(self) -> None:
				self.driver = await launch_my_engine(
					proxy=self.worker_settings.proxy,
				)
				self._running = True

			async def stop(self) -> None:
				await self.driver.close()
				self._running = False

			async def healthy(self) -> bool:
				return self._running and self.driver.is_connected()

		async def my_task(worker: MyWorker, url: str) -> None:
			await worker.driver.goto(url)
	"""

	def __init__(
		self,
		worker_settings: WorkerSettings | None = None,
		index: int = 0,
		**kwargs: Any,
	) -> None:
		self.worker_settings = worker_settings or WorkerSettings()
		self.index           = index
		self._running        = False

	@abc.abstractmethod
	async def start(self) -> None:
		"""Launch the worker. Called once per worker on manager start."""

	@abc.abstractmethod
	async def stop(self) -> None:
		"""Shut down the worker. Called on manager stop or after a fatal error."""

	async def healthy(self) -> bool:
		"""Return True if the worker is ready to accept tasks.

		Override with a real probe for stronger guarantees. The default
		implementation returns True if start() has been called without
		a subsequent stop().
		"""
		return self._running

	async def restart(self) -> None:
		"""Stop then start the worker.

		Called automatically on WorkerException(restart=True) and on
		pool rotation via PoolSettings.restart_every.
		"""
		await self.stop()
		await self.start()

	async def __aenter__(self) -> "BaseWorker":
		await self.start()
		return self

	async def __aexit__(self, *_: Any) -> None:
		await self.stop()
