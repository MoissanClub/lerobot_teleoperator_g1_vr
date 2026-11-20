"""G1-29 XR calibration shared by offline and live consumers."""

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from .xr.status import XRSourceState, XRSourceStatus
from .xr.types import XRPose


def load_anchor_grid(path: Path):
    payload = json.loads(path.read_text())
    anchors = payload.get("anchors", {})
    grid = {}
    for label, anchor in anchors.items():
        if not label.startswith("calibration-"):
            continue
        suffix = label.removeprefix("calibration-")
        try:
            position, orientation = suffix.split("-", 1)
        except ValueError as error:
            raise ValueError(f"unrecognized calibration label: {label}") from error
        if position not in ("down", "forward", "horizontal", "up") or orientation not in (
            "down",
            "forward",
            "up",
            "inward",
            "outward",
            "backward",
        ):
            raise ValueError(f"unsupported calibration matrix cell: {label}")
        poses = anchor.get("representative_poses")
        if not poses or any(name not in poses for name in ("head", "left", "right")):
            raise ValueError(f"missing representative head/controller poses: {label}")
        grid[(position, orientation)] = {"label": label, "poses": poses}
    return grid


@dataclass
class CalibrationProfile:
    basis: np.ndarray
    neutral: np.ndarray
    home: tuple
    fits: dict
    down: dict
    anchor_sha256: str
    urdf_sha256: str

    def position(self, poses, side):
        return self.basis @ (np.asarray(poses[side]["position_m"]) - poses["head"]["position_m"])

    def rotation(self, poses, side):
        return self.basis @ Rotation.from_quat(poses[side]["quaternion_xyzw"]).as_matrix()

    def metadata(self):
        return {
            "version": 1,
            "embodiment": "g1_29",
            "anchor_sha256": self.anchor_sha256,
            "urdf_sha256": self.urdf_sha256,
            "basis": self.basis.tolist(),
            "reference_q": self.neutral.tolist(),
            "fits": {
                s: {
                    "shoulder_m": p.tolist(),
                    "scale": float(k),
                    "controller_palm_normal": n.tolist(),
                }
                for s, (p, k, n) in self.fits.items()
            },
        }

    def heading_matches(self, sample, tolerance_deg=25.0):
        """Check the operator facing calibration-forward before live clutching."""
        if not sample.head.tracked:
            return False
        forward = -Rotation.from_quat(sample.head.pose.quaternion_xyzw).as_matrix()[:, 2]
        forward[1] = 0
        length = np.linalg.norm(forward)
        return length > 1e-6 and forward @ self.basis[0] / length >= np.cos(
            np.deg2rad(tolerance_deg)
        )

    def map_sample(self, sample):
        if not sample.head.tracked:
            return replace(
                sample, status=XRSourceStatus(XRSourceState.STALE, "Head tracking unavailable")
            )
        updates = {}
        for side, controller in (("left", sample.left), ("right", sample.right)):
            if controller.tracked:
                pos = np.asarray(controller.pose.position_m) - sample.head.pose.position_m
                pos = self.fits[side][1] * (self.basis @ pos)
                # A constant controller-to-hand offset cancels in R(t) R(clutch).T.
                rot = Rotation.from_matrix(self.basis) * Rotation.from_quat(
                    controller.pose.quaternion_xyzw
                )
                updates[side] = replace(controller, pose=XRPose(tuple(pos), tuple(rot.as_quat())))
        return replace(sample, **updates)


