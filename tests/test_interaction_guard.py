"""Deterministic fail-hold and re-clutch behavior shared by all XR sources."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lerobot_teleoperator_g1_vr import (
    DeterministicClock,
    XRController,
    XRInteractionConfig,
    XRInteractionGuard,
    XRPose,
    XRSample,
    XRSourceState,
    XRSourceStatus,
)


def controller(*, x=0.0, squeeze=0.0, tracked=True):
    return XRController(
        tracked,
        XRPose((x, 0, 0), (0, 0, 0, 1)) if tracked else None,
        squeeze=squeeze,
    )


def sample(
    sequence,
    captured_at_s,
    *,
    left=None,
    right=None,
    state=XRSourceState.READY,
    source_timestamp_ns=None,
    advanced=True,
):
    return XRSample(
        sequence=sequence,
        captured_at_s=captured_at_s,
        left=left or controller(),
        right=right or controller(),
        status=XRSourceStatus(state),
        source_timestamp_ns=source_timestamp_ns,
        source_timestamp_advanced=advanced,
    )


def test_fresh_sample_passes_without_source_specific_behavior():
    clock = DeterministicClock(10.0)
    guard = XRInteractionGuard(clock=clock)
    original = sample(0, 10.0, left=controller(squeeze=1.0), source_timestamp_ns=1)
    assert guard.process(original) == original
    assert guard.awaiting_release == (False, False)


@pytest.mark.parametrize(
    "candidate",
    [
        sample(0, 1.0),
        sample(0, 10.0, state=XRSourceState.STALE),
        sample(0, 10.0, state=XRSourceState.DISCONNECTED),
        sample(0, 10.0, source_timestamp_ns=1, advanced=False),
    ],
)
def test_stale_disconnected_or_frozen_input_disables_both_hands(candidate):
    clock = DeterministicClock(10.0)
    guard = XRInteractionGuard(clock=clock)
    guarded = guard.process(
        replace(candidate, left=controller(squeeze=1.0), right=controller(squeeze=1.0))
    )
    assert guarded.status.state is XRSourceState.STALE
    assert not guarded.left.tracked and not guarded.right.tracked
    assert guarded.left.squeeze == 0 and guarded.right.squeeze == 0
    assert guard.awaiting_release == (True, True)
    assert "release grip" in guarded.status.recovery_hint.lower()


def test_reconnect_at_large_offset_cannot_move_until_release_then_new_grip():
    clock = DeterministicClock(10.0)
    guard = XRInteractionGuard(clock=clock)
    guard.process(sample(0, 10.0, state=XRSourceState.DISCONNECTED))

    held = guard.process(
        sample(
            1,
            10.0,
            left=controller(x=100.0, squeeze=1.0),
            right=controller(x=-100.0, squeeze=1.0),
            source_timestamp_ns=1,
        )
    )
    assert held.left.tracked and held.right.tracked
    assert held.left.squeeze == 0 and held.right.squeeze == 0
    assert guard.awaiting_release == (True, True)

    released = guard.process(
        sample(2, 10.0, left=controller(x=100.0), right=controller(x=-100.0), source_timestamp_ns=2)
    )
    assert released.left.squeeze == 0 and released.right.squeeze == 0
    assert guard.awaiting_release == (False, False)

    reclutched = guard.process(
        sample(
            3,
            10.0,
            left=controller(x=100.0, squeeze=1.0),
            right=controller(x=-100.0, squeeze=1.0),
            source_timestamp_ns=3,
        )
    )
    assert reclutched.left.squeeze == 1 and reclutched.right.squeeze == 1


def test_each_hand_can_clear_recovery_latch_independently():
    clock = DeterministicClock(10.0)
    guard = XRInteractionGuard(clock=clock)
    guard.process(sample(0, 10.0, advanced=False))
    left_release = guard.process(
        sample(
            1,
            10.0,
            left=controller(squeeze=0.0),
            right=controller(squeeze=1.0),
            source_timestamp_ns=1,
        )
    )
    assert guard.awaiting_release == (False, True)
    assert left_release.right.squeeze == 0
    next_sample = guard.process(
        sample(
            2,
            10.0,
            left=controller(squeeze=1.0),
            right=controller(squeeze=1.0),
            source_timestamp_ns=2,
        )
    )
    assert next_sample.left.squeeze == 1
    assert next_sample.right.squeeze == 0


def test_backward_source_timestamp_forces_recovery():
    clock = DeterministicClock(10.0)
    guard = XRInteractionGuard(clock=clock)
    guard.process(sample(0, 10.0, source_timestamp_ns=10))
    backward = guard.process(sample(1, 10.0, source_timestamp_ns=9))
    assert backward.status.state is XRSourceState.STALE
    assert "backward" in backward.status.detail


def test_reset_clears_timestamp_and_recovery_latches():
    clock = DeterministicClock(10.0)
    guard = XRInteractionGuard(clock=clock)
    guard.process(sample(0, 10.0, advanced=False))
    guard.reset()
    assert guard.awaiting_release == (False, False)
    assert guard.process(sample(1, 10.0, source_timestamp_ns=0)).status.state is XRSourceState.READY


@pytest.mark.parametrize(
    "updates,error",
    [
        ({"max_age_s": 0}, ValueError),
        ({"clutch_threshold": 0}, ValueError),
        ({"clutch_threshold": 2}, ValueError),
        ({"reconnect_hint": ""}, ValueError),
    ],
)
def test_interaction_config_rejects_invalid_values(updates, error):
    with pytest.raises(error):
        XRInteractionConfig(**updates)
