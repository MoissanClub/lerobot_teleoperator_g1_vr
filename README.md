# lerobot_teleoperator_g1_vr

Reusable XR input sources, interaction state, G1 retargeter adapters, and a
third-party LeRobot teleoperator plugin.

The project is under active development. Its first supported path will be
XRoboToolkit controller input to G1-29 MuJoCo simulation. The architecture keeps
the input source independent of the robot embodiment so CloudXR and G1-23 can be
added without duplicating the control stack.

## Normalized XR input contract

`XRInputSource` is the boundary between a vendor transport and downstream
interaction/retargeting code. Implementations expose the same lifecycle:

```python
source.connect()
sample = source.sample()
status = source.status
source.disconnect()
```

`XRSample` uses these conventions:

- positions are metres in a documented normalized XR frame;
- quaternions are `[x, y, z, w]` and normalized on construction;
- `captured_at_s` is a finite, nonnegative host monotonic time;
- an optional source timestamp is preserved separately from host time;
- squeeze, trigger, and normalized button values are in `[0, 1]`;
- an untracked pose is represented by `tracked=False` and `pose=None`;
- values are copied into immutable tuples/mappings at the boundary.

The contract has no XRoboToolkit, CloudXR, GPU, MuJoCo, or physical-device
dependency. Source adapters and G1 retargeting are added in later commits.

## Trace-driven development

The trace boundary is part of the plugin architecture. `TraceRecorder` writes
raw source values and normalized `XRSample` values together; `TraceReplaySource`
then presents the normalized stream through the same `XRInputSource` interface as
a live headset:

```python
from lerobot_teleoperator_g1_vr import (
    DeterministicClock,
    TraceManifestSeed,
    TraceReader,
    TraceRecorder,
    TraceReplaySource,
)

with TraceRecorder(
    "trace-idle",
    TraceManifestSeed(
        trace_id="trace-idle",
        label="idle-released",
        source_type="synthetic",
        source_adapter_revision="example",
        coordinate_frame="normalized right-handed XR frame",
    ),
) as recorder:
    recorder.record(sample, raw_payload={"vendor_value": 1})

clock = DeterministicClock()
source = TraceReplaySource(TraceReader("trace-idle"), clock=clock)
source.connect()
replayed = source.sample()
```

Deterministic mode advances an injected clock without sleeping. Real-time mode
preserves recorded elapsed timing while replacing the original absolute host
timestamp. Replays are currently restricted to the `simulation` target.

See [the version 1 trace format](docs/trace-format-v1.md) for artifact layout,
integrity rules, and evidence limitations.

## CloudXR source adapter

`CloudXRSource` wraps the established LeRobot `XRControllers` reader behind the
normalized contract. Importing the plugin does not import LeRobot, Isaac Teleop,
OpenXR, CUDA, or video code. The default reader resolves those optional
dependencies only during `connect()`; tests and alternate integrations can
inject a narrow reader factory.

```python
from lerobot_teleoperator_g1_vr import CloudXRSource, CloudXRSourceConfig

source = CloudXRSource(CloudXRSourceConfig(max_age_s=0.25))
source.connect()
sample = source.sample()
source.disconnect()
```

Set `video_channel` to use the pinned LeRobot shared controller/video session.
Leave it `None` for controller input only. The source performs one backend read
per sample, preserves the backend acquisition timestamp, rejects future/stale
frames, and isolates invalid data to the affected hand. `last_raw_action` returns
a defensive JSON-compatible copy suitable for `TraceRecorder`.

The adapter does not launch or own CloudXR. Runtime installation, EULA handling,
process supervision, and video production remain responsibilities of the
integration harness.

## G1-29 retargeting

`G129Retargeter` is a thin adapter over the supported LeRobot
`G1ArmKinematics`/`G1XRControl`; the plugin does not copy the solver. It consumes
any normalized `XRSample`, accepts the measured 14-arm-joint state as its seed,
and returns named joint actions plus clutch and IK diagnostics. G1-23 is rejected
explicitly until its separate retargeter/model contract is implemented.

The base package still has no LeRobot runtime dependency. Constructing the
default G1-29 retargeter resolves the supported LeRobot integration lazily; unit
tests can inject compatible kinematics/control components.

Manual headset requirements for both sources are tracked in
[headset verification by commit](docs/headset-verification-by-commit.md).

## Development

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are recommended:

```bash
uv run --extra test pytest -q
uv run --extra test ruff check .
uv run --extra test ruff format --check .
uv build
```

The base package is intentionally vendor-free. Optional SDK dependency groups
will be introduced with their corresponding adapters.

## License

Apache-2.0.
