from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unified_arm_and_vision_services_load_the_same_runtime_env_file() -> None:
    expected = "EnvironmentFile=-/home/fibo/.config/xingbao/runtime.env"
    arm_unit = (ROOT / "deploy" / "systemd" / "xingbao-unified-arm.service").read_text(encoding="utf-8")
    vision_unit = (
        ROOT / "deploy" / "systemd" / "xingbao-unified-high-five-vision.service"
    ).read_text(encoding="utf-8")
    point_unit = (
        ROOT / "deploy" / "systemd" / "xingbao-unified-hand-server.service"
    ).read_text(encoding="utf-8")

    assert expected in arm_unit
    assert expected in vision_unit
    assert expected in point_unit


def test_runtime_env_example_declares_only_local_ipc_endpoints() -> None:
    content = (ROOT / "deploy" / "runtime.env.example").read_text(encoding="utf-8")

    assert "XINGBAO_ARM_ACTION_HOST=127.0.0.1" in content
    assert "XINGBAO_ARM_ACTION_PORT=8764" in content
    assert "XINGBAO_HAND_RECOGNITION_CONTROL_HOST=127.0.0.1" in content
    assert "XINGBAO_HAND_RECOGNITION_CONTROL_PORT=10001" in content
    assert "XINGBAO_VISION_POINT_ACTION_HOST=127.0.0.1" in content
    assert "XINGBAO_VISION_POINT_ACTION_PORT=10000" in content
