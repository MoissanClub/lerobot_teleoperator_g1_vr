"""Immutable normalized XR samples.

Positions are metres. Quaternions are ordered ``[x, y, z, w]``. Host capture
time is monotonic seconds; a vendor source timestamp is preserved separately.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .status import XRSourceState, XRSourceStatus


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a real number, not bool")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _finite_tuple(value: Iterable[object], size: int, name: str) -> tuple[float, ...]:
    try:
        result = tuple(_finite_float(item, f"{name}[{index}]") for index, item in enumerate(value))
    except TypeError as exc:
        raise TypeError(f"{name} must be an iterable of {size} real numbers") from exc
    if len(result) != size:
        raise ValueError(f"{name} must contain exactly {size} values")
    return result


def _unit_interval(value: object, name: str) -> float:
    result = _finite_float(value, name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return result


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


@dataclass(frozen=True, slots=True)
class XRPose:
    """A finite position and unit quaternion in the normalized XR frame."""

    position_m: tuple[float, float, float]
    quaternion_xyzw: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        position = _finite_tuple(self.position_m, 3, "position_m")
        quaternion = _finite_tuple(self.quaternion_xyzw, 4, "quaternion_xyzw")
        norm = math.sqrt(sum(component * component for component in quaternion))
        if norm <= 1e-12:
            raise ValueError("quaternion_xyzw must have nonzero norm")
        object.__setattr__(self, "position_m", position)
        object.__setattr__(
            self,
            "quaternion_xyzw",
            tuple(component / norm for component in quaternion),
        )


@dataclass(frozen=True, slots=True)
class XRTrackedPose:
    """A pose that is present exactly when tracking is valid."""

    tracked: bool
    pose: XRPose | None

    def __post_init__(self) -> None:
        if not isinstance(self.tracked, bool):
            raise TypeError("tracked must be a bool")
        if self.tracked != (self.pose is not None):
            raise ValueError("pose must be present exactly when tracked is true")
        if self.pose is not None and not isinstance(self.pose, XRPose):
            raise TypeError("pose must be an XRPose or None")


@dataclass(frozen=True, slots=True)
class XRController(XRTrackedPose):
    """Tracked controller pose plus normalized analog/button values."""

    squeeze: float = 0.0
    trigger: float = 0.0
    buttons: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super(XRController, self).__post_init__()
        object.__setattr__(self, "squeeze", _unit_interval(self.squeeze, "squeeze"))
        object.__setattr__(self, "trigger", _unit_interval(self.trigger, "trigger"))
        if not isinstance(self.buttons, Mapping):
            raise TypeError("buttons must be a mapping")
        copied: dict[str, float] = {}
        for name, value in self.buttons.items():
            if not isinstance(name, str) or not name:
                raise ValueError("button names must be nonempty strings")
            copied[name] = _unit_interval(value, f"buttons[{name!r}]")
        object.__setattr__(self, "buttons", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class XRSample:
    """One immutable, source-independent bimanual XR sample."""

    sequence: int
    captured_at_s: float
    left: XRController
    right: XRController
    status: XRSourceStatus
    head: XRTrackedPose = field(default_factory=lambda: XRTrackedPose(False, None))
    source_timestamp_ns: int | None = None
    source_timestamp_advanced: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence", _nonnegative_int(self.sequence, "sequence"))
        captured = _finite_float(self.captured_at_s, "captured_at_s")
        if captured < 0:
            raise ValueError("captured_at_s must be nonnegative")
        object.__setattr__(self, "captured_at_s", captured)
        for name in ("left", "right"):
            if not isinstance(getattr(self, name), XRController):
                raise TypeError(f"{name} must be an XRController")
        if not isinstance(self.head, XRTrackedPose):
            raise TypeError("head must be an XRTrackedPose")
        if not isinstance(self.status, XRSourceStatus):
            raise TypeError("status must be an XRSourceStatus")
        if self.source_timestamp_ns is not None:
            object.__setattr__(
                self,
                "source_timestamp_ns",
                _nonnegative_int(self.source_timestamp_ns, "source_timestamp_ns"),
            )
        if self.source_timestamp_advanced is not None and not isinstance(
            self.source_timestamp_advanced, bool
        ):
            raise TypeError("source_timestamp_advanced must be a bool or None")

    @classmethod
    def disconnected(cls, sequence: int, captured_at_s: float, detail: str = "") -> XRSample:
        """Create a deterministic no-tracking sample for a disconnected source."""

        controller = XRController(False, None)
        return cls(
            sequence=sequence,
            captured_at_s=captured_at_s,
            left=controller,
            right=controller,
            status=XRSourceStatus(XRSourceState.DISCONNECTED, detail),
        )

    def to_action_dict(self) -> dict[str, object]:
        """Return the flat field names consumed by the established G1 XR control."""

        result: dict[str, object] = {
            "captured_at": self.captured_at_s,
            "source_timestamp_ns": self.source_timestamp_ns,
            "source_timestamp_advanced": self.source_timestamp_advanced,
            "head.tracked": self.head.tracked,
            "head.position": self.head.pose.position_m if self.head.pose else (0.0, 0.0, 0.0),
            "head.quaternion": (
                self.head.pose.quaternion_xyzw if self.head.pose else (0.0, 0.0, 0.0, 1.0)
            ),
        }
        for side, controller in (("left", self.left), ("right", self.right)):
            result.update(
                {
                    f"{side}.tracked": controller.tracked,
                    f"{side}.grip_pos": (
                        controller.pose.position_m if controller.pose else (0.0, 0.0, 0.0)
                    ),
                    f"{side}.grip_quat": (
                        controller.pose.quaternion_xyzw if controller.pose else (0.0, 0.0, 0.0, 1.0)
                    ),
                    f"{side}.squeeze": controller.squeeze,
                    f"{side}.trigger": controller.trigger,
                }
            )
            result.update(
                {f"{side}.button.{name}": value for name, value in controller.buttons.items()}
            )
        return result
