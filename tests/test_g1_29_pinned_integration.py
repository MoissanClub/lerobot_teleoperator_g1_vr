"""Opt-in real G1-29 IK checks against the pinned LeRobot release."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lerobot_teleoperator_g1_vr import (
    DeterministicClock,
    G1RetargeterConfig,
    G129Retargeter,
    XRController,
    XRPose,
    XRSample,
    XRSourceState,
    XRSourceStatus,
)

pytest.importorskip("lerobot.robots.unitree_g1.g1_cartesian_control")
URDF = os.environ.get("G1_29_URDF")
pytestmark = pytest.mark.skipif(not URDF, reason="Set G1_29_URDF to the pinned model")


def controller(*, x=0.0, y=0.0, z=0.0, squeeze=0.0, tracked=True):
    return XRController(
        tracked,
        XRPose((x, y, z), (0, 0, 0, 1)) if tracked else None,
        squeeze=squeeze,
    )


def sample(sequence, captured_at_s, *, left=None, right=None, state=XRSourceState.READY):
    return XRSample(
        sequence=sequence,
        captured_at_s=captured_at_s,
        left=left or controller(),
        right=right or controller(),
        status=XRSourceStatus(state),
    )


def values(result, keys):
    return tuple(result.action[key] for key in keys)


def test_real_g1_29_ik_holds_and_isolates_right_controller_motion():
    assert Path(URDF).is_file()
    clock = DeterministicClock(10.0)
    retargeter = G129Retargeter(G1RetargeterConfig(URDF), clock=clock)
    keys = tuple(retargeter.action_features)
    assert len(keys) == 14
    measured = (0.0,) * 14

    released = retargeter.retarget(sample(0, clock.now()), measured)
    assert values(released, keys) == measured

    origin = retargeter.retarget(sample(1, clock.now(), right=controller(squeeze=1.0)), measured)
    measured = values(origin, keys)
    clock.sleep(0.02)
    moved = retargeter.retarget(
        sample(2, clock.now(), right=controller(x=0.02, z=0.02, squeeze=1.0)), measured
    )
    moved_q = values(moved, keys)
    assert max(abs(moved_q[index] - measured[index]) for index in range(7, 14)) > 1e-4
    assert moved_q[:7] == measured[:7]
    assert all(abs(value) < 10 for value in moved_q)

    clock.sleep(0.02)
    held = retargeter.retarget(
        sample(3, clock.now(), right=controller(x=1.0, squeeze=0.0)), moved_q
    )
    assert values(held, keys) == moved_q
    assert held.diagnostics.held


def test_real_g1_29_stale_sample_holds_both_arms():
    clock = DeterministicClock(10.0)
    retargeter = G129Retargeter(G1RetargeterConfig(URDF), clock=clock)
    keys = tuple(retargeter.action_features)
    measured = tuple(index / 100 for index in range(14))
    stale = retargeter.retarget(
        sample(
            0,
            1.0,
            left=controller(tracked=False),
            right=controller(tracked=False),
            state=XRSourceState.STALE,
        ),
        measured,
    )
    assert values(stale, keys) == measured
    assert stale.diagnostics.source_state == "stale"
    assert stale.diagnostics.held
