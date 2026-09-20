"""On-site acceptance check for camera, models, and central vision routing."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multimodal.vision_runtime import VisionRuntimeConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the configured camera vision runtime without changing board data."
    )
    parser.add_argument(
        "--source",
        default="",
        help="Override XINGBAO_VISION_SOURCE with a camera index or test video.",
    )
    parser.add_argument("--max-frames", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--check-central",
        action="store_true",
        help="Send one silent neutral vision event through the central loopback service.",
    )
    parser.add_argument("--central-host", default="127.0.0.1")
    parser.add_argument("--central-port", type=int, default=8766)
    args = parser.parse_args()

    config = VisionRuntimeConfig.from_environment()
    if args.source:
        config = replace(config, source=str(args.source))
    checks = [
        _camera_probe(
            config,
            max_frames=max(1, min(30, int(args.max_frames))),
            timeout=max(5.0, min(180.0, float(args.timeout))),
        )
    ]
    if args.check_central:
        checks.append(
            _central_probe(
                args.central_host,
                args.central_port,
                timeout=min(10.0, max(0.2, float(args.timeout))),
            )
        )
    result = {
        "ok": all(check.get("ok", False) for check in checks),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def _camera_probe(
    config: VisionRuntimeConfig,
    *,
    max_frames: int,
    timeout: float,
) -> dict[str, Any]:
    errors = config.validate()
    if errors:
        return {
            "name": "vision_camera_pipeline",
            "ok": False,
            "errors": errors,
        }
    command = config.command()
    command[command.index("--xingbao-events")] = "--json"
    command.extend(["--max-frames", str(max_frames)])
    try:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "name": "vision_camera_pipeline",
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "command": command,
        }

    frames = _parse_frame_payloads(completed.stdout)
    valid = [
        frame
        for frame in frames
        if all(
            type(frame.get(key)) is int
            for key in (
                "return_code",
                "drink_return_code",
                "emotion_return_code",
            )
        )
    ]
    return {
        "name": "vision_camera_pipeline",
        "ok": completed.returncode == 0 and len(valid) >= max_frames,
        "return_code": completed.returncode,
        "frames_requested": max_frames,
        "frames_received": len(valid),
        "source": config.source,
        "no_objects": config.no_objects,
        "emotion_enabled": not config.no_emotion,
        "last_frame": valid[-1] if valid else None,
        "message": (completed.stderr or "").strip()[-1000:],
        "command": command,
    }


def _central_probe(host: str, port: int, *, timeout: float) -> dict[str, Any]:
    message = {
        "version": "1.0",
        "message_id": f"vision-acceptance-{uuid.uuid4()}",
        "type": "vision_state",
        "source": "vision",
        "priority": 1,
        "payload": {
            "state": "child_emotion_detected",
            "emotion": "neutral",
            "emotion_code": 8,
            "confidence": 1.0,
            "simulated": True,
        },
    }
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(
                (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            )
            response = json.loads(
                sock.makefile("r", encoding="utf-8-sig").readline()
            )
    except Exception as exc:
        return {
            "name": "vision_central_route",
            "ok": False,
            "host": host,
            "port": port,
            "error": type(exc).__name__,
            "message": str(exc),
        }
    payload = response.get("payload") if isinstance(response, dict) else None
    status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
    return {
        "name": "vision_central_route",
        "ok": bool(
            isinstance(response, dict)
            and response.get("ok")
            and status in {"queued", "finished", "accepted"}
        ),
        "host": host,
        "port": port,
        "response": response,
    }


def _parse_frame_payloads(output: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for line in str(output or "").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and type(payload.get("frame")) is int
            and isinstance(payload.get("faces"), list)
        ):
            frames.append(payload)
    return frames


if __name__ == "__main__":
    raise SystemExit(main())
