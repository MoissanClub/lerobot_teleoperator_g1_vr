"""Vendor-free G1-29 retargeter contract tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from lerobot_teleoperator_g1_vr import (
    DeterministicClock,
    G1Retargeter,
    G1RetargeterConfig,
    G129Retargeter,
    XRController,
    XRPose,
    XRSample,
    XRSourceState,
    XRSourceStatus,
)


class FakeKinematics:
    size = 14
    keys = tuple(
        [f"left_joint_{index}.q" for index in range(7)]
        + [f"right_joint_{index}.q" for index in range(7)]
    )

    def arm_action(self, q):
        return dict(zip(self.keys, q, strict=True))


@dataclass
class FakeIKResult:
    status: str = "success"
    converged: bool = True
    position_error_m: tuple[float, float] = (0.001, 0.002)
    orientation_error_rad: tuple[float, float] = (0.01, 0.02)


class FakeControl:
    def __init__(self, kinematics):
        self.kinematics = kinematics
        self.engaged = (False, False)
        self.last_result = None
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1
        self.engaged = (False, False)
        self.last_result = None

    def action(self, sample, measured, *, now):
        self.engaged = (
            sample["left.tracked"] and sample["left.squeeze"] >= 0.5,
            sample["right.tracked"] and sample["right.squeeze"] >= 0.5,
        )
        values = list(measured)
        if self.engaged[0]:
            values[0] += sample["left.grip_pos"][0]
        if self.engaged[1]:
            values[7] += sample["right.grip_pos"][0]
        self.last_result = FakeIKResult() if any(self.engaged) else None
        return self.kinematics.arm_action(values)


def controller(*, tracked=True, x=0.0, squeeze=0.0):
    return XRController(
        tracked,
        XRPose((x, 0, 0), (0, 0, 0, 1)) if tracked else None,
        squeeze=squeeze,
    )


def sample(*, left=None, right=None, state=XRSourceState.READY):
    return XRSample(
        sequence=0,
        captured_at_s=10.0,
        left=left or controller(),
        right=right or controller(),
        status=XRSourceStatus(state),
    )


def make_retargeter(*, kinematics=None, control=None):
    kinematics = kinematics or FakeKinematics()
    control = control or FakeControl(kinematics)
    result = G129Retargeter(
        G1RetargeterConfig("/tmp/g1_29.urdf"),
        components_factory=lambda _: (kinematics, control),
        clock=DeterministicClock(10.0),
    )
    return result, control


def test_retargeter_is_structural_and_exposes_14_named_actions():
    actual, _ = make_retargeter()
    assert isinstance(actual, G1Retargeter)
    assert actual.embodiment == "g1_29"
    assert len(actual.action_features) == 14
    assert all(key.endswith(".q") and kind is float for key, kind in actual.action_features.items())


def test_released_controllers_hold_measured_arm_state():
    actual, _ = make_retargeter()
    measured = tuple(index / 100 for index in range(14))
    result = actual.retarget(sample(), measured)
    assert tuple(result.action.values()) == measured
    assert result.diagnostics.held
    assert not result.diagnostics.left_engaged
    assert not result.diagnostics.right_engaged
    assert result.diagnostics.ik_status is None


def test_left_right_and_bimanual_actions_are_isolated_and_diagnostic():
    actual, _ = make_retargeter()
    measured = (0.0,) * 14
    left = actual.retarget(sample(left=controller(x=0.1, squeeze=1.0)), measured)
    assert left.action["left_joint_0.q"] == 0.1
    assert left.action["right_joint_0.q"] == 0.0
    assert left.diagnostics.left_engaged and not left.diagnostics.right_engaged

    both = actual.retarget(
        sample(left=controller(x=0.1, squeeze=1.0), right=controller(x=-0.2, squeeze=1.0)),
        measured,
    )
    assert both.action["left_joint_0.q"] == 0.1
    assert both.action["right_joint_0.q"] == -0.2
    assert both.diagnostics.left_engaged and both.diagnostics.right_engaged
    assert both.diagnostics.converged
    assert both.diagnostics.position_error_m == (0.001, 0.002)


def test_reset_delegates_and_clears_engagement():
    actual, control = make_retargeter()
    actual.retarget(sample(left=controller(squeeze=1.0)), (0.0,) * 14)
    actual.reset()
    assert control.reset_calls == 1
    assert control.engaged == (False, False)


@pytest.mark.parametrize(
    "measured,error",
    [
        ((0.0,) * 13, ValueError),
        ((0.0,) * 13 + (float("nan"),), ValueError),
        (None, TypeError),
    ],
)
def test_measured_arm_state_must_be_14_finite_values(measured, error):
    actual, _ = make_retargeter()
    with pytest.raises(error):
        actual.retarget(sample(), measured)


def test_wrong_embodiment_and_wrong_kinematics_size_fail_before_control():
    with pytest.raises(NotImplementedError, match="g1_23"):
        G1RetargeterConfig("/tmp/g1_23.urdf", embodiment="g1_23")
    kinematics = FakeKinematics()
    kinematics.size = 10
    with pytest.raises(ValueError, match="14 arm joints"):
        make_retargeter(kinematics=kinematics, control=FakeControl(kinematics))


def test_wrong_action_keys_and_nonfinite_action_are_rejected():
    class BadControl(FakeControl):
        def action(self, sample, measured, *, now):
            return {"wrong.q": 0.0}

    kinematics = FakeKinematics()
    actual, _ = make_retargeter(kinematics=kinematics, control=BadControl(kinematics))
    with pytest.raises(ValueError, match="keys"):
        actual.retarget(sample(), (0.0,) * 14)

    class NonfiniteControl(FakeControl):
        def action(self, sample, measured, *, now):
            result = self.kinematics.arm_action(measured)
            result["left_joint_0.q"] = float("nan")
            return result

    actual, _ = make_retargeter(kinematics=kinematics, control=NonfiniteControl(kinematics))
    with pytest.raises(ValueError, match="finite"):
        actual.retarget(sample(), (0.0,) * 14)
