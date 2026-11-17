# XR trace format version 1

The trace format separates headset/source evidence from robot commands. A trace
contains the source payload and normalized controller intent; G1 joint commands
and simulator observations are downstream evidence and are not trace inputs.

## Directory layout

```text
trace-directory/
  manifest.json
  raw.jsonl
  normalized.jsonl
  events.jsonl
  checksums.sha256
```

`TraceRecorder` creates a new directory and refuses to overwrite an existing
one. It writes a manifest and checksums only when a nonempty recording closes
normally. A directory without a manifest is incomplete and cannot be replayed.

## Manifest

The manifest records:

- schema version (`1`);
- trace ID and operator label;
- source type and source-adapter revision;
- timezone-qualified capture creation time;
- coordinate-frame description;
- position unit (`metre`) and quaternion order (`xyzw`);
- sample count and elapsed duration;
- whether data were transformed (`false` for exact capture in version 1);
- SHA-256 and record count for each JSONL file.

`checksums.sha256` independently covers the three JSONL files and the manifest.
`TraceReader` verifies both sets of hashes before decoding normalized samples.

## Raw records

Each `raw.jsonl` record contains:

- schema version;
- sequence and elapsed trace time;
- original host monotonic capture time;
- optional source timestamp;
- a finite JSON-compatible vendor payload, or `null`.

The recorder makes a JSON deep copy at the call boundary. Later mutations to an
SDK-owned list or mapping cannot change the trace. Source adapters are responsible
for describing their raw payload schema and converting native objects to finite
JSON-compatible values.

## Normalized records

Each `normalized.jsonl` record includes elapsed trace time and the complete
source-independent `XRSample`: source status, host/source timestamps, optional
head pose, both controller poses, tracking validity, squeeze, trigger, and
normalized buttons. Positions are metres and quaternions are `[x, y, z, w]`.

Sequence numbers must increase strictly. Host capture timestamps and elapsed
trace time must be monotonic. A reader rejects unsupported schema versions,
record/sample sequence disagreement, invalid values, unordered frames, empty
traces, and integrity failures.

## Events

`events.jsonl` records source-state transitions (`ready`, `stale`, or
`disconnected`) with sequence, elapsed time, detail, and recovery hint. Repeated
samples in the same state do not create duplicate event records.

## Replay timing

`TraceReplaySource` implements `XRInputSource` and supports:

- `deterministic`: advance an `AdvanceableClock` to each recorded elapsed time;
  no wall-clock sleep;
- `realtime`: sleep against an injected/system monotonic clock to reproduce
  recorded elapsed timing.

Both modes replace the old absolute `captured_at_s` with the replay clock. Source
timestamps and source-health transitions remain unchanged. This lets freshness
logic use the same injected clock without treating a valid historical trace as
stale merely because it was captured on another day.

Rate conversion is not implemented in version 1. A future resampler must mark
the output as transformed and preserve parent-trace hashes; it must not overwrite
or masquerade as exact-sample replay.

## Safety and evidence limits

Trace replay currently accepts only `target="simulation"`. A trace is development
input, not authorization to command physical hardware.

Replay validates deterministic clutch/IK/simulator behavior but does not validate
live network latency, SDK lifecycle, current device coordinates, headset UI,
video decoding, or operator comfort. Those require separate bounded live tests.

Before committing a normalized trace fixture, review it for privacy and retain
only the shortest segment needed by the regression. Store full-rate captures as
hashed experiment evidence when practical.
