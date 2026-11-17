"""Explicit source selection and dependency-isolation tests."""

from __future__ import annotations

import pytest
from synthetic_traces import scenarios

from lerobot_teleoperator_g1_vr import (
    CloudXRSource,
    CloudXRSourceConfig,
    DeterministicClock,
    TraceManifestSeed,
    TraceRecorder,
    TraceReplaySource,
    XRoboToolkitSource,
    XRoboToolkitSourceConfig,
    XRSourceKind,
    XRSourceSelection,
    build_xr_source,
)


def write_trace(path):
    seed = TraceManifestSeed("selection", "selection", "synthetic", "test", "test")
    with TraceRecorder(path, seed) as recorder:
        for sample in scenarios()["idle"]:
            recorder.record(sample)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (XRSourceKind.CLOUDXR, CloudXRSource),
        (XRSourceKind.XROBOTOOLKIT, XRoboToolkitSource),
    ],
)
def test_live_selection_builds_exactly_one_unconnected_adapter(kind, expected):
    selected = build_xr_source(XRSourceSelection(kind))
    assert type(selected) is expected
    assert not selected.is_connected


def test_selection_passes_only_selected_vendor_dependency():
    def reader_factory(config):
        return None

    cloudxr = build_xr_source(XRSourceSelection("cloudxr"), cloudxr_reader_factory=reader_factory)
    assert cloudxr._reader_factory is reader_factory

    sdk = object()
    xrobotoolkit = build_xr_source(XRSourceSelection("xrobotoolkit"), xrobotoolkit_sdk=sdk)
    assert xrobotoolkit._injected_sdk is sdk


def test_trace_selection_loads_replay_without_live_dependencies(tmp_path):
    trace = tmp_path / "trace"
    write_trace(trace)
    selected = build_xr_source(
        XRSourceSelection("trace", trace_path=trace), clock=DeterministicClock()
    )
    assert type(selected) is TraceReplaySource
    selected.connect()
    assert selected.sample().sequence == 0


@pytest.mark.parametrize(
    "selection",
    [
        XRSourceSelection,
    ],
)
def test_factory_rejects_non_selection(selection):
    with pytest.raises(TypeError):
        build_xr_source(selection)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "trace"},
        {"kind": "trace", "trace_path": "trace", "cloudxr": CloudXRSourceConfig()},
        {"kind": "cloudxr", "xrobotoolkit": XRoboToolkitSourceConfig()},
        {"kind": "xrobotoolkit", "cloudxr": CloudXRSourceConfig()},
    ],
)
def test_selection_rejects_missing_or_mixed_configuration(kwargs):
    with pytest.raises(ValueError):
        XRSourceSelection(**kwargs)


def test_trace_selection_rejects_live_dependency(tmp_path):
    trace = tmp_path / "trace"
    write_trace(trace)
    with pytest.raises(ValueError, match="live-source"):
        build_xr_source(XRSourceSelection("trace", trace_path=trace), xrobotoolkit_sdk=object())
