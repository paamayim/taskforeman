"""taskforeman.core.exceptions — Public exception for controlling worker behaviour."""

from __future__ import annotations


class WorkerException(Exception):
	"""Raise from inside a task callable to signal the worker how to handle the outcome.

	All flags default to False. Only set the flags relevant to the desired outcome.
	When multiple flags are set, they are evaluated in the following priority order:
	circuit_breaker > error > quit > skip > retry. restart is honoured alongside
	whichever primary flag is active.

	Attributes:
		retry: Retry the task, subject to RetrySettings.max_attempts. Escalates
			to error accumulation once the budget is exhausted.
		restart: Restart the worker before the next attempt, before skipping,
			or before error accumulation.
		skip: Discard the task silently. Does not touch error accumulation.
		quit: Exit the program immediately. restart is honoured first if also set.
		error: Force one error accumulation and discard the task, bypassing
			the retry budget. Triggers a circuit breaker trip once
			ErrorSettings.max_accumulated is reached.
		circuit_breaker: Force an immediate circuit breaker trip and discard
			the task, bypassing error accumulation entirely.

	Example — retry with worker restart::

		raise WorkerException("session expired", restart=True, retry=True)

	Example — force error accumulation::

		raise WorkerException("rate limited", error=True)

	Example — force circuit breaker trip::

		raise WorkerException("proxy dead", circuit_breaker=True)

	Example — subclassing for readability::

		class SessionExpired(WorkerException):
			def __init__(self, message=None):
				super().__init__(message, restart=True, retry=True)

		class RateLimited(WorkerException):
			def __init__(self, message=None):
				super().__init__(message, error=True)

		class ProxyDead(WorkerException):
			def __init__(self, message=None):
				super().__init__(message, circuit_breaker=True)

		class FatalError(WorkerException):
			def __init__(self, message=None):
				super().__init__(message, restart=True, quit=True)
	"""

	def __init__(
		self,
		message: str | None = None,
		*,
		retry: bool = False,
		restart: bool = False,
		skip: bool = False,
		quit: bool = False,
		error: bool = False,
		circuit_breaker: bool = False,
	) -> None:
		super().__init__(message or self.__class__.__name__)
		self.retry           = retry
		self.restart         = restart
		self.skip            = skip
		self.quit            = quit
		self.error           = error
		self.circuit_breaker = circuit_breaker
