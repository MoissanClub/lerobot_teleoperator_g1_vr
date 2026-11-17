"""Standard LeRobot plugin contract checks against the pinned framework."""

from __future__ import annotations

import pytest

lerobot = pytest.importorskip("lerobot")

from lerobot.teleoperators import (  # noqa: E402
    Teleoperator,
    TeleoperatorConfig,
    make_teleoperator_from_config,
)

from lerobot_teleoperator_g1_vr import (  # noqa: E402
    DeterministicClock,
    G1RetargetDiagnostics,
    G1RetargetResult,
    G1VRTeleoperator,
    G1VRTeleoperatorConfig,
    XRController,
    XRPose,
    XRSample,
    XRSourceState,
    XRSourceStatus,
)

KEYS = tuple(f"joint_{index}.q" for index in range(14))


class FakeSource:
    def __init__(self):
        self.is_connected = False
        self.status = XRSourceStatus(XRSourceState.DISCONNECTED)
        self.sequence = 0

    def connect(self):
        self.is_connected = True

    def sample(self):
        controller = XRController(True, XRPose((0, 0, 0), (0, 0, 0, 1)), squeeze=1.0)
        sample = XRSample(
            self.sequence,
            10.0,
            controller,
            controller,
            XRSourceStatus(XRSourceState.READY),
        )
        self.sequence += 1
        return sample

    def disconnect(self):
        self.is_connected = False


class FakeRetargeter:
    embodiment = "g1_29"
    action_features = dict.fromkeys(KEYS, float)

    def reset(self):
        pass

    def retarget(self, sample, measured):
        return G1RetargetResult(
            dict(zip(KEYS, measured, strict=True)),
            G1RetargetDiagnostics("g1_29", "ready", True, True, False),
        )


def config(tmp_path):
    return G1VRTeleoperatorConfig(
        id="test",
        calibration_dir=tmp_path / "calibration",
        urdf_path=tmp_path / "g1.urdf",
        source="trace",
        trace_path=tmp_path / "trace",
    )


def test_config_registers_and_framework_factory_finds_plugin(monkeypatch, tmp_path):
    actual = config(tmp_path)
    assert isinstance(actual, TeleoperatorConfig)
    assert actual.type == "g1_vr"
    monkeypatch.setattr(
        "lerobot_teleoperator_g1_vr.lerobot_plugin.G129Retargeter",
        lambda *args, **kwargs: FakeRetargeter(),
    )
    monkeypatch.setattr(
        "lerobot_teleoperator_g1_vr.lerobot_plugin.build_xr_source",
        lambda *args, **kwargs: FakeSource(),
    )
    device = make_teleoperator_from_config(actual)
    assert isinstance(device, G1VRTeleoperator)
    assert isinstance(device, Teleoperator)


def test_standard_feedback_action_lifecycle(tmp_path):
    source = FakeSource()
    device = G1VRTeleoperator(
        config(tmp_path),
        source=source,
        retargeter=FakeRetargeter(),
        clock=DeterministicClock(10.0),
    )
    assert device.action_features == dict.fromkeys(KEYS, float)
    assert device.feedback_features == device.action_features
    with pytest.raises(RuntimeError, match="not connected"):
        device.send_feedback({})
    device.connect()
    with pytest.raises(RuntimeError, match="feedback"):
        device.get_action()
    measured = dict.fromkeys(KEYS, 0.25)
    device.send_feedback(measured)
    assert device.get_action() == measured
    device.disconnect()
    assert not device.is_connected


def test_invalid_feedback_and_physical_opt_in_are_rejected(tmp_path):
    device = G1VRTeleoperator(
        config(tmp_path),
        source=FakeSource(),
        retargeter=FakeRetargeter(),
        clock=DeterministicClock(10.0),
    )
    device.connect()
    with pytest.raises(ValueError, match="14"):
        device.send_feedback({})
    with pytest.raises(ValueError, match="finite"):
        device.send_feedback(dict.fromkeys(KEYS, float("nan")))
    with pytest.raises(ValueError, match="simulation-only"):
        G1VRTeleoperatorConfig(
            urdf_path=tmp_path / "g1.urdf",
            source="trace",
            trace_path=tmp_path / "trace",
            simulation_only=False,
        )
