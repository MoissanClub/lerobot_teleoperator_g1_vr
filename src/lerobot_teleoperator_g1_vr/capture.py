"""Capture XRoboToolkit raw and normalized traces without a robot backend."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from .xr.trace import TraceManifestSeed, TraceRecorder
from .xr.xrobotoolkit import XRoboToolkitSource, XRoboToolkitSourceConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--duration-s", type=float, default=10.0)
    parser.add_argument("--rate-hz", type=float, default=60.0)
    parser.add_argument("--sdk-site-packages", type=Path)
    parser.add_argument("--adapter-revision", default="working-tree")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.duration_s <= 0 or args.rate_hz <= 0:
        raise SystemExit("duration and rate must be positive")
    source = XRoboToolkitSource(XRoboToolkitSourceConfig(sdk_site_packages=args.sdk_site_packages))
    manifest = TraceManifestSeed(
        trace_id=args.output.name,
        label=args.label,
        source_type="xrobotoolkit",
        source_adapter_revision=args.adapter_revision,
        coordinate_frame="XRoboToolkit normalized controller frame; metres; quaternion xyzw",
    )
    source.connect()
    started = time.monotonic()
    try:
        with TraceRecorder(args.output, manifest) as recorder:
            while time.monotonic() - started < args.duration_s:
                cycle = time.monotonic()
                sample = source.sample()
                recorder.record(sample, source.last_raw_action)
                time.sleep(max(0.0, 1.0 / args.rate_hz - (time.monotonic() - cycle)))
    finally:
        source.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
