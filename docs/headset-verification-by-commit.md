# Headset verification required by implementation commit

This matrix is the manual acceptance backlog for the G1 VR plugin. Development
may proceed by assuming these gates pass, but an assumed gate is **not observed
evidence**. Record actual operator results, versions, logs, and trace hashes when
the simulation-lab test is performed.

All checks are simulation-only. Do not connect physical DDS or a physical G1.

| Commit | CloudXR headset verification | XRoboToolkit headset verification |
| --- | --- | --- |
| 1 — pinned G1-29 baseline | None. Synthetic replay only. | None. Synthetic replay only. |
| 2 — normalized source contract | None. Contract/unit review only. | None. Contract/unit review only. |
| 3 — trace recording/replay | Optional format smoke: capture a short source trace later and confirm it replays. | Required at the capture gate after Commit 7: record raw and normalized traces, then replay without headset. |
| 4 — CloudXR source adapter | After integration: connect once, verify both controller poses/buttons update, cached frames become stale after disconnect, and reconnect produces fresh data. No G1 motion is required for adapter-only acceptance. | None; ensure installing/importing the CloudXR adapter does not affect XRoboToolkit dependencies. |
| 5 — G1-29 retargeter | Deferred to Commit 9 live control: right-only, left-only, bimanual, release/hold and small rotations. | Same stages using the identical recorded normalized traces, then live input at Commit 9. |
| 6 — freshness/reconnect state | Required: disconnect or end CloudXR session while gripped; simulation must hold, show stale/reconnect guidance, and require release/new grip before motion resumes. | Required: stop/reconnect Quest app or PC Service while gripped; same hold and new-grip behavior. |
| 7 — XRoboToolkit source | Regression only: CloudXR path still imports/runs independently. | Required capture-only gate: idle, right, left, bimanual, rebase, buttons/head, and reconnect traces with no simulator running. |
| 8 — source selection | Launch CloudXR selection and confirm only CloudXR processes/dependencies are used. | Launch XRoboToolkit selection and confirm CloudXR is not started, probed, or stopped. |
| 9 — supervised G1-29 simulation | Required input-only live run: right, release, left, release, bimanual, then reconnect. Compare with trace replay. | Required input-only live run with the same ordered stages and reconnect comparison. |
| 10 — standard LeRobot control | Repeat a short right/left/release sequence through standard `lerobot-teleoperate`; compare named joint/action telemetry with the supervised reference path. | Same through standard `lerobot-teleoperate`; no source-specific bridge fork. |
| 11 — video sidecar | Verify CloudXR controller/video session displays the G1-29 view while control remains responsive; video loss must not prevent hold/shutdown. | Verify Quest video return plus XRoboToolkit input; repeat right/left/bimanual/release and one tracking reconnect. |
| 12 — reviewed workflow | Clean-install smoke using documented commands; verify recovery instructions and clean shutdown. | Clean-install smoke using documented commands; verify trace capture/replay, recovery instructions, video and clean shutdown. |

## Evidence to record at every required live gate

- exact plugin, LeRobot, integration-harness, SDK/app, and model revisions;
- selected source and process graph;
- headset/controller model and network endpoints without credentials;
- raw and normalized trace hashes where capture is involved;
- source status transitions, clutch state, commanded/observed joints, and IK
  diagnostics;
- operator observation for same-side motion, released-side hold, video, comfort,
  and reconnect prompt;
- process exit codes and whether forced shutdown was required.

The final efficient lab protocol will consolidate repeated checks so each source
needs one capture/setup sequence rather than a separate headset session per
commit.
