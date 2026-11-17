"""Injectable clocks for live pacing and deterministic trace replay."""

from __future__ import annotations

import math
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Minimal clock used by freshness and replay code."""

    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


@runtime_checkable
class AdvanceableClock(Clock, Protocol):
    """A clock that deterministic replay can move to an exact time."""

    def advance_to(self, timestamp_s: float) -> None: ...


class SystemClock:
    """Production monotonic wall clock."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("sleep duration must be finite and nonnegative")
        time.sleep(seconds)


class DeterministicClock:
    """Manually advanced monotonic clock; sleeping advances without blocking."""

    def __init__(self, start_s: float = 0.0) -> None:
        if not math.isfinite(start_s) or start_s < 0:
            raise ValueError("start_s must be finite and nonnegative")
        self._now_s = float(start_s)

    def now(self) -> float:
        return self._now_s

    def sleep(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("sleep duration must be finite and nonnegative")
        self._now_s += seconds

    def advance_to(self, timestamp_s: float) -> None:
        if not math.isfinite(timestamp_s) or timestamp_s < self._now_s:
            raise ValueError("timestamp_s must be finite and monotonic")
        self._now_s = float(timestamp_s)
