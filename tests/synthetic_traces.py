"""Small source-independent traces used by recorder/replay tests."""

from __future__ import annotations

from lerobot_teleoperator_g1_vr import (
    XRController,
    XRPose,
    XRSample,
    XRSourceState,
    XRSourceStatus,
)


def controller(
    *,
    tracked: bool = True,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    squeeze: float = 0.0,
) -> XRController:
    return XRController(
        tracked,
        XRPose((x, y, z), (0.0, 0.0, 0.0, 1.0)) if tracked else None,
        squeeze=squeeze,
    )


def frame(
    sequence: int,
    captured_at_s: float,
    *,
    state: XRSourceState = XRSourceState.READY,
    left: XRController | None = None,
    right: XRController | None = None,
    source_timestamp_ns: int | None = None,
    source_timestamp_advanced: bool | None = True,
) -> XRSample:
    return XRSample(
        sequence=sequence,
        captured_at_s=captured_at_s,
        left=left or controller(),
        right=right or controller(),
        status=XRSourceStatus(state),
        source_timestamp_ns=source_timestamp_ns,
        source_timestamp_advanced=source_timestamp_advanced,
    )


def scenarios() -> dict[str, tuple[XRSample, ...]]:
    idle = (
        frame(0, 100.0, source_timestamp_ns=1),
        frame(1, 100.02, source_timestamp_ns=2),
    )
    right = (
        frame(0, 100.0, right=controller(squeeze=1.0), source_timestamp_ns=1),
        frame(1, 100.02, right=controller(x=0.02, squeeze=1.0), source_timestamp_ns=2),
    )
    left = (
        frame(0, 100.0, left=controller(squeeze=1.0), source_timestamp_ns=1),
        frame(1, 100.02, left=controller(y=0.02, squeeze=1.0), source_timestamp_ns=2),
    )
    bimanual = (
        frame(
            0,
            100.0,
            left=controller(squeeze=1.0),
            right=controller(squeeze=1.0),
            source_timestamp_ns=1,
        ),
        frame(
            1,
            100.02,
            left=controller(x=0.01, squeeze=1.0),
            right=controller(y=-0.01, squeeze=1.0),
            source_timestamp_ns=2,
        ),
    )
    release = (
        frame(0, 100.0, right=controller(squeeze=1.0), source_timestamp_ns=1),
        frame(1, 100.02, right=controller(x=0.02), source_timestamp_ns=2),
    )
    stale = (
        frame(0, 100.0, right=controller(squeeze=1.0), source_timestamp_ns=1),
        frame(
            1,
            100.5,
            state=XRSourceState.STALE,
            right=controller(tracked=False),
            source_timestamp_ns=1,
            source_timestamp_advanced=False,
        ),
    )
    reconnect = (
        frame(0, 100.0, source_timestamp_ns=1),
        frame(
            1,
            100.1,
            state=XRSourceState.DISCONNECTED,
            left=controller(tracked=False),
            right=controller(tracked=False),
            source_timestamp_ns=1,
            source_timestamp_advanced=False,
        ),
        frame(2, 100.2, source_timestamp_ns=1, source_timestamp_advanced=True),
    )
    return {
        "idle": idle,
        "right": right,
        "left": left,
        "bimanual": bimanual,
        "release": release,
        "stale": stale,
        "reconnect": reconnect,
    }
