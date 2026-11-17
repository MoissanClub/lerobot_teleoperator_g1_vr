"""Trace schema, integrity, and normalized-sample round trips."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from synthetic_traces import scenarios

from lerobot_teleoperator_g1_vr import (
    TraceManifestSeed,
    TraceReader,
    TraceRecorder,
    XRTraceError,
    XRTraceIntegrityError,
    sample_from_dict,
    sample_to_dict,
)


def seed(label: str = "test") -> TraceManifestSeed:
    return TraceManifestSeed(
        trace_id=f"trace-{label}",
        label=label,
        source_type="synthetic",
        source_adapter_revision="test-revision",
        coordinate_frame="test right-handed frame",
        created_at_utc="2026-11-16T20:00:00Z",
    )


def record_trace(directory: Path, samples, *, raw_payloads=None) -> TraceReader:
    payloads = raw_payloads or [None] * len(samples)
    with TraceRecorder(directory, seed(directory.name)) as recorder:
        for sample, raw in zip(samples, payloads, strict=True):
            recorder.record(sample, raw)
    return TraceReader(directory)


def test_normalized_sample_json_codec_round_trip():
    original = scenarios()["bimanual"][1]
    assert sample_from_dict(sample_to_dict(original)) == original


@pytest.mark.parametrize("name", sorted(scenarios()))
def test_synthetic_scenarios_round_trip_with_manifest_and_hashes(tmp_path, name):
    original = scenarios()[name]
    reader = record_trace(
        tmp_path / name,
        original,
        raw_payloads=[{"vendor_sequence": item.sequence} for item in original],
    )
    assert tuple(frame.sample for frame in reader) == original
    assert reader.frames[0].elapsed_ns == 0
    assert reader.frames[-1].elapsed_ns == round(
        (original[-1].captured_at_s - original[0].captured_at_s) * 1_000_000_000
    )
    assert reader.manifest["sample_count"] == len(original)
    assert reader.manifest["position_unit"] == "metre"
    assert reader.manifest["quaternion_order"] == "xyzw"
    assert reader.manifest["transformed"] is False
    assert (tmp_path / name / "checksums.sha256").is_file()


def test_event_stream_records_only_source_state_transitions(tmp_path):
    directory = tmp_path / "events"
    samples = scenarios()["reconnect"]
    reader = record_trace(directory, samples)
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert [event["state"] for event in events] == ["ready", "disconnected", "ready"]
    assert reader.manifest["files"]["events.jsonl"]["records"] == 3


def test_raw_payload_is_copied_and_nonfinite_json_is_rejected(tmp_path):
    payload = {"pose": [1, 2, 3]}
    directory = tmp_path / "copied"
    with TraceRecorder(directory, seed()) as recorder:
        recorder.record(scenarios()["idle"][0], payload)
        payload["pose"][0] = 99
    raw = json.loads((directory / "raw.jsonl").read_text())
    assert raw["payload"] == {"pose": [1, 2, 3]}

    with (
        pytest.raises(TypeError, match="JSON-compatible"),
        TraceRecorder(tmp_path / "invalid", seed()) as recorder,
    ):
        recorder.record(scenarios()["idle"][0], {"bad": float("nan")})


def test_recorder_rejects_nonmonotonic_sequence_and_capture_time(tmp_path):
    first, second = scenarios()["idle"]
    with TraceRecorder(tmp_path / "sequence", seed()) as recorder:
        recorder.record(first)
        with pytest.raises(XRTraceError, match="sequences"):
            recorder.record(first)

    with TraceRecorder(tmp_path / "time", seed()) as recorder:
        recorder.record(second)
        with pytest.raises(XRTraceError, match="captured_at_s"):
            recorder.record(replace(first, sequence=2))


def test_reader_rejects_unsupported_schema_before_replay(tmp_path):
    directory = tmp_path / "schema"
    record_trace(directory, scenarios()["idle"])
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(XRTraceError, match="unsupported trace schema"):
        TraceReader(directory)


def test_reader_detects_normalized_trace_corruption(tmp_path):
    directory = tmp_path / "corrupt"
    record_trace(directory, scenarios()["idle"])
    normalized = directory / "normalized.jsonl"
    normalized.write_text(normalized.read_text().replace('"sequence":0', '"sequence":9', 1))
    with pytest.raises(XRTraceIntegrityError, match=r"normalized\.jsonl"):
        TraceReader(directory)


def test_empty_trace_is_not_finalized(tmp_path):
    directory = tmp_path / "empty"
    with pytest.raises(XRTraceError, match="empty"), TraceRecorder(directory, seed()):
        pass
    assert not (directory / "manifest.json").exists()
