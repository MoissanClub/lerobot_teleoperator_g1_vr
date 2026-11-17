"""Lifecycle contract shared by live and recorded XR input sources."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .status import XRSourceStatus
from .types import XRSample


class XRSourceNotConnectedError(RuntimeError):
    """Raised when a sample is requested before the source is connected."""


@runtime_checkable
class XRInputSource(Protocol):
    """A vendor-neutral, record/replay-compatible XR sample producer."""

    @property
    def is_connected(self) -> bool: ...

    @property
    def status(self) -> XRSourceStatus: ...

    def connect(self) -> None: ...

    def sample(self) -> XRSample: ...

    def disconnect(self) -> None: ...
