"""Capture-only CLI argument and lifecycle tests."""

from __future__ import annotations

import pytest

from lerobot_teleoperator_g1_vr.capture import build_parser


def test_capture_cli_requires_output_and_label():
    parser = build_parser()
    args = parser.parse_args(["trace", "--label", "reach-left"])
    assert args.output.name == "trace"
    assert args.label == "reach-left"
    assert args.rate_hz == 60.0
    assert args.duration_s == 10.0


@pytest.mark.parametrize("argv", [[], ["trace"]])
def test_capture_cli_rejects_missing_required_arguments(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)
