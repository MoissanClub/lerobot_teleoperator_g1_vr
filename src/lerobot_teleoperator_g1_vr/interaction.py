"""Shared freshness and re-clutch behavior for every XR source/retargeter."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .xr.clock import Clock, SystemClock
from .xr.status import XRSourceState, XRSourceStatus
from .xr.types import XRController, XRSample


@dataclass(frozen=True, slots=True)
class XRInteractionConfig:
    max_age_s: float = 0.25
    clutch_threshold: float = 0.5
    reconnect_hint: str = "Reconnect the XR source, release grip, then press grip again"

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_age_s) or self.max_age_s <= 0:
            raise ValueError("max_age_s must be finite and positive")
        if not math.isfinite(self.clutch_threshold) or not 0 < self.clutch_threshold <= 1:
            raise ValueError("clutch_threshold must be in (0, 1]")
        if not isinstance(self.reconnect_hint, str) or not self.reconnect_hint:
            raise ValueError("reconnect_hint must be a nonempty string")


def _disabled_controller() -> XRController:
    return XRController(False, None)


class XRInteractionGuard:
    """Fail-hold stale data and require an explicit release/re-grip after recovery."""

    def __init__(
        self, config: XRInteractionConfig | None = None, *, clock: Clock | None = None
    ) -> None:
        self.config = config or XRInteractionConfig()
        self.clock = clock or SystemClock()
        self.reset()

    @property
    def awaiting_release(self) -> tuple[bool, bool]:
        return tuple(self._awaiting_release)

    def reset(self) -> None:
        self._awaiting_release = [False, False]
        self._last_source_timestamp_ns: int | None = None

    def _is_fresh(self, sample: XRSample) -> tuple[bool, str]:
        now = self.clock.now()
        age = now - sample.captured_at_s
        if (
            sample.status.state is not XRSourceState.READY
            or not math.isfinite(now)
            or not math.isfinite(age)
            or not 0 <= age <= self.config.max_age_s
        ):
            return False, "XR source is disconnected, stale, or outside the freshness window"
        timestamp = sample.source_timestamp_ns
        if sample.source_timestamp_advanced is False:
            return False, "XR source timestamp did not advance"
        if (
            timestamp is not None
            and self._last_source_timestamp_ns is not None
            and timestamp < self._last_source_timestamp_ns
        ):
            return False, "XR source timestamp moved backward"
        return True, ""

    def process(self, sample: XRSample) -> XRSample:
        if not isinstance(sample, XRSample):
            raise TypeError("sample must be an XRSample")
        fresh, reason = self._is_fresh(sample)
        if not fresh:
            self._awaiting_release[:] = [True, True]
            if sample.status.state is XRSourceState.DISCONNECTED:
                self._last_source_timestamp_ns = None
            return replace(
                sample,
                captured_at_s=self.clock.now(),
                left=_disabled_controller(),
                right=_disabled_controller(),
                status=XRSourceStatus(
                    XRSourceState.STALE,
                    reason,
                    self.config.reconnect_hint,
                ),
            )

        if sample.source_timestamp_ns is not None:
            self._last_source_timestamp_ns = sample.source_timestamp_ns
        controllers = [sample.left, sample.right]
        waiting: list[str] = []
        for index, (side, controller) in enumerate(
            zip(("left", "right"), controllers, strict=True)
        ):
            if not self._awaiting_release[index]:
                continue
            if controller.squeeze < self.config.clutch_threshold:
                self._awaiting_release[index] = False
            else:
                controllers[index] = replace(controller, squeeze=0.0)
                waiting.append(side)
        status = sample.status
        if waiting:
            status = XRSourceStatus(
                XRSourceState.READY,
                f"Waiting for grip release: {', '.join(waiting)}",
                "Release the listed grip, then press it again to resume",
            )
        return replace(sample, left=controllers[0], right=controllers[1], status=status)
