"""Source-neutral XR value objects and source lifecycle."""

from .clock import AdvanceableClock, Clock, DeterministicClock, SystemClock
from .codec import sample_from_dict, sample_to_dict
from .source import XRInputSource, XRSourceNotConnectedError
from .status import XRSourceState, XRSourceStatus
from .trace import (
    ReplayMode,
    TraceFrame,
    TraceManifestSeed,
    TraceReader,
    TraceRecorder,
    TraceReplaySource,
    XRTraceError,
    XRTraceExhaustedError,
    XRTraceIntegrityError,
)
from .types import XRController, XRPose, XRSample, XRTrackedPose

__all__ = [
    "AdvanceableClock",
    "Clock",
    "DeterministicClock",
    "ReplayMode",
    "SystemClock",
    "TraceFrame",
    "TraceManifestSeed",
    "TraceReader",
    "TraceRecorder",
    "TraceReplaySource",
    "XRController",
    "XRInputSource",
    "XRPose",
    "XRSample",
    "XRSourceNotConnectedError",
    "XRSourceState",
    "XRSourceStatus",
    "XRTraceError",
    "XRTraceExhaustedError",
    "XRTraceIntegrityError",
    "XRTrackedPose",
    "sample_from_dict",
    "sample_to_dict",
]
