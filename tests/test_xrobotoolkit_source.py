"""XRoboToolkit source tests without a Quest, PC Service, or vendor SDK."""

from __future__ import annotations

import json

import pytest

from lerobot_teleoperator_g1_vr import (
    DeterministicClock,
    XRInputSource,
    XRoboToolkitSource,
    XRoboToolkitSourceConfig,
    XRSourceNotConnectedError,
    XRSourceState,
)


class FakeSDK:
    def __init__(self) -> None:
        self.timestamp_ns = 1_000
        self.left_pose = [1, 2, 3, 0, 0, 0, 2]
        self.right_pose = [4, 5, 6, 0, 0, 0, 1]
        self.left_grip = 0.75
        self.right_grip = 0.5
        self.left_trigger = 0.25
        self.right_trigger = 0.125
        self.init_calls = 0
        self.close_calls = 0
        self.read_error: Exception | None = None

    def init(self):
        self.init_calls += 1

    def close(self):
        self.close_calls += 1

    def _read(self, value):
        if self.read_error is not None:
            raise self.read_error
        return value

    def get_time_stamp_ns(self):
        return self._read(self.timestamp_ns)

    def get_headset_pose(self):
        return self._read([0, 1, 2, 0, 0, 0, 1])

    def get_left_controller_pose(self):
        return self._read(self.left_pose)

    def get_right_controller_pose(self):
        return self._read(self.right_pose)

    def get_left_grip(self):
        return self._read(self.left_grip)

    def get_right_grip(self):
        return self._read(self.right_grip)

    def get_left_trigger(self):
        return self._read(self.left_trigger)

    def get_right_trigger(self):
        return self._read(self.right_trigger)

    def get_X_button(self):
        return True


def make_source(sdk: FakeSDK, *, clock=None, timeout=0.5):
    return XRoboToolkitSource(
        XRoboToolkitSourceConfig(stale_timeout_s=timeout),
        sdk=sdk,
        clock=clock or DeterministicClock(10.0),
    )


def test_source_normalizes_sdk_values_and_is_structural_input_source():
    sdk = FakeSDK()
    source = make_source(sdk)
    assert isinstance(source, XRInputSource)
    with pytest.raises(XRSourceNotConnectedError):
        source.sample()
    source.connect()
    sample = source.sample()
    assert sample.status.state is XRSourceState.READY
    assert sample.sequence == 0
    assert sample.source_timestamp_ns == 1_000
    assert sample.source_timestamp_advanced is True
    assert sample.head.pose.position_m == (0.0, 1.0, 2.0)
    assert sample.left.pose.position_m == (1.0, 2.0, 3.0)
    assert sample.left.pose.quaternion_xyzw == (0.0, 0.0, 0.0, 1.0)
    assert sample.left.squeeze == 0.75
    assert sample.left.buttons["x"] == 1.0
    assert sample.right.pose.position_m == (4.0, 5.0, 6.0)


def test_unchanged_timestamp_has_grace_period_then_fails_closed():
    clock = DeterministicClock(10.0)
    source = make_source(FakeSDK(), clock=clock, timeout=0.5)
    source.connect()
    source.sample()
    clock.sleep(0.4)
    grace = source.sample()
    assert grace.status.state is XRSourceState.READY
    assert grace.source_timestamp_advanced is None
    clock.sleep(0.11)
    stale = source.sample()
    assert stale.status.state is XRSourceState.STALE
    assert not stale.left.tracked and not stale.right.tracked
    assert "Reconnect" in stale.status.recovery_hint


def test_timestamp_restart_fails_closed_immediately():
    sdk = FakeSDK()
    source = make_source(sdk)
    source.connect()
    source.sample()
    sdk.timestamp_ns = 999
    stale = source.sample()
    assert stale.status.state is XRSourceState.STALE
    assert stale.source_timestamp_advanced is False


def test_invalid_hand_data_is_isolated_from_other_hand():
    sdk = FakeSDK()
    sdk.right_grip = 2.0
    source = make_source(sdk)
    source.connect()
    sample = source.sample()
    assert sample.left.tracked
    assert not sample.right.tracked
    assert sample.status.state is XRSourceState.READY
    assert sample.status.detail == "Invalid controller data: right"


def test_sdk_read_failure_returns_stale_hold_sample():
    sdk = FakeSDK()
    source = make_source(sdk)
    source.connect()
    sdk.read_error = RuntimeError("service stopped")
    sample = source.sample()
    assert sample.status.state is XRSourceState.STALE
    assert not sample.left.tracked and not sample.right.tracked
    assert source.last_raw_action == {"error": "RuntimeError: service stopped"}


def test_raw_snapshot_is_json_compatible_and_defensively_copied():
    source = make_source(FakeSDK())
    source.connect()
    source.sample()
    snapshot = source.last_raw_action
    json.dumps(snapshot, allow_nan=False)
    snapshot["left_controller_pose"][0] = 99
    assert source.last_raw_action["left_controller_pose"][0] == 1


def test_connect_disconnect_lifecycle_is_idempotent():
    sdk = FakeSDK()
    source = make_source(sdk)
    source.connect()
    with pytest.raises(RuntimeError, match="already connected"):
        source.connect()
    source.disconnect()
    source.disconnect()
    assert sdk.init_calls == 1
    assert sdk.close_calls == 1
    assert source.status.state is XRSourceState.DISCONNECTED


@pytest.mark.parametrize("timeout", [0, -1, float("nan")])
def test_config_rejects_invalid_stale_timeout(timeout):
    with pytest.raises(ValueError):
        XRoboToolkitSourceConfig(stale_timeout_s=timeout)
