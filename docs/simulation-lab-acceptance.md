# Efficient simulation-lab acceptance plan

This plan consolidates all deferred manual verification from Commits 3–12 into
two headset sessions—one XRoboToolkit and one CloudXR—plus headset-free replay.
All robot targets are G1-29 MuJoCo simulation. Do not start physical DDS or
connect a physical G1.

Assumed gates used during development are not evidence. Mark each checkpoint
with observed pass/fail, exact revisions, timestamps and artifact paths.

## 0. Preflight without the headset

1. Check out the candidate revisions in the workflow document and confirm clean
   status except known operator files.
2. Run plugin lint/unit tests, pinned G1 IK tests, integration supervisor tests,
   Quest protocol tests and the trace→native-MuJoCo test.
3. Record Python/package versions, URDF hash, GPU/driver, IP endpoints (no
   credentials), and available disk space.
4. Replay the synthetic idle/right/left/bimanual/stale/reconnect cases. Require
   finite 14-joint actions, correct-side isolation, release hold, stale hold,
   release/re-grip recovery and clean exit.
5. Prepare one evidence directory per source. Start simulation/viewer and video
   prerequisites before putting on the headset.

## 1. XRoboToolkit session: capture once, then combined live gate

Connect USB only if needed for app launch/ADB or recovery; normal Wi-Fi tracking
does not require leaving USB attached once PC Service/app communication works.

1. Start PC Service and Quest app. Select XRoboToolkit explicitly and verify no
   CloudXR process is launched or stopped.
2. Capture short labeled traces, in this order: released idle; right-only reach
   and rotation; left-only; bimanual; grip/trigger/buttons/head; tracking loss;
   reconnect while grips are pressed, then release and re-grip. Save hashes.
3. Confirm the app/source status changes to stale or no-response when PC Service
   or the app link is interrupted and presents the reconnect guidance.
4. Start the supervised G1-29 simulator input-only. Repeat right, release, left,
   release, bimanual. Require same-side motion, other-side hold, released-side
   hold, bounded finite actions and responsive simulation.
5. Interrupt tracking while gripped. Require immediate two-arm hold. Reconnect:
   motion must remain inhibited until release and a new grip.
6. Enable the Quest video sidecar and request `OPEN_CAMERA`. Require a
   recognizable updating MuJoCo view. Repeat one right/left/bimanual/release
   cycle. Stop or break video and require the control path still holds/runs and
   can shut down cleanly.
7. Run the short right/left/release sequence through standard
   `lerobot-teleoperate`. Compare named joint telemetry with the supervised path.
8. Stop normally and preserve traces, telemetry, `sender.log`, `metadata.json`,
   source transitions, process exit codes and any forced-shutdown observation.

## 2. Headset-free replay while XRoboToolkit can be disconnected

1. Stop the live source and remove the headset dependency.
2. Replay every captured trace through the supervised native simulation, then a
   representative trace through standard `lerobot-teleoperate`.
3. Compare source-state/clutch transitions and action direction with the live
   run. Exact joint equality is required only for deterministic replay of the
   same trace/environment, not between separately performed live motions.
4. Corrupt one copied trace and confirm checksum validation rejects it.

This phase is the primary regression loop for later development.

## 3. CloudXR session: equivalence and shared video

1. Start the pinned CloudXR/Isaac Teleop runtime. Select CloudXR explicitly and
   verify XRoboToolkit SDK/PC Service is not started, probed or stopped.
2. Input-only: verify both poses, squeeze/trigger/buttons and freshness. Repeat
   right, release, left, release and bimanual stages.
3. End/disconnect the CloudXR session while gripped. Require stale/reconnect
   guidance, two-arm hold, and release/new-grip before recovery.
4. Enable the existing CloudXR shared video session. Require the G1-29 view in
   the headset while controller response remains usable. Interrupt video and
   require hold/shutdown remains available.
5. Repeat a short right/left/release sequence through standard
   `lerobot-teleoperate` and compare named joint/action telemetry with the
   supervised reference.
6. Stop normally and preserve logs, source transitions, telemetry, versions,
   endpoints and process exit codes.

## 4. Final acceptance criteria

Pass only if both sources meet all of these:

- correct source exclusivity and both-controller visibility;
- right-only, left-only and bimanual same-side response;
- released controller holds its arm;
- tracking loss/frozen timestamp holds both arms;
- reconnect requires release and a new grip;
- standard LeRobot and supervised paths have matching named action semantics;
- recognizable updating video, with video failure isolated from control safety;
- trace integrity/replay succeeds without a headset;
- no nonfinite action, MuJoCo warning, physical DDS discovery, forced shutdown,
  traceback, broken pipe or OpenXR instance-loss error.

If a check fails, retain the artifacts and stop at simulation scope. Do not
reinterpret a partial pass as CloudXR/XRoboToolkit equivalence, G1-23 support,
latency/reliability validation or physical-robot safety.

## Commit coverage

| Checks | Commits covered |
| --- | --- |
| Preflight and deterministic replay | 1–6, 8–10, 12 |
| XRoboToolkit capture/source isolation | 3, 6–9 |
| Live G1-29 and standard LeRobot comparison | 5, 9, 10 |
| Quest/CloudXR video and failure isolation | 4, 11 |
| Reconnect prompt, hold and re-clutch | 6, 9–12 |

The detailed per-commit/source checklist remains in
`headset-verification-by-commit.md`.
