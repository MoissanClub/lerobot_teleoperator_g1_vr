"""Composable VR input and G1 retargeting for LeRobot."""

from .interaction import XRInteractionConfig, XRInteractionGuard
from .retargeting import (
    G1RetargetDiagnostics,
    G1Retargeter,
    G1RetargeterConfig,
    G1RetargetingDependencyError,
    G1RetargetResult,
    G129Retargeter,
)
from .xr import (
    AdvanceableClock,
    Clock,
    CloudXRDependencyError,
    CloudXRReader,
    CloudXRSource,
    CloudXRSourceConfig,
    DeterministicClock,
    ReplayMode,
    SystemClock,
    TraceFrame,
    TraceManifestSeed,
    TraceReader,
    TraceRecorder,
    TraceReplaySource,
    XRController,
    XRInputSource,
    XRoboToolkitDependencyError,
    XRoboToolkitSDK,
    XRoboToolkitSource,
    XRoboToolkitSourceConfig,
    XRPose,
    XRSample,
    XRSourceKind,
    XRSourceNotConnectedError,
    XRSourceSelection,
    XRSourceState,
    XRSourceStatus,
    XRTraceError,
    XRTraceExhaustedError,
    XRTraceIntegrityError,
    XRTrackedPose,
    build_xr_source,
    sample_from_dict,
    sample_to_dict,
)

__all__ = [
    "AdvanceableClock",
    "Clock",
    "CloudXRDependencyError",
    "CloudXRReader",
    "CloudXRSource",
    "CloudXRSourceConfig",
    "DeterministicClock",
    "G1RetargetDiagnostics",
    "G1RetargetResult",
    "G1Retargeter",
    "G1RetargeterConfig",
    "G1RetargetingDependencyError",
    "G129Retargeter",
    "ReplayMode",
    "SystemClock",
    "TraceFrame",
    "TraceManifestSeed",
    "TraceReader",
    "TraceRecorder",
    "TraceReplaySource",
    "XRController",
    "XRInputSource",
    "XRInteractionConfig",
    "XRInteractionGuard",
    "XRPose",
    "XRSample",
    "XRSourceKind",
    "XRSourceNotConnectedError",
    "XRSourceSelection",
    "XRSourceState",
    "XRSourceStatus",
    "XRTraceError",
    "XRTraceExhaustedError",
    "XRTraceIntegrityError",
    "XRTrackedPose",
    "XRoboToolkitDependencyError",
    "XRoboToolkitSDK",
    "XRoboToolkitSource",
    "XRoboToolkitSourceConfig",
    "build_xr_source",
    "sample_from_dict",
    "sample_to_dict",
]

# LeRobot discovers third-party plugins by importing the distribution package.
# Keep the core contracts importable without LeRobot, but register when it exists.
try:
    from .lerobot_plugin import G1VRTeleoperator, G1VRTeleoperatorConfig
except ModuleNotFoundError as exc:
    if exc.name != "lerobot":
        raise
else:
    __all__ += ["G1VRTeleoperator", "G1VRTeleoperatorConfig"]

__version__ = "0.1.0"
