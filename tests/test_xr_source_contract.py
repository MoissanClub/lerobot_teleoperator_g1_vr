"""Normalized XR contract tests without vendor SDKs or devices."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from lerobot_teleoperator_g1_vr import (
    XRController,
    XRInputSource,
    XRPose,
    XRSample,
    XRSourceNotConnectedError,
    XRSourceState,
    XRSourceStatus,
    XRTrackedPose,
)


def pose(position=(1.0, 2.0, 3.0), quaternion=(0.0, 0.0, 0.0, 2.0)) -> XRPose:
    return XRPose(position, quaternion)


def controller(*, tracked=True, squeeze=0.0, trigger=0.0, buttons=None) -> XRController:
    return XRController(
        tracked=tracked,
        pose=pose() if tracked else None,
        squeeze=squeeze,
        trigger=trigger,
        buttons={} if buttons is None else buttons,
    )


def sample(**updates) -> XRSample:
    values = {
        "sequence": 7,
        "captured_at_s": 12.5,
        "source_timestamp_ns": 42,
        "source_timestamp_advanced": True,
        "head": XRTrackedPose(True, pose((0, 1, 2))),
        "left": controller(squeeze=0.75, buttons={"primary": 1}),
        "right": controller(trigger=0.25),
        "status": XRSourceStatus(XRSourceState.READY),
    }
    values.update(updates)
    return XRSample(**values)


def test_pose_copies_values_and_normalizes_xyzw_quaternion():
    position = [1, 2, 3]
    quaternion = [0, 0, 0, 2]
    actual = XRPose(position, quaternion)
    position[0] = 99
    quaternion[3] = 99
    assert actual.position_m == (1.0, 2.0, 3.0)
    assert actual.quaternion_xyzw == (0.0, 0.0, 0.0, 1.0)
    with pytest.raises(FrozenInstanceError):
        actual.position_m = (0, 0, 0)


@pytest.mark.parametrize(
    "position,quaternion,error",
    [
        ([0, 0], [0, 0, 0, 1], ValueError),
        ([0, 0, 0], [0, 0, 1], ValueError),
        ([0, 0, math.nan], [0, 0, 0, 1], ValueError),
        ([0, 0, 0], [0, 0, 0, 0], ValueError),
        (None, [0, 0, 0, 1], TypeError),
    ],
)
def test_pose_rejects_invalid_shapes_and_values(position, quaternion, error):
    with pytest.raises(error):
        XRPose(position, quaternion)


@pytest.mark.parametrize(
    "tracked,tracked_pose",
    [(True, None), (False, pose())],
)
def test_tracking_flag_and_pose_presence_must_agree(tracked, tracked_pose):
    with pytest.raises(ValueError, match="exactly"):
        XRTrackedPose(tracked, tracked_pose)


@pytest.mark.parametrize("field,value", [("squeeze", -0.1), ("trigger", 1.1)])
def test_controller_rejects_analog_values_outside_unit_interval(field, value):
    kwargs = {field: value}
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        controller(**kwargs)


def test_controller_copies_buttons_into_immutable_mapping():
    buttons = {"primary": 1}
    actual = controller(buttons=buttons)
    buttons["primary"] = 0
    assert actual.buttons == {"primary": 1.0}
    with pytest.raises(TypeError):
        actual.buttons["primary"] = 0


@pytest.mark.parametrize(
    "updates,error",
    [
        ({"sequence": -1}, ValueError),
        ({"sequence": True}, TypeError),
        ({"captured_at_s": -0.1}, ValueError),
        ({"captured_at_s": math.inf}, ValueError),
        ({"source_timestamp_ns": -1}, ValueError),
        ({"source_timestamp_advanced": 1}, TypeError),
    ],
)
def test_sample_rejects_invalid_sequence_and_timestamps(updates, error):
    with pytest.raises(error):
        sample(**updates)


def test_disconnected_sample_has_no_tracking_or_analog_motion():
    actual = XRSample.disconnected(3, 4.5, "service unavailable")
    assert actual.status == XRSourceStatus(XRSourceState.DISCONNECTED, "service unavailable")
    assert not actual.left.tracked
    assert not actual.right.tracked
    action = actual.to_action_dict()
    assert action["left.squeeze"] == 0
    assert action["right.squeeze"] == 0
    assert action["left.grip_quat"] == (0.0, 0.0, 0.0, 1.0)


def test_flat_action_preserves_normalized_controller_and_head_fields():
    actual = sample().to_action_dict()
    assert actual["captured_at"] == 12.5
    assert actual["source_timestamp_ns"] == 42
    assert actual["head.position"] == (0.0, 1.0, 2.0)
    assert actual["left.grip_pos"] == (1.0, 2.0, 3.0)
    assert actual["left.grip_quat"] == (0.0, 0.0, 0.0, 1.0)
    assert actual["left.squeeze"] == 0.75
    assert actual["left.button.primary"] == 1.0
    assert actual["right.trigger"] == 0.25


class FakeSource:
    def __init__(self) -> None:
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def status(self) -> XRSourceStatus:
        state = XRSourceState.READY if self.connected else XRSourceState.DISCONNECTED
        return XRSourceStatus(state)

    def connect(self) -> None:
        self.connected = True

    def sample(self) -> XRSample:
        if not self.connected:
            raise XRSourceNotConnectedError
        return sample()

    def disconnect(self) -> None:
        self.connected = False


def test_protocol_is_structural_and_lifecycle_is_explicit():
    source = FakeSource()
    assert isinstance(source, XRInputSource)
    with pytest.raises(XRSourceNotConnectedError):
        source.sample()
    source.connect()
    assert source.is_connected
    assert source.status.state is XRSourceState.READY
    assert source.sample().sequence == 7
    source.disconnect()
    assert source.status.state is XRSourceState.DISCONNECTED
