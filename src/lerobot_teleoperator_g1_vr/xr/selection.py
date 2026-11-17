"""Explicit construction boundary for live and replay XR sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .clock import Clock
from .cloudxr import CloudXRReader, CloudXRSource, CloudXRSourceConfig
from .source import XRInputSource
from .trace import ReplayMode, TraceReplaySource
from .xrobotoolkit import XRoboToolkitSDK, XRoboToolkitSource, XRoboToolkitSourceConfig


class XRSourceKind(StrEnum):
    CLOUDXR = "cloudxr"
    XROBOTOOLKIT = "xrobotoolkit"
    TRACE = "trace"


@dataclass(frozen=True, slots=True)
class XRSourceSelection:
    """One source kind and only the configuration belonging to that kind."""

    kind: XRSourceKind | str
    cloudxr: CloudXRSourceConfig | None = None
    xrobotoolkit: XRoboToolkitSourceConfig | None = None
    trace_path: str | Path | None = None
    replay_mode: ReplayMode | str = ReplayMode.DETERMINISTIC

    def __post_init__(self) -> None:
        kind = XRSourceKind(self.kind)
        mode = ReplayMode(self.replay_mode)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "replay_mode", mode)
        if self.trace_path is not None:
            object.__setattr__(self, "trace_path", Path(self.trace_path))

        if kind is XRSourceKind.CLOUDXR:
            if self.xrobotoolkit is not None or self.trace_path is not None:
                raise ValueError("cloudxr selection contains settings for another source")
        elif kind is XRSourceKind.XROBOTOOLKIT:
            if self.cloudxr is not None or self.trace_path is not None:
                raise ValueError("xrobotoolkit selection contains settings for another source")
        elif self.cloudxr is not None or self.xrobotoolkit is not None:
            raise ValueError("trace selection contains settings for a live source")
        elif self.trace_path is None:
            raise ValueError("trace selection requires trace_path")


def build_xr_source(
    selection: XRSourceSelection,
    *,
    clock: Clock | None = None,
    cloudxr_reader_factory: Callable[[CloudXRSourceConfig], CloudXRReader] | None = None,
    xrobotoolkit_sdk: XRoboToolkitSDK | None = None,
) -> XRInputSource:
    """Build the selected adapter without connecting or probing other vendors."""

    if not isinstance(selection, XRSourceSelection):
        raise TypeError("selection must be an XRSourceSelection")
    if selection.kind is XRSourceKind.CLOUDXR:
        return CloudXRSource(
            selection.cloudxr,
            reader_factory=cloudxr_reader_factory,
            clock=clock,
        )
    if selection.kind is XRSourceKind.XROBOTOOLKIT:
        return XRoboToolkitSource(
            selection.xrobotoolkit,
            sdk=xrobotoolkit_sdk,
            clock=clock,
        )
    if cloudxr_reader_factory is not None or xrobotoolkit_sdk is not None:
        raise ValueError("trace selection cannot receive a live-source dependency")
    return TraceReplaySource(
        selection.trace_path,
        mode=selection.replay_mode,
        clock=clock,
    )
