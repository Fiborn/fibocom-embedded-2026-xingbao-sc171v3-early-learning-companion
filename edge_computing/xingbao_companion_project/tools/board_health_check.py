"""Board-side health checks before running the full Xingbao demo."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import uuid
from importlib.util import find_spec
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_MODULES = ("requests", "numpy", "sounddevice", "dashscope")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Xingbao central board readiness.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--check-arm",
        action="store_true",
        help="Explicitly send the arm service safety-stop probe. Do this only when no action should be running.",
    )
    parser.add_argument("--arm-host", default="127.0.0.1")
    parser.add_argument("--arm-port", type=int, default=8764)
    parser.add_argument(
        "--skip-ui",
        action="store_true",
        help="Do not test the touch desktop NDJSON bridge.",
    )
    parser.add_argument(
        "--skip-wake-model",
        action="store_true",
        help="Do not load the local wake-word model.",
    )
    parser.add_argument(
        "--check-vision",
        action="store_true",
        help="Validate the configured vision Python, model files, OpenCV, and FERPlus loading.",
    )
    parser.add_argument(
        "--vision-no-objects",
        action="store_true",
        help="Validate board-safe face/emotion mode without requiring Ultralytics.",
    )
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    checks.append(_check_python())
    checks.append(_check_path("main.py", Path("main.py").exists()))
    checks.append(_check_path("config/settings.json", Path("config/settings.json").exists()))
    checks.extend(_check_import(module_name) for module_name in REQUIRED_MODULES)
    if not args.skip_wake_model:
        checks.append(_check_wake_model())
    if args.check_vision:
        checks.append(_check_vision_runtime(force_no_objects=args.vision_no_objects))
    checks.append(_check_api_key())
    if not args.skip_ui:
        checks.append(_check_board_ui(args.host, args.port, args.timeout))
    # stay_still is intentionally opt-in: it is an emergency-safe action but
    # must not interrupt a child's ongoing physical expression during a normal
    # readiness check.
    if args.check_arm:
        checks.append(_check_arm_service(args.arm_host, args.arm_port, args.timeout))

    ok = all(item["ok"] for item in checks)
    result = {"ok": ok, "checks": checks}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


def _check_python() -> dict[str, Any]:
    version = sys.version_info
    ok = version.major == 3 and version.minor >= 8
    return {
        "name": "python_version",
        "ok": ok,
        "value": f"{version.major}.{version.minor}.{version.micro}",
        "expect": ">=3.8",
    }


def _check_path(name: str, ok: bool) -> dict[str, Any]:
    return {"name": f"path:{name}", "ok": ok}


def _check_import(module_name: str, timeout: float = 5.0) -> dict[str, Any]:
    """Check an optional runtime dependency in a child process only."""
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib; importlib.import_module({!r})".format(module_name),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(0.1, float(timeout)),
        )
    except Exception as exc:
        return {
            "name": f"import:{module_name}",
            "ok": False,
            "error": "ImportCheckFailed",
            "message": str(exc),
        }
    if completed.returncode != 0:
        return {
            "name": f"import:{module_name}",
            "ok": False,
            "error": "ImportFailed",
            "message": (completed.stderr or completed.stdout).strip()[-500:],
        }
    return {"name": f"import:{module_name}", "ok": True}


def _check_module_spec(module_name: str) -> dict[str, Any]:
    """Confirm a module is discoverable without importing its device runtime."""
    try:
        found = find_spec(module_name) is not None
    except (ImportError, AttributeError, ValueError) as exc:
        return {
            "name": f"module_spec:{module_name}",
            "ok": False,
            "validation": "module_spec_only",
            "error": type(exc).__name__,
        }
    return {
        "name": f"module_spec:{module_name}",
        "ok": found,
        "validation": "module_spec_only",
    }


def _select_capture_source(pactl_sources: str) -> str:
    """Select the first real PulseAudio input and ignore null-sink monitors."""
    for line in str(pactl_sources or "").splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        source = fields[1].strip()
        if not source or source.endswith(".monitor") or source.startswith("auto_null"):
            continue
        return source
    return ""


def _check_api_key() -> dict[str, Any]:
    value = os.getenv("DASHSCOPE_API_KEY", "")
    return {
        "name": "env:DASHSCOPE_API_KEY",
        "ok": bool(value.strip()),
        "message": "set" if value.strip() else "missing",
    }


def _check_arm_service(host: str, port: int, timeout: float) -> dict[str, Any]:
    """Explicit safety-stop probe for the isolated loopback arm service.

    This uses only ``stay_still`` and is never part of the default readiness
    path, because a safety stop is intentionally allowed to interrupt motion.
    """
    payload = {"request_id": str(uuid.uuid4()), "arm_action": "stay_still"}
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            raw = _read_one_line(sock)
        response = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        return {
            "name": "arm_action_service",
            "ok": False,
            "host": host,
            "port": port,
            "error": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "name": "arm_action_service",
        "ok": bool(isinstance(response, dict) and response.get("ok", False)),
        "host": host,
        "port": port,
        "response": response,
    }


def _check_wake_model() -> dict[str, Any]:
    try:
        from core.settings import AppSettings
        from multimodal.wake_word import OpenWakeWordDetector, WakeWordConfig

        settings = AppSettings.load()
        config = WakeWordConfig.from_settings(settings)
        config.validate_files()
        detector = OpenWakeWordDetector(config)
        detector._get_model()
    except Exception as exc:
        return {
            "name": "wake_model",
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "name": "wake_model",
        "ok": True,
        "model_path": str(config.model_path),
    }


def _check_vision_runtime(*, force_no_objects: bool = False) -> dict[str, Any]:
    from multimodal.vision_runtime import VisionRuntimeConfig

    config = VisionRuntimeConfig.from_environment()
    no_objects = bool(force_no_objects or config.no_objects)
    if force_no_objects and not config.no_objects:
        from dataclasses import replace

        config = replace(config, no_objects=True)
    errors = config.validate()
    if errors:
        return {
            "name": "vision_runtime",
            "ok": False,
            "errors": errors,
            "no_objects": no_objects,
        }

    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "import cv2",
            "import numpy",
            "emotion = Path(sys.argv[1])",
            "net = cv2.dnn.readNetFromONNX(str(emotion))",
            "assert net is not None",
            "cascade = Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'",
            "classifier = cv2.CascadeClassifier(str(cascade))",
            "assert not classifier.empty()",
            "if sys.argv[2] == 'objects':",
            "    import ultralytics",
            "    assert Path(sys.argv[3]).is_file()",
        ]
    )
    try:
        completed = subprocess.run(
            [
                config.python_executable,
                "-c",
                script,
                str(config.emotion_model_path),
                "no-objects" if no_objects else "objects",
                str(config.model_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20.0,
        )
    except Exception as exc:
        return {
            "name": "vision_runtime",
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "no_objects": no_objects,
        }
    return {
        "name": "vision_runtime",
        "ok": completed.returncode == 0,
        "python": config.python_executable,
        "source": config.source,
        "emotion_model": str(config.emotion_model_path),
        "object_model": None if no_objects else str(config.model_path),
        "no_objects": no_objects,
        "message": (completed.stderr or completed.stdout).strip()[-1000:],
    }


def _check_board_ui(host: str, port: int, timeout: float) -> dict[str, Any]:
    payload = {
        "version": "1.0",
        "request_id": str(uuid.uuid4()),
        "type": "assistant_output",
        "source": "central_health_check",
        "target": "desktop_ui",
        "payload": {
            "speech": {"text": "", "request_tts": False, "interrupt": False},
            "screen_text": "central connected",
            "screen_expression": {"name": "smile", "duration_ms": 1000},
            "arm_action": "stay_still",
            "led": {"mode": "off", "duration_ms": 1000},
            "ui_command": None,
        },
    }
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            raw = _read_one_line(sock)
        response = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        return {
            "name": "board_ui_bridge",
            "ok": False,
            "host": host,
            "port": port,
            "error": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "name": "board_ui_bridge",
        "ok": bool(isinstance(response, dict) and response.get("ok", False)),
        "host": host,
        "port": port,
        "response": response,
    }


def _read_one_line(sock: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(chunks).split(b"\n", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
