"""Distribution metadata required by LeRobot's third-party plugin discovery."""

from importlib import metadata


def test_distribution_name_matches_lerobot_teleoperator_discovery_prefix():
    package = metadata.metadata("lerobot_teleoperator_g1_vr")
    assert package["Name"] == "lerobot_teleoperator_g1_vr"
    assert package["Name"].startswith("lerobot_teleoperator_")


def test_base_install_has_no_robot_or_vendor_runtime_dependencies():
    requirements = metadata.requires("lerobot_teleoperator_g1_vr") or []
    runtime = [requirement for requirement in requirements if "extra ==" not in requirement]
    assert runtime == []
