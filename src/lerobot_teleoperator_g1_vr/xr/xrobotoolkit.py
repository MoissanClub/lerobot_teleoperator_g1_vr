"""Lazy XRoboToolkit SDK adapter for the normalized XR source contract."""

from __future__ import annotations

import importlib
import math
import sys
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .clock import Clock, SystemClock
from .source import XRInputSource, XRSourceNotConnectedError
from .status import XRSourceState, XRSourceStatus
from .types import XRController, XRPose, XRSample, XRTrackedPose


class XRoboToolkitDependencyError(ImportError):
    """The optional XRoboToolkit Python SDK cannot be imported."""


class XRoboToolkitSDK(Protocol):
    def init(self) -> object: ...
    def close(self) -> object: ...
    def get_time_stamp_ns(self) -> object: ...
    def get_headset_pose(self) -> object: ...
    def get_left_controller_pose(self) -> object: ...
    def get_right_controller_pose(self) -> object: ...
    def get_left_grip(self) -> object: ...
    def get_right_grip(self) -> object: ...
    def get_left_trigger(self) -> object: ...
    def get_right_trigger(self) -> object: ...


@dataclass(frozen=True, slots=True)
class XRoboToolkitSourceConfig:
    sdk_site_packages: str | Path | None = None
    stale_timeout_s: float = 0.5

    def __post_init__(self) -> None:
        if self.sdk_site_packages is not None:
            object.__setattr__(self, "sdk_site_packages", Path(self.sdk_site_packages))
        if not math.isfinite(self.stale_timeout_s) or self.stale_timeout_s <= 0:
            raise ValueError("stale_timeout_s must be finite and positive")


def _load_sdk(config: XRoboToolkitSourceConfig) -> XRoboToolkitSDK:
    if config.sdk_site_packages is not None:
        path = str(config.sdk_site_packages.expanduser().resolve())
        if path not in sys.path:
            # Append: prepending can replace the pinned G1 NumPy/Pinocchio/MuJoCo stack.
            sys.path.append(path)
    try:
        return importlib.import_module("xrobotoolkit_sdk")
    except ImportError as exc:
        raise XRoboToolkitDependencyError(
            "Install xrobotoolkit_sdk or configure sdk_site_packages"
        ) from exc


def _pose(value: object) -> XRPose | None:
    try:
        values = tuple(float(item) for item in value)
        if len(values) != 7 or not all(math.isfinite(item) for item in values):
            return None
        return XRPose(values[:3], values[3:])
    except (TypeError, ValueError):
        return None


def _button(sdk: object, name: str) -> float:
    getter = getattr(sdk, name, None)
    if not callable(getter):
        return 0.0
    try:
        return float(bool(getter()))
    except Exception:
        return 0.0


def _controller(
    pose: XRPose | None,
    squeeze: object,
    trigger: object,
    buttons: object,
) -> XRController:
    try:
        return XRController(
            pose is not None,
            pose,
            squeeze=squeeze,
            trigger=trigger,
            buttons=buttons,
        )
    except (TypeError, ValueError):
        return XRController(False, None)