def load_profile(path, ik):
    path = Path(path)
    grid = load_anchor_grid(path)
    reference_key = ("down", "inward")
    if reference_key not in grid:
        raise ValueError("retargeting preview requires calibration-down-inward")
    if ("up", "inward") not in grid:
        raise ValueError("reach estimation requires calibration-up-inward")

    # Fixed body heading from the reference headset, retaining gravity-up.
    down = grid[reference_key]["poses"]
    forward = -np.asarray(Rotation.from_quat(down["head"]["quaternion_xyzw"]).as_matrix())[:, 2]
    forward[1] = 0
    if np.linalg.norm(forward) < 1e-6:
        raise ValueError("Down/inward headset orientation lacks a horizontal heading")
    forward /= np.linalg.norm(forward)
    vertical = np.array([0.0, 1.0, 0.0])
    basis = np.stack([forward, np.cross(vertical, forward), vertical])
    neutral = np.zeros(14)
    neutral[[3, 10]] = np.pi / 2  # G1 forearms point forward at zero elbow.
    sides = ("left", "right")

    def position(poses, side):
        return basis @ (np.array(poses[side]["position_m"]) - poses["head"]["position_m"])

    def rotation(poses, side):
        return basis @ Rotation.from_quat(poses[side]["quaternion_xyzw"]).as_matrix()

    home = ik.fk(neutral)
    up = grid[("up", "inward")]["poses"]
    fits = {}
    for i, side in enumerate(sides):
        low, high = position(down, side), position(up, side)
        shoulder = (low + high) / 2
        span = np.linalg.norm(high - low)
        if span < 0.25:
            raise ValueError(f"Insufficient up/down separation for {side}")
        data = ik.model.createData()
        ik._pin.forwardKinematics(ik.model, data, ik._to_model(neutral))
        joint = ik.model.getJointId(f"{side}_shoulder_pitch_joint")
        reach = np.linalg.norm(home[i][:3, 3] - data.oMi[joint].translation)
        inward = np.array([0.0, -1.0 if i == 0 else 1.0, 0.0])
        normals = dict(
            inward=inward,
            outward=-inward,
            up=[0, 0, 1],
            down=[0, 0, -1],
            forward=[1, 0, 0],
            backward=[-1, 0, 0],
        )
        # Express each annotated normal in controller coordinates and average.
        normal = np.mean(
            [
                rotation(e["poses"], side).T @ normals[col]
                for (row, col), e in grid.items()
                if row in ("forward", "horizontal")
            ],
            axis=0,
        )
        if not np.isfinite(normal).all() or np.linalg.norm(normal) < 0.2:
            raise ValueError(f"Inconsistent palm orientation anchors for {side}")
        fits[side] = shoulder, 2 * reach / span, normal / np.linalg.norm(normal)
    return CalibrationProfile(
        basis,
        neutral,
        home,
        fits,
        down,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        hashlib.sha256(Path(ik.urdf_path).read_bytes()).hexdigest(),
    )


def static_targets(profile, key, entry):
    targets = []
    for i, side in enumerate(("left", "right")):
        target = profile.home[i].copy()
        if key != ("down", "inward"):
            shoulder, scale, normal = profile.fits[side]
            p = profile.position(entry["poses"], side)
            target[:3, 3] += scale * (p - profile.position(profile.down, side))
            # Straight-arm protocol: fingers extend along the arm.
            x = p - shoulder
            if np.linalg.norm(x) < 1e-6:
                raise ValueError(f"Undefined straight-arm direction for {side} at {key}")
            x /= np.linalg.norm(x)
            y = profile.rotation(entry["poses"], side) @ normal * (-1 if i == 0 else 1)
            y -= x * (x @ y)
            if np.linalg.norm(y) < 1e-6:
                raise ValueError(f"Ambiguous palm direction for {side} at {key}")
            y /= np.linalg.norm(y)
            target[:3, :3] = np.column_stack([x, y, np.cross(x, y)])
        targets.append(target)
    return targets


def solve_anchor(ik, profile, key, entry, max_iterations=80):
    targets = static_targets(profile, key, entry)
    previous = profile.neutral.copy()
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    for iteration in range(1, max_iterations + 1):
        result = ik.solve(*targets, seed=previous)
        current = result.q
        stable = float(np.max(np.abs(current - previous))) < 1e-6
        previous = current
        if result.converged or stable or iteration == max_iterations:
            return targets, result, iteration


def verify_trace_anchor(manifest, label, anchor_set, trace=None):
    manifest = json.loads(Path(manifest).read_text())
    entry = manifest["segments"][label]
    digest = hashlib.sha256(Path(anchor_set).read_bytes()).hexdigest()
    selected = Path(trace or entry["selected_trace"]).resolve()
    attempts = [
        a for a in entry["attempts"] if Path(a["trace_path"]).resolve() == selected and a["passed"]
    ]
    if len(attempts) != 1 or attempts[0]["calibration_anchor_set_sha256"] != digest:
        raise ValueError(f"Calibration digest mismatch or unaccepted trace for {label}")


if __name__ == "__main__":
    import sys

    verify_trace_anchor(*sys.argv[1:])
