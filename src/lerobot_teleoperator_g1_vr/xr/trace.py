"""Versioned XR trace recording, integrity validation, and replay."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import IO

from .clock import AdvanceableClock, Clock, DeterministicClock, SystemClock
from .codec import sample_from_dict, sample_to_dict
from .source import XRInputSource, XRSourceNotConnectedError
from .status import XRSourceState, XRSourceStatus
from .types import XRSample

TRACE_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
RAW_NAME = "raw.jsonl"
NORMALIZED_NAME = "normalized.jsonl"
EVENTS_NAME = "events.jsonl"
CHECKSUMS_NAME = "checksums.sha256"
DATA_NAMES = (RAW_NAME, NORMALIZED_NAME, EVENTS_NAME)


class XRTraceError(ValueError):
    """Base error for malformed or incompatible traces."""


class XRTraceIntegrityError(XRTraceError):
    """A trace file does not match its recorded hash."""


class XRTraceExhaustedError(EOFError):
    """No samples remain in a replay source."""


class ReplayMode(StrEnum):
    DETERMINISTIC = "deterministic"
    REALTIME = "realtime"


@dataclass(frozen=True, slots=True)
class TraceManifestSeed:
    """Capture identity known before samples are recorded."""

    trace_id: str
    label: str
    source_type: str
    source_adapter_revision: str
    coordinate_frame: str
    created_at_utc: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "trace_id",
            "label",
            "source_type",
            "source_adapter_revision",
            "coordinate_frame",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if self.created_at_utc is not None:
            if not isinstance(self.created_at_utc, str):
                raise TypeError("created_at_utc must be a string or None")
            try:
                parsed = datetime.fromisoformat(self.created_at_utc.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("created_at_utc must be ISO 8601") from exc
            if parsed.tzinfo is None:
                raise ValueError("created_at_utc must include a timezone")


@dataclass(frozen=True, slots=True)
class TraceFrame:
    elapsed_ns: int
    sample: XRSample

    def __post_init__(self) -> None:
        if isinstance(self.elapsed_ns, bool) or not isinstance(self.elapsed_ns, int):
            raise TypeError("elapsed_ns must be an integer")
        if self.elapsed_ns < 0:
            raise ValueError("elapsed_ns must be nonnegative")
        if not isinstance(self.sample, XRSample):
            raise TypeError("sample must be an XRSample")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_copy(value: object, name: str) -> object:
    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be finite JSON-compatible data") from exc


def _write_json_line(stream: IO[str], value: Mapping[str, object]) -> None:
    stream.write(json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


class TraceRecorder:
    """Record synchronized raw and normalized samples into a new trace directory."""

    def __init__(self, directory: str | Path, manifest: TraceManifestSeed) -> None:
        self.directory = Path(directory)
        self.seed = manifest
        self._streams: dict[str, IO[str]] = {}
        self._first_capture_s: float | None = None
        self._last_capture_s: float | None = None
        self._last_sequence: int | None = None
        self._last_state: XRSourceState | None = None
        self._sample_count = 0
        self._event_count = 0
        self._closed = False

    def __enter__(self) -> TraceRecorder:
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close(finalize=exc_type is None)

    def open(self) -> None:
        if self._streams or self._closed:
            raise RuntimeError("recorder cannot be opened more than once")
        self.directory.mkdir(parents=True, exist_ok=False)
        self._streams = {
            name: (self.directory / name).open("x", encoding="utf-8") for name in DATA_NAMES
        }

    def record(self, sample: XRSample, raw_payload: object = None) -> None:
        if not self._streams or self._closed:
            raise RuntimeError("recorder is not open")
        if not isinstance(sample, XRSample):
            raise TypeError("sample must be an XRSample")
        if self._last_sequence is not None and sample.sequence <= self._last_sequence:
            raise XRTraceError("sample sequences must increase strictly")
        if self._last_capture_s is not None and sample.captured_at_s < self._last_capture_s:
            raise XRTraceError("captured_at_s must be monotonic")
        if self._first_capture_s is None:
            self._first_capture_s = sample.captured_at_s
        elapsed_ns = round((sample.captured_at_s - self._first_capture_s) * 1_000_000_000)
        raw = _json_copy(raw_payload, "raw_payload")
        _write_json_line(
            self._streams[RAW_NAME],
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "sequence": sample.sequence,
                "elapsed_ns": elapsed_ns,
                "captured_at_s": sample.captured_at_s,
                "source_timestamp_ns": sample.source_timestamp_ns,
                "payload": raw,
            },
        )
        _write_json_line(
            self._streams[NORMALIZED_NAME],
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "sequence": sample.sequence,
                "elapsed_ns": elapsed_ns,
                "sample": sample_to_dict(sample),
            },
        )
        if sample.status.state is not self._last_state:
            _write_json_line(
                self._streams[EVENTS_NAME],
                {
                    "schema_version": TRACE_SCHEMA_VERSION,
                    "sequence": sample.sequence,
                    "elapsed_ns": elapsed_ns,
                    "state": sample.status.state.value,
                    "detail": sample.status.detail,
                    "recovery_hint": sample.status.recovery_hint,
                },
            )
            self._event_count += 1
            self._last_state = sample.status.state
        self._last_sequence = sample.sequence
        self._last_capture_s = sample.captured_at_s
        self._sample_count += 1

    def close(self, *, finalize: bool = True) -> None:
        if self._closed:
            return
        for stream in self._streams.values():
            stream.close()
        self._streams.clear()
        self._closed = True
        if not finalize:
            return
        if self._sample_count == 0:
            raise XRTraceError("cannot finalize an empty trace")
        files = {
            name: {
                "sha256": _sha256(self.directory / name),
                "records": self._sample_count if name != EVENTS_NAME else self._event_count,
            }
            for name in DATA_NAMES
        }
        created = self.seed.created_at_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        manifest = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": self.seed.trace_id,
            "label": self.seed.label,
            "source_type": self.seed.source_type,
            "source_adapter_revision": self.seed.source_adapter_revision,
            "created_at_utc": created,
            "coordinate_frame": self.seed.coordinate_frame,
            "position_unit": "metre",
            "quaternion_order": "xyzw",
            "sample_count": self._sample_count,
            "duration_ns": round(
                ((self._last_capture_s or 0.0) - (self._first_capture_s or 0.0)) * 1_000_000_000
            ),
            "transformed": False,
            "files": files,
        }
        manifest_path = self.directory / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        checksum_paths = (*DATA_NAMES, MANIFEST_NAME)
        (self.directory / CHECKSUMS_NAME).write_text(
            "".join(f"{_sha256(self.directory / name)}  {name}\n" for name in checksum_paths)
        )


class TraceReader:
    """Load and validate a finalized normalized XR trace."""

    def __init__(self, directory: str | Path, *, verify_integrity: bool = True) -> None:
        self.directory = Path(directory)
        try:
            manifest = json.loads((self.directory / MANIFEST_NAME).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise XRTraceError("trace manifest is missing or invalid") from exc
        if manifest.get("schema_version") != TRACE_SCHEMA_VERSION:
            raise XRTraceError(
                f"unsupported trace schema version: {manifest.get('schema_version')!r}"
            )
        if verify_integrity:
            self._verify_integrity(manifest)
        self._manifest = MappingProxyType(manifest)
        self._frames = self._read_frames()
        if len(self._frames) != manifest.get("sample_count"):
            raise XRTraceError("manifest sample_count does not match normalized trace")

    @property
    def manifest(self) -> Mapping[str, object]:
        return self._manifest

    @property
    def frames(self) -> tuple[TraceFrame, ...]:
        return self._frames

    def __iter__(self) -> Iterator[TraceFrame]:
        return iter(self._frames)

    def _verify_integrity(self, manifest: Mapping[str, object]) -> None:
        files = manifest.get("files")
        if not isinstance(files, Mapping):
            raise XRTraceError("manifest files must be a mapping")
        for name in DATA_NAMES:
            entry = files.get(name)
            if not isinstance(entry, Mapping) or not isinstance(entry.get("sha256"), str):
                raise XRTraceError(f"manifest is missing hash for {name}")
            path = self.directory / name
            if not path.is_file() or _sha256(path) != entry["sha256"]:
                raise XRTraceIntegrityError(f"hash mismatch for {name}")
        checksums_path = self.directory / CHECKSUMS_NAME
        try:
            expected = {
                name: digest
                for digest, name in (
                    line.strip().split("  ", 1) for line in checksums_path.read_text().splitlines()
                )
            }
        except (OSError, ValueError) as exc:
            raise XRTraceIntegrityError("checksums.sha256 is missing or invalid") from exc
        for name in (*DATA_NAMES, MANIFEST_NAME):
            if expected.get(name) != _sha256(self.directory / name):
                raise XRTraceIntegrityError(f"checksum mismatch for {name}")

    def _read_frames(self) -> tuple[TraceFrame, ...]:
        frames: list[TraceFrame] = []
        last_elapsed = -1
        last_sequence = -1
        try:
            lines = (self.directory / NORMALIZED_NAME).read_text().splitlines()
            for line in lines:
                record = json.loads(line)
                if record.get("schema_version") != TRACE_SCHEMA_VERSION:
                    raise XRTraceError("normalized record schema version mismatch")
                elapsed = record.get("elapsed_ns")
                sample_value = record.get("sample")
                if not isinstance(sample_value, Mapping):
                    raise XRTraceError("normalized record sample must be a mapping")
                frame = TraceFrame(elapsed, sample_from_dict(sample_value))
                if record.get("sequence") != frame.sample.sequence:
                    raise XRTraceError("record/sample sequence mismatch")
                if frame.elapsed_ns < last_elapsed or frame.sample.sequence <= last_sequence:
                    raise XRTraceError("trace frames must be ordered")
                frames.append(frame)
                last_elapsed = frame.elapsed_ns
                last_sequence = frame.sample.sequence
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            if isinstance(exc, XRTraceError):
                raise
            raise XRTraceError("normalized trace is invalid") from exc
        if not frames:
            raise XRTraceError("normalized trace is empty")
        return tuple(frames)


class TraceReplaySource(XRInputSource):
    """Replay normalized samples through the standard XR input lifecycle."""

    def __init__(
        self,
        trace: TraceReader | str | Path,
        *,
        mode: ReplayMode | str = ReplayMode.DETERMINISTIC,
        clock: Clock | None = None,
        target: str = "simulation",
    ) -> None:
        if target != "simulation":
            raise ValueError("trace replay currently supports simulation targets only")
        self.reader = trace if isinstance(trace, TraceReader) else TraceReader(trace)
        self.mode = ReplayMode(mode)
        self.clock: Clock = clock or (
            DeterministicClock() if self.mode is ReplayMode.DETERMINISTIC else SystemClock()
        )
        if self.mode is ReplayMode.DETERMINISTIC and not isinstance(self.clock, AdvanceableClock):
            raise TypeError("deterministic replay requires an AdvanceableClock")
        self._connected = False
        self._index = 0
        self._started_at_s = 0.0
        self._status = XRSourceStatus(XRSourceState.DISCONNECTED, "trace not connected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> XRSourceStatus:
        return self._status

    def connect(self) -> None:
        if self._connected:
            raise RuntimeError("trace replay source is already connected")
        self._connected = True
        self._index = 0
        self._started_at_s = self.clock.now()
        self._status = XRSourceStatus(XRSourceState.READY, "trace replay ready")

    def sample(self) -> XRSample:
        if not self._connected:
            raise XRSourceNotConnectedError("trace replay source is not connected")
        if self._index >= len(self.reader.frames):
            raise XRTraceExhaustedError("trace replay is complete")
        frame = self.reader.frames[self._index]
        target_s = self._started_at_s + frame.elapsed_ns / 1_000_000_000
        if self.mode is ReplayMode.DETERMINISTIC:
            assert isinstance(self.clock, AdvanceableClock)
            self.clock.advance_to(target_s)
        else:
            delay = target_s - self.clock.now()
            if not math.isfinite(delay):
                raise XRTraceError("replay clock returned a nonfinite time")
            self.clock.sleep(max(0.0, delay))
        result = replace(frame.sample, captured_at_s=self.clock.now())
        self._status = result.status
        self._index += 1
        return result

    def disconnect(self) -> None:
        self._connected = False
        self._status = XRSourceStatus(XRSourceState.DISCONNECTED, "trace disconnected")
