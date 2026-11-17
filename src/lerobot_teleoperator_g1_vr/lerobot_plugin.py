"""Standard LeRobot Teleoperator plugin for normalized G1-29 VR input."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lerobot.teleoperators import Teleoperator, TeleoperatorConfig

from .interaction import XRInteractionConfig, XRInteractionGuard
from .retargeting import G1Retargeter, G1RetargeterConfig, G129Retargeter
from .xr import (
    Clock,
    CloudXRSourceConfig,
    DeterministicClock,
    ReplayMode,
    SystemClock,
    XRInputSource,
    XRoboToolkitSourceConfig,
    XRSourceKind,
    XRSourceSelection,
    build_xr_source,
)


@TeleoperatorConfig.register_subclass("g1_vr")
@dataclass(kw_only=True)
class G1VRTeleoperatorConfig(TeleoperatorConfig):
    """CLI-serializable settings for the external G1 VR plugin."""

    urdf_path: Path
    source: str = "trace"
    trace_path: Path | None = None
    sdk_site_packages: Path | None = None
    cloudxr_app_name: str = "LeRobot G1 VR"
    clutch_threshold: float = 0.5
    max_sample_age_s: float = 0.25
    translation_scale: float = 1.0
    simulation_only: bool = True

    def __post_init__(self) -> None:
        self.source = XRSourceKind(self.source).value
        self.urdf_path = Path(self.urdf_path)
        if self.trace_path is not None:
            self.trace_path = Path(self.trace_path)
        if self.sdk_site_packages is not None:
            self.sdk_site_packages = Path(self.sdk_site_packages)
        if not self.simulation_only:
            raise ValueError(
                "G1VRTeleoperator is simulation-only until physical validation is approved"
            )


class G1VRTeleoperator(Teleoperator):
    """LeRobot action producer backed by CloudXR, XRoboToolkit, or a trace."""

    config_class = G1VRTeleoperatorConfig
    name = "g1_vr"

    def __init__(
        self,
        config: G1VRTeleoperatorConfig,
        *,
        source: XRInputSource | None = None,
        retargeter: G1Retargeter | None = None,
        guard: XRInteractionGuard | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(config)
        self.config = config
        kind = XRSourceKind(config.source)
        self.clock = clock or (
            DeterministicClock() if kind is XRSourceKind.TRACE else SystemClock()
        )
        selection = XRSourceSelection(
            kind,
            cloudxr=(
                CloudXRSourceConfig(
                    app_name=config.cloudxr_app_name,
                    max_age_s=config.max_sample_age_s,
                )
                if kind is XRSourceKind.CLOUDXR
                else None
            ),
            xrobotoolkit=(
                XRoboToolkitSourceConfig(
                    sdk_site_packages=config.sdk_site_packages,
                    stale_timeout_s=config.max_sample_age_s,
                )
                if kind is XRSourceKind.XROBOTOOLKIT
                else None
            ),
            trace_path=config.trace_path,
            replay_mode=ReplayMode.DETERMINISTIC,
        )
        self.source = source or build_xr_source(selection, clock=self.clock)
        self.retargeter = retargeter or G129Retargeter(
            G1RetargeterConfig(
                config.urdf_path,
                clutch_threshold=config.clutch_threshold,
                max_sample_age_s=config.max_sample_age_s,
                translation_scale=config.translation_scale,
            ),
            clock=self.clock,
        )
        self.guard = guard or XRInteractionGuard(
            XRInteractionConfig(
                max_age_s=config.max_sample_age_s,
                clutch_threshold=config.clutch_threshold,
            ),
            clock=self.clock,
        )
        self._measured_q: tuple[float, ...] | None = None

    @property
    def action_features(self) -> dict[str, type]:
        return dict(self.retargeter.action_features)

    @property
    def feedback_features(self) -> dict[str, type]:
        return dict(self.retargeter.action_features)

    @property
    def is_connected(self) -> bool:
        return self.source.is_connected

    @property
    def is_calibrated(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise RuntimeError("G1 VR teleoperator is already connected")
        self.guard.reset()
        self.retargeter.reset()
        self._measured_q = None
        self.source.connect()

    def calibrate(self) -> None:
        return None

    def configure(self) -> None:
        return None

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        if not self.is_connected:
            raise RuntimeError("G1 VR teleoperator is not connected")
        try:
            measured = tuple(float(feedback[key]) for key in self.action_features)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("feedback must contain all 14 G1-29 arm joint positions") from exc
        if not all(math.isfinite(value) for value in measured):
            raise ValueError("G1-29 arm feedback must be finite")
        self._measured_q = measured

    def get_action(self) -> dict[str, float]:
        if not self.is_connected:
            raise RuntimeError("G1 VR teleoperator is not connected")
        if self._measured_q is None:
            raise RuntimeError("send robot feedback before requesting a G1 VR action")
        sample = self.guard.process(self.source.sample())
        return dict(self.retargeter.retarget(sample, self._measured_q).action)

    def disconnect(self) -> None:
        self.source.disconnect()
        self._measured_q = None
