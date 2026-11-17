# Reviewed G1-29 XR simulation workflow

This handoff is simulation-only. It does not validate or authorize physical G1
motion. Manual headset gates are listed as pending until an operator records
observed results.

## Candidate revisions

| Component | Revision/version | Role |
| --- | --- | --- |
| `MoissanClub/lerobot_teleoperator_g1_vr` | Commit 10 `b0928d0ddbccb7a4e9caf6e322c37267b8395453` plus this documentation commit | Reusable sources, traces, guard, retargeter and LeRobot plugin |
| `MoissanClub/unitree_g1_lerobot` | Commit 11 `13a272a0711e39d9e736bef0577b43f500b3e137` | Simulation supervisor, Quest video sidecar and evidence capture |
| `MoissanClub/lerobot` | `d5e400bcefeccc93ba956ce876530e5283512df1` | Pinned G1-29 IK, native MuJoCo robot and plugin hooks |
| XRoboToolkit Python SDK | 1.1.0 | Quest/controller input through PC Service |
| Simulation stack | Python 3.12.14, Pinocchio 3.9.0, MuJoCo 3.12.0, NumPy 2.2.6 | Observed automated-test environment |
| G1-29 URDF | SHA-256 `8bbf006633fc50b616f665c7a970780cc296577a0adfd7d28b049e751c238735` | Pinned G1-29 model |

The existing LeRobot release pin is intentionally unchanged. Move it only after
reviewing the stacked branches and recording the pending live gates.

## Install and automated checks

From this repository:

```bash
uv run --python 3.12 --extra test ruff format --check .
uv run --python 3.12 --extra test ruff check .
uv run --python 3.12 --extra test pytest -q
uv build
```

Install the wheel into the pinned LeRobot environment without resolving a
second scientific stack:

```bash
uv pip install \
  --python /home/dwei/lerobot-sim/unitree_g1_lerobot/.vr-sim/clean-install-verification/env/bin/python \
  --no-deps --reinstall dist/lerobot_teleoperator_g1_vr-0.1.0-py3-none-any.whl
```

## Capture XRoboToolkit traces without simulation

Start PC Service and the Quest app, then run:

```bash
g1-vr-capture-xrobotoolkit traces/right-reach \
  --label right-reach \
  --duration-s 10 \
  --sdk-site-packages \
  /home/dwei/meta_quest_xrobotoolkit/xrbt-quest-mujoco.da7RUqYj/venv/lib/python3.12/site-packages \
  --adapter-revision b73c8a9
```

Capture released idle, right, left, bimanual, head/buttons and reconnect cases.
Each trace contains raw/normalized/event JSONL, a manifest and SHA-256 checksums.

## Headset-free replay through native G1-29 MuJoCo

Use the integration harness at Commit 11:

```bash
PYTHONPATH=/path/to/lerobot_teleoperator_g1_vr/src:/path/to/lerobot/src \
/path/to/pinned/python \
  tools/run_supervised_g1_29_vr.py \
  --source trace \
  --trace /absolute/path/to/trace \
  --urdf /absolute/path/to/g1_29.urdf \
  --telemetry outputs/replay-telemetry.json
```

This diagnostic path never selects DDS or a physical target.

## Standard LeRobot path

The same trace can drive LeRobot's native robot through the discovered plugin:

```bash
/path/to/pinned/python -m lerobot.scripts.lerobot_teleoperate \
  --teleop.type=g1_vr \
  --teleop.id=g1-vr \
  --teleop.urdf_path=/absolute/path/to/g1_29.urdf \
  --teleop.source=trace \
  --teleop.trace_path=/absolute/path/to/trace \
  --robot.type=unitree_g1 \
  --robot.id=g1-29-sim \
  --robot.embodiment=g1_29 \
  --robot.is_simulation=true \
  --robot.simulation_urdf=/absolute/path/to/g1_29.urdf \
  --robot.gravity_compensation=true \
  --fps=60
```

For live input, change `--teleop.source` to `xrobotoolkit` and provide
`--teleop.sdk_site_packages`, or change it to `cloudxr` after starting the
supported CloudXR/Isaac Teleop runtime. Do not remove `simulation_only` or
`simulation_urdf`.

## Optional XRoboToolkit Quest video

The integration supervisor accepts `--quest-video`. The sidecar listens for
Quest `OPEN_CAMERA`, captures the selected X11 desktop with FFmpeg/NVENC, and
sends length-framed H.264. It is outside the command loop. Its failure is logged
and does not prevent control cleanup.

```bash
tools/run_supervised_g1_29_vr.py ... \
  --quest-video \
  --video-display :1 \
  --video-evidence-root outputs
```

The command prints the evidence directory containing `sender.log` and
`metadata.json`. CloudXR uses its existing shared controller/video session, not
this XRoboToolkit protocol sidecar.

## Recovery and shutdown

- Stale, disconnected, frozen or backward timestamps disable both hands.
- After recovery, release each grip before pressing it again. This prevents a
  large reconnect offset from becoming an immediate arm command.
- Stop the control loop first. The supervisor disconnects the XR source and
  native simulator; the optional video sidecar is then terminated and its final
  status is written.
- A video failure is not an input failure. A tracking/input failure is always a
  command hold even if video remains visible.

## Compatibility and extension seams

| Combination | Status |
| --- | --- |
| Trace → G1-29 IK → native MuJoCo | Automated pass |
| Plugin discovery and standard LeRobot interface | Automated pass |
| XRoboToolkit SDK import beside pinned simulation packages | Automated pass |
| XRoboToolkit live tracking/control/video | Manual simulation-lab gate pending |
| CloudXR live tracking/control/video | Manual simulation-lab gate pending |
| G1-23 | Not implemented; add a separate `G123Retargeter` over explicit upstream kinematics/model metadata |
| Physical G1 | Unsupported and not authorized |

`XRInputSource` remains independent of embodiment. `CloudXRSource` and
`XRoboToolkitSource` feed the same samples. A future G1-23 adapter should not
fork either source or the re-clutch state machine. Robot-generic kinematics and
embodiment metadata belong upstream in LeRobot; source adapters, XR interaction
policy, traces and experiment orchestration remain in Moissan repositories.
