"""JSON-compatible encoding for normalized XR samples."""

from __future__ import annotations

from collections.abc import Mapping

from .status import XRSourceState, XRSourceStatus
from .types import XRController, XRPose, XRSample, XRTrackedPose


def _pose_to_dict(value: XRTrackedPose) -> dict[str, object]:
    return {
        "tracked": value.tracked,
        "position_m": list(value.pose.position_m) if value.pose else None,
        "quaternion_xyzw": list(value.pose.quaternion_xyzw) if value.pose else None,
    }


def _pose_from_dict(value: Mapping[str, object]) -> XRTrackedPose:
    tracked = value.get("tracked")
    if not isinstance(tracked, bool):
        raise TypeError("tracked must be a bool")
    position = value.get("position_m")
    quaternion = value.get("quaternion_xyzw")
    pose = None if position is None and quaternion is None else XRPose(position, quaternion)
    return XRTrackedPose(tracked, pose)


def _controller_to_dict(value: XRController) -> dict[str, object]:
    return {
        **_pose_to_dict(value),
        "squeeze": value.squeeze,
        "trigger": value.trigger,
        "buttons": dict(value.buttons),
    }


def _controller_from_dict(value: Mapping[str, object]) -> XRController:
    tracked_pose = _pose_from_dict(value)
    buttons = value.get("buttons", {})
    if not isinstance(buttons, Mapping):
        raise TypeError("buttons must be a mapping")
    return XRController(
        tracked=tracked_pose.tracked,
        pose=tracked_pose.pose,
        squeeze=value.get("squeeze", 0.0),
        trigger=value.get("trigger", 0.0),
        buttons=buttons,
    )


def sample_to_dict(sample: XRSample) -> dict[str, object]:
    """Encode a normalized sample without source-specific values."""

    return {
        "sequence": sample.sequence,
        "captured_at_s": sample.captured_at_s,
        "source_timestamp_ns": sample.source_timestamp_ns,
        "source_timestamp_advanced": sample.source_timestamp_advanced,
        "status": {
            "state": sample.status.state.value,
            "detail": sample.status.detail,
            "recovery_hint": sample.status.recovery_hint,
        },
        "head": _pose_to_dict(sample.head),
        "left": _controller_to_dict(sample.left),
        "right": _controller_to_dict(sample.right),
    }


def sample_from_dict(value: Mapping[str, object]) -> XRSample:
    """Decode and validate a normalized sample."""

    status = value.get("status")
    if not isinstance(status, Mapping):
        raise TypeError("status must be a mapping")
    head = value.get("head")
    left = value.get("left")
    right = value.get("right")
    if not all(isinstance(item, Mapping) for item in (head, left, right)):
        raise TypeError("head, left, and right must be mappings")
    return XRSample(
        sequence=value.get("sequence"),
        captured_at_s=value.get("captured_at_s"),
        source_timestamp_ns=value.get("source_timestamp_ns"),
        source_timestamp_advanced=value.get("source_timestamp_advanced"),
        status=XRSourceStatus(
            XRSourceState(status.get("state")),
            detail=status.get("detail", ""),
            recovery_hint=status.get("recovery_hint"),
        ),
        head=_pose_from_dict(head),
        left=_controller_from_dict(left),
        right=_controller_from_dict(right),
    )