class XRoboToolkitSource(XRInputSource):
    """Read Quest/head/controller values from the XRoboToolkit PC Service SDK."""

    def __init__(
        self,
        config: XRoboToolkitSourceConfig | None = None,
        *,
        sdk: XRoboToolkitSDK | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config or XRoboToolkitSourceConfig()
        self._injected_sdk = sdk
        self.clock = clock or SystemClock()
        self._sdk: XRoboToolkitSDK | None = None
        self._sequence = 0
        self._last_timestamp_ns: int | None = None
        self._last_advance_s: float | None = None
        self._last_raw_action: dict[str, object] | None = None
        self._status = XRSourceStatus(XRSourceState.DISCONNECTED, "XRoboToolkit not connected")

    @property
    def is_connected(self) -> bool:
        return self._sdk is not None

    @property
    def status(self) -> XRSourceStatus:
        return self._status

    @property
    def last_raw_action(self) -> Mapping[str, object] | None:
        return deepcopy(self._last_raw_action)

    def connect(self) -> None:
        if self.is_connected:
            raise RuntimeError("XRoboToolkit source is already connected")
        sdk = self._injected_sdk or _load_sdk(self.config)
        try:
            sdk.init()
        except BaseException:
            with suppress(Exception):
                sdk.close()
            raise
        self._sdk = sdk
        self._sequence = 0
        self._last_timestamp_ns = None
        self._last_advance_s = None
        self._status = XRSourceStatus(XRSourceState.READY, "XRoboToolkit SDK connected")

    def _error_sample(self, now: float, detail: str) -> XRSample:
        status = XRSourceStatus(
            XRSourceState.STALE,
            detail,
            "Reconnect the Quest app and XRoboToolkit PC Service",
        )
        result = XRSample(
            sequence=self._sequence,
            captured_at_s=now,
            left=XRController(False, None),
            right=XRController(False, None),
            status=status,
            source_timestamp_ns=self._last_timestamp_ns,
            source_timestamp_advanced=False,
        )
        self._sequence += 1
        self._status = status
        return result

    def sample(self) -> XRSample:
        if self._sdk is None:
            raise XRSourceNotConnectedError("XRoboToolkit source is not connected")
        sdk = self._sdk
        now = self.clock.now()
        try:
            timestamp_ns = int(sdk.get_time_stamp_ns())
            raw = {
                "timestamp_ns": timestamp_ns,
                "headset_pose": list(sdk.get_headset_pose()),
                "left_controller_pose": list(sdk.get_left_controller_pose()),
                "right_controller_pose": list(sdk.get_right_controller_pose()),
                "left_grip": float(sdk.get_left_grip()),
                "right_grip": float(sdk.get_right_grip()),
                "left_trigger": float(sdk.get_left_trigger()),
                "right_trigger": float(sdk.get_right_trigger()),
                "left_buttons": {
                    "x": _button(sdk, "get_X_button"),
                    "y": _button(sdk, "get_Y_button"),
                    "menu": _button(sdk, "get_left_menu_button"),
                    "axis_click": _button(sdk, "get_left_axis_click"),
                },
                "right_buttons": {
                    "a": _button(sdk, "get_A_button"),
                    "b": _button(sdk, "get_B_button"),
                    "menu": _button(sdk, "get_right_menu_button"),
                    "axis_click": _button(sdk, "get_right_axis_click"),
                },
            }
        except Exception as exc:
            self._last_raw_action = {"error": f"{type(exc).__name__}: {exc}"}
            return self._error_sample(now, "XRoboToolkit SDK read failed")
        self._last_raw_action = deepcopy(raw)

        advanced = self._last_timestamp_ns is None or timestamp_ns > self._last_timestamp_ns
        moved_backward = (
            self._last_timestamp_ns is not None and timestamp_ns < self._last_timestamp_ns
        )
        if advanced:
            self._last_advance_s = now
        stale = (
            timestamp_ns <= 0
            or moved_backward
            or self._last_advance_s is None
            or now - self._last_advance_s > self.config.stale_timeout_s
        )
        self._last_timestamp_ns = timestamp_ns
        head_pose = _pose(raw["headset_pose"])
        left_pose = _pose(raw["left_controller_pose"])
        right_pose = _pose(raw["right_controller_pose"])
        if stale:
            return self._error_sample(now, "XRoboToolkit timestamp is stale or restarted")

        left = _controller(left_pose, raw["left_grip"], raw["left_trigger"], raw["left_buttons"])
        right = _controller(
            right_pose, raw["right_grip"], raw["right_trigger"], raw["right_buttons"]
        )
        invalid = [
            side
            for side, controller in (("left", left), ("right", right))
            if not controller.tracked
        ]
        detail = f"Invalid controller data: {', '.join(invalid)}" if invalid else ""
        status = XRSourceStatus(XRSourceState.READY, detail)
        result = XRSample(
            sequence=self._sequence,
            captured_at_s=now,
            head=XRTrackedPose(head_pose is not None, head_pose),
            left=left,
            right=right,
            status=status,
            source_timestamp_ns=timestamp_ns,
            source_timestamp_advanced=True if advanced else None,
        )
        self._sequence += 1
        self._status = status
        return result

    def disconnect(self) -> None:
        sdk, self._sdk = self._sdk, None
        self._status = XRSourceStatus(XRSourceState.DISCONNECTED, "XRoboToolkit disconnected")
        if sdk is not None:
            sdk.close()
