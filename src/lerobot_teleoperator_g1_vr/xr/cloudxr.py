"""CloudXR/Isaac Teleop adapter for the normalized XR source contract.

The module itself has no LeRobot, Isaac Teleop, OpenXR, GPU, or video imports.
Those optional dependencies are resolved only when the default reader factory is
used during ``connect()``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from .clock import Clock, SystemClock
from .source import XRInputSource, XRSourceNotConnectedError
from .status import XRSourceState, XRSourceStatus
from .types import XRController, XRPose, XRSample

DEFAULT_BASE_T_ANCHOR = (
    (0.0, 0.0, -1.0, 0.0),
    (-1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


class CloudXRDependencyError(ImportError):
    """The optional pinned LeRobot/Isaac Teleop stack is unavailable."""


class CloudXRReader(Protocol):
    """Narrow lifecycle used from LeRobot's existing XRControllers reader."""

    def connect(self) -> None: ...

    def get_action(self) -> Mapping[str, object]: ...

    def disconnect(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CloudXRSourceConfig:
    """Source settings independent of the optional SDK objects."""

    app_name: str = "LeRobot G1 VR"
    max_age_s: float = 0.25
    base_T_anchor: tuple[tuple[float, float, float, float], ...] = DEFAULT_BASE_T_ANCHOR
    video_channel: str | None = None
    video_expected_source: str | None = None
    video_width: int = 640
    video_height: int = 480

    def __post_init__(self) -> None:
        if not isinstance(self.app_name, str) or not self.app_name.strip():
            raise ValueError("app_name must be a nonempty string")
        if not math.isfinite(self.max_age_s) or self.max_age_s <= 0:
            raise ValueError("max_age_s must be finite and positive")
        try:
            transform = tuple(tuple(float(value) for value in row) for row in self.base_T_anchor)
        except (TypeError, ValueError) as exc:
            raise TypeError("base_T_anchor must be a finite 4x4 transform") from exc
        if (
            len(transform) != 4
            or any(len(row) != 4 for row in transform)
            or not all(math.isfinite(value) for row in transform for value in row)
        ):
            raise ValueError("base_T_anchor must be a finite 4x4 transform")
        rotation = tuple(row[:3] for row in transform[:3])
        orthonormal = all(
            math.isclose(
                sum(rotation[row][axis] * rotation[column][axis] for axis in range(3)),
                1.0 if row == column else 0.0,
                abs_tol=1e-6,
            )
            for row in range(3)
            for column in range(3)
        )
        determinant = (
            rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
            - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
            + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
        )
        if (
            tuple(transform[3]) != (0.0, 0.0, 0.0, 1.0)
            or not orthonormal
            or not math.isclose(determinant, 1.0, abs_tol=1e-6)
        ):
            raise ValueError("base_T_anchor must be a rigid transform")
        object.__setattr__(self, "base_T_anchor", transform)
        if self.video_channel is not None and (
            not isinstance(self.video_channel, str) or not self.video_channel
        ):
            raise ValueError("video_channel must be a nonempty string or None")
        if self.video_expected_source is not None and not isinstance(
            self.video_expected_source, str
        ):
            raise TypeError("video_expected_source must be a string or None")
        for name in ("video_width", "video_height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


def _default_reader_factory(config: CloudXRSourceConfig) -> CloudXRReader:
    try:
        from lerobot.teleoperators.xr_controllers import XRControllers, XRControllersConfig
    except ImportError as exc:
        raise CloudXRDependencyError(
            "CloudXRSource requires the supported LeRobot XRControllers integration; "
            "install the pinned G1 VR environment or inject reader_factory"
        ) from exc

    controller_config = XRControllersConfig(
        app_name=config.app_name,
        base_T_anchor=[list(row) for row in config.base_T_anchor],
    )
    if config.video_channel is None:
        return XRControllers(controller_config)
    try:
        from lerobot.teleoperators.xr_controllers.camera_display import VideoConfig
        from lerobot.teleoperators.xr_controllers.video_session import VideoControllerSession
    except ImportError as exc:
        raise CloudXRDependencyError(
            "CloudXR video requires the supported LeRobot video-session integration"
        ) from exc
    video = VideoConfig(
        channel=config.video_channel,
        width=config.video_width,
        height=config.video_height,
        expected_source=config.video_expected_source,
    )
    return XRControllers(
        controller_config,
        session_factory=partial(VideoControllerSession, video=video),
    )


def _json_compatible(value: object) -> object:
    """Copy common SDK scalars/arrays without importing NumPy."""

    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if value is None or isinstance(value, str | bool | int):
        return value
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _json_compatible(tolist())
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_compatible(item) for item in value]
    return repr(value)


def _controller_from_action(action: Mapping[str, object], side: str) -> XRController:
    try:
        tracked = action[f"{side}.tracked"]
        if not isinstance(tracked, bool) or not tracked:
            return XRController(False, None)
        buttons = {
            key.removeprefix(f"{side}.button."): value
            for key, value in action.items()
            if key.startswith(f"{side}.button.")
        }
        return XRController(
            True,
            XRPose(action[f"{side}.grip_pos"], action[f"{side}.grip_quat"]),
            squeeze=action[f"{side}.squeeze"],
            trigger=action[f"{side}.trigger"],
            buttons=buttons,
        )
    except (KeyError, TypeError, ValueError):
        return XRController(False, None)


class CloudXRSource(XRInputSource):
    """Normalize the existing LeRobot CloudXR controller reader."""

    def __init__(
        self,
        config: CloudXRSourceConfig | None = None,
        *,
        reader_factory: Callable[[CloudXRSourceConfig], CloudXRReader] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config or CloudXRSourceConfig()
        self._reader_factory = reader_factory or _default_reader_factory
        self.clock = clock or SystemClock()
        self._reader: CloudXRReader | None = None
        self._sequence = 0
        self._status = XRSourceStatus(XRSourceState.DISCONNECTED, "CloudXR not connected")
        self._last_raw_action: Mapping[str, object] | None = None

    @property
    def is_connected(self) -> bool:
        return self._reader is not None

    @property
    def status(self) -> XRSourceStatus:
        return self._status

    @property
    def last_raw_action(self) -> Mapping[str, object] | None:
        return deepcopy(self._last_raw_action)

    def connect(self) -> None:
        if self.is_connected:
            raise RuntimeError("CloudXR source is already connected")
        reader = self._reader_factory(self.config)
        try:
            reader.connect()
        except BaseException:
            reader.disconnect()
            raise
        self._reader = reader
        self._sequence = 0
        self._status = XRSourceStatus(XRSourceState.READY, "CloudXR reader connected")

    def sample(self) -> XRSample:
        if self._reader is None:
            raise XRSourceNotConnectedError("CloudXR source is not connected")
        try:
            action = self._reader.get_action()
        except Exception:
            self._status = XRSourceStatus(
                XRSourceState.STALE,
                "CloudXR reader failed",
                "Disconnect and reconnect the CloudXR session",
            )
            raise
        if not isinstance(action, Mapping):
            self._status = XRSourceStatus(
                XRSourceState.STALE,
                "CloudXR reader returned a non-mapping action",
                "Disconnect and reconnect the CloudXR session",
            )
            raise TypeError("CloudXR reader action must be a mapping")
        self._last_raw_action = {str(key): _json_compatible(item) for key, item in action.items()}
        now = self.clock.now()
        try:
            captured_at_s = float(action["captured_at"])
            age_s = now - captured_at_s
            fresh = (
                math.isfinite(captured_at_s)
                and math.isfinite(now)
                and 0.0 <= age_s <= self.config.max_age_s
            )
        except (KeyError, TypeError, ValueError):
            captured_at_s = now
            fresh = False
        if not fresh:
            # The vendor timestamp remains in last_raw_action. Normalized samples
            # must carry a finite host time even when their source status is stale.
            captured_at_s = now

        invalid_sides: list[str] = []
        controllers: dict[str, XRController] = {}
        for side in ("left", "right"):
            controller = (
                _controller_from_action(action, side) if fresh else XRController(False, None)
            )
            controllers[side] = controller
            declared_tracking = action.get(f"{side}.tracked")
            if fresh and (
                not isinstance(declared_tracking, bool)
                or (declared_tracking and not controller.tracked)
            ):
                invalid_sides.append(side)

        if not fresh:
            status = XRSourceStatus(
                XRSourceState.STALE,
                "CloudXR controller sample is missing, future, or stale",
                "Disconnect and reconnect the CloudXR session",
            )
        elif invalid_sides:
            status = XRSourceStatus(
                XRSourceState.READY,
                f"Invalid controller data: {', '.join(invalid_sides)}",
            )
        else:
            status = XRSourceStatus(XRSourceState.READY)
        sample = XRSample(
            sequence=self._sequence,
            captured_at_s=captured_at_s,
            left=controllers["left"],
            right=controllers["right"],
            status=status,
        )
        self._sequence += 1
        self._status = status
        return sample

    def disconnect(self) -> None:
        reader, self._reader = self._reader, None
        self._status = XRSourceStatus(XRSourceState.DISCONNECTED, "CloudXR disconnected")
        if reader is not None:
            reader.disconnect()
