"""Vendor-neutral XR source health values."""

from dataclasses import dataclass
from enum import StrEnum


class XRSourceState(StrEnum):
    """Connection/freshness state independent of a vendor SDK."""

    DISCONNECTED = "disconnected"
    STALE = "stale"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class XRSourceStatus:
    """Current source health and an optional operator-facing recovery hint."""

    state: XRSourceState
    detail: str = ""
    recovery_hint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, XRSourceState):
            raise TypeError("state must be an XRSourceState")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")
        if self.recovery_hint is not None and not isinstance(self.recovery_hint, str):
            raise TypeError("recovery_hint must be a string or None")
