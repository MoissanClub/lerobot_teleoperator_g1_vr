"""CloudXR adapter tests without LeRobot, Isaac Teleop, OpenXR, GPU, or headset."""

from __future__ import annotations

import builtins
from collections.abc import Mapping

import pytest

from lerobot_teleoperator_g1_vr import (
    CloudXRDependencyError,
    CloudXRSource,
    CloudXRSourceConfig,
    DeterministicClock,
    XRInputSource,
    XRSourceNotConnectedError,
    XRSourceState,
)


def action(captured_at=10.0, **updates) -> dict[str, object]:
    result: dict[str, object] = {"captured_at": captured_at}
    for side, x in (("left", 1.0), ("right", 4.0)):
        result.update(
            {
                f"{side}.tracked": True,
                f"{side}.grip_pos": [x, x + 1, x + 2],
                f"{side}.grip_quat": [0, 0, 0, 2],
                f"{side}.squeeze": 0.75 if side == "left" else 0.5,
                f"{side}.trigger": 0.25 if side == "left" else 0.125,
            }
        )
    result.update(updates)
    return result


class FakeReader:
    def __init__(self, actions, *, connect_error=None, read_error=None) -> None:
        self.actions = list(actions)
        self.connect_error = connect_error
        self.read_error = read_error
        self.connect_calls = 0
        self.read_calls = 0
        self.disconnect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error

    def get_action(self) -> Mapping[str, object]:
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return self.actions[min(self.read_calls - 1, len(self.actions) - 1)]

    def disconnect(self) -> None:
        self.disconnect_calls += 1


def source(reader: FakeReader, *, clock=None, max_age_s=0.25) -> CloudXRSource:
    return CloudXRSource(
        CloudXRSourceConfig(max_age_s=max_age_s),
        reader_factory=lambda _: reader,
        clock=clock or DeterministicClock(10.0),
    )


def test_cloudxr_source_is_structural_input_source_and_reads_once_per_sample():
    reader = FakeReader([action()])
    actual = source(reader)
    assert isinstance(actual, XRInputSource)
    with pytest.raises(XRSourceNotConnectedError):
        actual.sample()
    actual.connect()
    sample = actual.sample()
    assert reader.read_calls == 1
    assert sample.sequence == 0
    assert sample.status.state is XRSourceState.READY
    assert sample.left.pose.position_m == (1.0, 2.0, 3.0)
    assert sample.left.pose.quaternion_xyzw == (0.0, 0.0, 0.0, 1.0)
    assert sample.right.pose.position_m == (4.0, 5.0, 6.0)


def test_normalized_action_matches_established_cloudxr_fields():
    legacy = action(**{"left.button.primary": 1.0})
    actual = source(FakeReader([legacy]))
    actual.connect()
    normalized = actual.sample().to_action_dict()
    for key in (
        "captured_at",
        "left.tracked",
        "left.grip_pos",
        "left.grip_quat",
        "left.squeeze",
        "left.trigger",
        "right.tracked",
        "right.grip_pos",
        "right.grip_quat",
        "right.squeeze",
        "right.trigger",
        "left.button.primary",
    ):
        expected = legacy[key]
        if isinstance(expected, list):
            expected = tuple(expected)
            if key.endswith("grip_quat"):
                expected = (0.0, 0.0, 0.0, 1.0)
        assert normalized[key] == expected


def test_invalid_controller_is_isolated_without_dropping_other_hand():
    malformed = action(**{"right.grip_quat": [0, 0, 0, 0]})
    actual = source(FakeReader([malformed]))
    actual.connect()
    sample = actual.sample()
    assert sample.left.tracked
    assert not sample.right.tracked
    assert sample.status.state is XRSourceState.READY
    assert sample.status.detail == "Invalid controller data: right"


def test_cached_frame_becomes_stale_and_clears_both_hands():
    clock = DeterministicClock(10.0)
    reader = FakeReader([action(9.9)])
    actual = source(reader, clock=clock, max_age_s=0.25)
    actual.connect()
    assert actual.sample().status.state is XRSourceState.READY
    clock.sleep(0.2)
    stale = actual.sample()
    assert stale.status.state is XRSourceState.STALE
    assert not stale.left.tracked
    assert not stale.right.tracked
    assert stale.left.squeeze == 0
    assert stale.right.squeeze == 0


@pytest.mark.parametrize("captured_at", [None, float("nan"), 11.0])
def test_missing_invalid_or_future_capture_time_is_stale(captured_at):
    candidate = action()
    if captured_at is None:
        candidate.pop("captured_at")
    else:
        candidate["captured_at"] = captured_at
    actual = source(FakeReader([candidate]))
    actual.connect()
    sample = actual.sample()
    assert sample.status.state is XRSourceState.STALE
    assert sample.captured_at_s == 10.0


def test_raw_snapshot_is_json_compatible_and_defensively_copied():
    legacy = action()
    actual = source(FakeReader([legacy]))
    actual.connect()
    actual.sample()
    snapshot = actual.last_raw_action
    assert snapshot["left.grip_pos"] == [1.0, 2.0, 3.0]
    snapshot["left.grip_pos"][0] = 99
    assert actual.last_raw_action["left.grip_pos"] == [1.0, 2.0, 3.0]


def test_connect_failure_cleans_reader_and_disconnect_is_idempotent():
    reader = FakeReader([], connect_error=RuntimeError("startup failed"))
    actual = source(reader)
    with pytest.raises(RuntimeError, match="startup failed"):
        actual.connect()
    assert reader.disconnect_calls == 1
    assert not actual.is_connected
    actual.disconnect()
    assert reader.disconnect_calls == 1


def test_read_failure_is_reported_stale_and_propagated():
    reader = FakeReader([], read_error=RuntimeError("worker failed"))
    actual = source(reader)
    actual.connect()
    with pytest.raises(RuntimeError, match="worker failed"):
        actual.sample()
    assert actual.status.state is XRSourceState.STALE
    assert "reconnect" in actual.status.recovery_hint.lower()


def test_disconnect_closes_reader_once_and_clears_connection():
    reader = FakeReader([action()])
    actual = source(reader)
    actual.connect()
    actual.disconnect()
    actual.disconnect()
    assert reader.disconnect_calls == 1
    assert not actual.is_connected
    assert actual.status.state is XRSourceState.DISCONNECTED


def test_optional_lerobot_import_is_delayed_until_default_connect(monkeypatch):
    actual_import = builtins.__import__

    def reject_lerobot(name, *args, **kwargs):
        if name.startswith("lerobot"):
            raise ImportError("deliberately unavailable")
        return actual_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_lerobot)
    actual = CloudXRSource(clock=DeterministicClock())
    with pytest.raises(CloudXRDependencyError, match="supported LeRobot"):
        actual.connect()


@pytest.mark.parametrize(
    "updates,error",
    [
        ({"max_age_s": 0}, ValueError),
        ({"base_T_anchor": ((1, 0),)}, ValueError),
        ({"base_T_anchor": ((0, 0, 0, 0),) * 4}, ValueError),
        ({"video_width": True}, ValueError),
        ({"video_channel": ""}, ValueError),
    ],
)
def test_cloudxr_config_rejects_invalid_values(updates, error):
    with pytest.raises(error):
        CloudXRSourceConfig(**updates)
