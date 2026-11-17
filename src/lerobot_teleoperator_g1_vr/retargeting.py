"""Source-independent G1 VR retargeting contracts and G1-29 adapter."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from .xr.clock import Clock, SystemClock
from .xr.types import XRSample


class G1RetargetingDependencyError(ImportError):
    """The supported LeRobot G1 Cartesian/XR implementation is unavailable."""


@dataclass(frozen=True, slots=True)
class G1RetargeterConfig:
    urdf_path: str | Path
    embodiment: str = "g1_29"
    clutch_threshold: float = 0.5
    max_sample_age_s: float = 0.25
    translation_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.embodiment != "g1_29":
            raise NotImplementedError(
                f"{self.embodiment!r} retargeting is not implemented; use g1_29"
            )
        object.__setattr__(self, "urdf_path", Path(self.urdf_path))
        if not math.isfinite(self.clutch_threshold) or not 0 < self.clutch_threshold <= 1:
            raise ValueError("clutch_threshold must be in (0, 1]")
        for name in ("max_sample_age_s", "translation_scale"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class G1RetargetDiagnostics:
    embodiment: str
    source_state: str
    left_engaged: bool
    right_engaged: bool
    held: bool
    ik_status: str | None = None
    converged: bool | None = None
    position_error_m: tuple[float, float] | None = None
    orientation_error_rad: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class G1RetargetResult:
    action: Mapping[str, float]
    diagnostics: G1RetargetDiagnostics

    def __post_init__(self) -> None:
        copied: dict[str, float] = {}
        for key, value in self.action.items():
            if not isinstance(key, str) or not key.endswith(".q"):
                raise ValueError("retargeted action keys must be named joint positions")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("retargeted actions must be finite")
            copied[key] = numeric
        object.__setattr__(self, "action", MappingProxyType(copied))


@runtime_checkable
class G1Retargeter(Protocol):
    @property
    def embodiment(self) -> str: ...

    @property
    def action_features(self) -> Mapping[str, type]: ...

    def reset(self) -> None: ...

    def retarget(self, sample: XRSample, measured_arm_q: Sequence[float]) -> G1RetargetResult: ...


class _Kinematics(Protocol):
    size: int

    def arm_action(self, q: Sequence[float]) -> Mapping[str, float]: ...


class _XRControl(Protocol):
    engaged: tuple[bool, bool]
    last_result: object | None

    def reset(self) -> None: ...

    def action(
        self, sample: Mapping[str, object], measured: Sequence[float], *, now: float
    ) -> Mapping[str, float]: ...


ComponentsFactory = Callable[[G1RetargeterConfig], tuple[_Kinematics, _XRControl]]


def _default_components(config: G1RetargeterConfig) -> tuple[_Kinematics, _XRControl]:
    try:
        from lerobot.robots.unitree_g1.g1_cartesian_control import (
            G1ArmKinematics,
            G1CartesianConfig,
        )
        from lerobot.robots.unitree_g1.g1_xr_control import G1XRControl
    except ImportError as exc:
        raise G1RetargetingDependencyError(
            "G1-29 retargeting requires the supported LeRobot G1 Cartesian/XR integration"
        ) from exc
    kinematics = G1ArmKinematics(G1CartesianConfig(config.embodiment, config.urdf_path))
    control = G1XRControl(
        kinematics,
        threshold=config.clutch_threshold,
        max_age=config.max_sample_age_s,
        translation_scale=config.translation_scale,
    )
    return kinematics, control


def _finite_vector(values: Sequence[float], size: int) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise TypeError("measured_arm_q must be a sequence of real values") from exc
    if len(result) != size or not all(math.isfinite(value) for value in result):
        raise ValueError(f"measured_arm_q must contain {size} finite values")
    return result


def _pair(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if len(result) != 2 or not all(math.isfinite(item) for item in result):
        return None
    return result


class G129Retargeter(G1Retargeter):
    """Thin source-neutral adapter over LeRobot's established G1-29 XR control."""

    ARM_DOF = 14

    def __init__(
        self,
        config: G1RetargeterConfig,
        *,
        components_factory: ComponentsFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.clock = clock or SystemClock()
        self.kinematics, self.control = (components_factory or _default_components)(config)
        if self.kinematics.size != self.ARM_DOF:
            raise ValueError(
                f"G1-29 retargeting requires {self.ARM_DOF} arm joints, got {self.kinematics.size}"
            )
        zero_action = self.kinematics.arm_action((0.0,) * self.ARM_DOF)
        if len(zero_action) != self.ARM_DOF or any(
            not isinstance(key, str) or not key.endswith(".q") for key in zero_action
        ):
            raise ValueError("kinematics must expose 14 named arm joint actions")
        self._action_keys = tuple(zero_action)
        self._action_features = MappingProxyType(dict.fromkeys(self._action_keys, float))

    @property
    def embodiment(self) -> str:
        return self.config.embodiment

    @property
    def action_features(self) -> Mapping[str, type]:
        return self._action_features

    def reset(self) -> None:
        self.control.reset()

    def retarget(self, sample: XRSample, measured_arm_q: Sequence[float]) -> G1RetargetResult:
        if not isinstance(sample, XRSample):
            raise TypeError("sample must be an XRSample")
        measured = _finite_vector(measured_arm_q, self.ARM_DOF)
        action = self.control.action(sample.to_action_dict(), measured, now=self.clock.now())
        if set(action) != set(self._action_keys):
            raise ValueError("retargeted action keys do not match G1-29 arm features")
        engaged = tuple(bool(value) for value in self.control.engaged)
        if len(engaged) != 2:
            raise ValueError("XR control must report left/right engagement")
        result = self.control.last_result if any(engaged) else None
        diagnostics = G1RetargetDiagnostics(
            embodiment=self.embodiment,
            source_state=sample.status.state.value,
            left_engaged=engaged[0],
            right_engaged=engaged[1],
            held=not any(engaged),
            ik_status=getattr(result, "status", None),
            converged=getattr(result, "converged", None),
            position_error_m=_pair(getattr(result, "position_error_m", None)),
            orientation_error_rad=_pair(getattr(result, "orientation_error_rad", None)),
        )
        return G1RetargetResult(action, diagnostics)
