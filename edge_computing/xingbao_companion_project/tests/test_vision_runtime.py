from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import multimodal.vision_runtime as vision_runtime
from multimodal.vision_runtime import VisionProcessBridge, VisionRuntimeConfig


def test_runtime_config_uses_board_environment_and_no_object_mode(tmp_path: Path) -> None:
    emotion_model = tmp_path / "emotion.onnx"
    emotion_model.write_bytes(b"model")
    config = VisionRuntimeConfig.from_environment(
        {
            "XINGBAO_VISION_PYTHON": sys.executable,
            "XINGBAO_VISION_SOURCE": "2",
            "XINGBAO_VISION_EMOTION_MODEL": str(emotion_model),
            "XINGBAO_VISION_NO_OBJECTS": "1",
            "XINGBAO_VISION_FACE_INTERVAL_SECONDS": "300",
            "XINGBAO_VISION_EMOTION_INTERVAL_SECONDS": "300",
            "XINGBAO_VISION_IMGSZ": "416",
            "XINGBAO_VISION_OBJECT_EVERY": "8",
            "XINGBAO_VISION_OBJECT_CONFIDENCE": "0.20",
            "XINGBAO_VISION_EMOTION_THRESHOLD": "0.68",
        }
    )

    assert config.source == "2"
    assert config.no_objects is True
    assert config.imgsz == 416
    assert config.object_every == 8
    assert config.object_confidence == 0.20
    assert config.emotion_threshold == 0.68
    assert config.face_interval_seconds == 300.0
    assert config.emotion_interval_seconds == 300.0
    assert "--no-objects" in config.command()
    assert config.command()[config.command().index("--face-interval-seconds") + 1] == "300.0"
    assert config.command()[config.command().index("--emotion-interval-seconds") + 1] == "300.0"
    assert config.command()[config.command().index("--conf") + 1] == "0.2"


def test_runtime_config_requires_only_enabled_models(tmp_path: Path, monkeypatch) -> None:
    entrypoint = tmp_path / "multimodal" / "vision_system" / "app.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("", encoding="utf-8")
    monkeypatch.setattr(vision_runtime, "PROJECT_ROOT", tmp_path)
    config = VisionRuntimeConfig(
        python_executable=sys.executable,
        model_path=tmp_path / "missing-yolo.pt",
        emotion_model_path=tmp_path / "missing-emotion.onnx",
        no_objects=True,
        no_emotion=True,
    )

    assert config.validate() == []


def test_process_bridge_delivers_only_high_level_vision_events(tmp_path: Path) -> None:
    script = tmp_path / "fake_vision.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "print('model warmup')",
                "print(json.dumps({'type': 'vision_state', 'source': 'vision', "
                "'payload': {'state': 'child_emotion_detected'}}))",
                "print(json.dumps({'type': 'raw_frame', 'source': 'vision'}))",
            ]
        ),
        encoding="utf-8",
    )
    emotion_model = tmp_path / "emotion.onnx"
    emotion_model.write_bytes(b"model")
    config = VisionRuntimeConfig(
        python_executable=sys.executable,
        emotion_model_path=emotion_model,
        no_objects=True,
    )
    config_command = [sys.executable, "-u", str(script)]
    object.__setattr__(config, "command", lambda: config_command)
    object.__setattr__(config, "validate", lambda: [])
    received: list[dict] = []
    logs: list[str] = []
    bridge = VisionProcessBridge(received.append, config=config, log_handler=logs.append)

    result = bridge.start()
    assert result["ok"] is True
    deadline = time.monotonic() + 2.0
    while bridge.status()["exit_code"] is None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert [item["payload"]["state"] for item in received] == [
        "child_emotion_detected"
    ]
    assert bridge.status()["events_delivered"] == 1
    assert bridge.status()["invalid_lines"] == 2
    assert any("model warmup" in line for line in logs)
    bridge.close()


def test_process_bridge_rate_limits_repeated_visual_state() -> None:
    received: list[dict] = []
    bridge = VisionProcessBridge(received.append)
    message = {
        "type": "vision_state",
        "source": "vision",
        "payload": {"state": "child_emotion_detected", "emotion": "sadness"},
    }

    assert bridge._allow_event(message) is True
    assert bridge._allow_event(message) is False


def test_process_bridge_restarts_failed_runtime_when_enabled(tmp_path: Path) -> None:
    script = tmp_path / "fake_vision_exit.py"
    script.write_text("raise SystemExit(2)\n", encoding="utf-8")
    config = VisionRuntimeConfig(
        python_executable=sys.executable,
        no_objects=True,
        no_emotion=True,
    )
    object.__setattr__(
        config,
        "command",
        lambda: [sys.executable, "-u", str(script)],
    )
    object.__setattr__(config, "validate", lambda: [])
    bridge = VisionProcessBridge(
        lambda _message: None,
        config=config,
        restart_delay_seconds=0.01,
    )

    assert bridge.start()["ok"] is True
    deadline = time.monotonic() + 2.0
    while bridge.status()["restart_count"] < 1 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert bridge.status()["restart_count"] >= 1
    bridge.close()
