"""Composable VR input and G1 retargeting for LeRobot."""

from .xr import (
    XRController,
    XRInputSource,
    XRPose,
    XRSample,
    XRSourceNotConnectedError,
    XRSourceState,
    XRSourceStatus,
    XRTrackedPose,
)

__all__ = [
    "XRController",
    "XRInputSource",
    "XRPose",
    "XRSample",
    "XRSourceNotConnectedError",
    "XRSourceState",
    "XRSourceStatus",
    "XRTrackedPose",
]

__version__ = "0.1.0"
