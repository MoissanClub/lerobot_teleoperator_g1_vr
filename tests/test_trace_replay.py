"""Deterministic and real-time trace source behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from synthetic_traces import scenarios

from lerobot_teleoperator_g1_vr import (
    DeterministicClock,
    ReplayMode,
    TraceManifestSeed,
    TraceReader,
    TraceRecorder,
    TraceReplaySource,
    XRInputSource,
    XRSourceNotConnectedError,
    XRSourceState,
    XRTraceExhaustedError,
)


def trace(tmp_path: Path, name: str = "reconnect") -> TraceReader:
    directory = tmp_path / name
    manifest = TraceManifestSeed(
        trace_id=f"trace-{name}",
        label=name,
        source_type="synthetic",
        source_adapter_revision="test-revision",
        coordinate_frame="test frame",
        created_at_utc="2026-11-16T20:00:00Z",
    )
    with TraceRecorder(directory, manifest) as recorder:
        for sample in scenarios()[name]:
            recorder.record(sample, {"sequence": sample.sequence})
    return TraceReader(directory)


def test_deterministic_replay_uses_trace_elapsed_time_on_injected_clock(tmp_path):
    clock = DeterministicClock(50.0)
    source = TraceReplaySource(trace(tmp_path, "idle"), clock=clock)
    assert isinstance(source, XRInputSource)
    source.connect()
    first = source.sample()
    second = source.sample()
    assert first.captured_at_s == 50.0
    assert second.captured_at_s == pytest.approx(50.02)
    assert clock.now() == pytest.approx(50.02)
    assert first.source_timestamp_ns == 1
    assert second.source_timestamp_ns == 2


def test_realtime_replay_paces_samples_without_using_recorded_absolute_time(tmp_path):
    clock = DeterministicClock(500.0)
    source = TraceReplaySource(trace(tmp_path, "right"), mode=ReplayMode.REALTIME, clock=clock)
    source.connect()
    first = source.sample()
    second = source.sample()
    assert (first.captured_at_s, second.captured_at_s) == pytest.approx((500.0, 500.02))


def test_replay_preserves_status_transitions_and_restarts_after_reconnect(tmp_path):
    clock = DeterministicClock(10.0)
    source = TraceReplaySource(trace(tmp_path), clock=clock)
    assert not source.is_connected
    with pytest.raises(XRSourceNotConnectedError):
        source.sample()
    source.connect()
    assert [source.sample().status.state for _ in range(3)] == [
        XRSourceState.READY,
        XRSourceState.DISCONNECTED,
        XRSourceState.READY,
    ]
    with pytest.raises(XRTraceExhaustedError):
        source.sample()
    source.disconnect()
    assert source.status.state is XRSourceState.DISCONNECTED

    source.connect()
    assert source.sample().sequence == 0
    assert source.sample().captured_at_s == pytest.approx(10.3)


def test_replay_rejects_physical_target_before_connecting(tmp_path):
    with pytest.raises(ValueError, match="simulation targets only"):
        TraceReplaySource(trace(tmp_path), target="physical")


class NonAdvanceableClock:
    def now(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        pass


def test_deterministic_mode_requires_advanceable_clock(tmp_path):
    with pytest.raises(TypeError, match="AdvanceableClock"):
        TraceReplaySource(trace(tmp_path), clock=NonAdvanceableClock())
