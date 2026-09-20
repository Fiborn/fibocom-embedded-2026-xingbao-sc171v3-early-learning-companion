#!/usr/bin/env python3
"""Local six-point compatibility endpoint for the Xingbao SO-101 arm.

This process owns TCP 127.0.0.1:10000 only.  It accepts one reviewed grid
code (11, 12, 13, 21, 22, or 23), translates it to the corresponding
high-level arm action, and forwards it to the sole hardware owner on 8764.
It never opens the serial device or accepts joint angles, speeds, or scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
from typing import Any


POINT_ACTIONS = {
    "11": "vision_high_five_11",
    "12": "vision_high_five_12",
    "13": "vision_high_five_13",
    "21": "vision_high_five_21",
    "22": "vision_high_five_22",
    "23": "vision_high_five_23",
}


def _port(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid_{name.lower()}:{raw}") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"invalid_{name.lower()}:{raw}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xingbao six-point arm compatibility endpoint")
    parser.add_argument(
        "--host",
        default=os.getenv("XINGBAO_VISION_POINT_ACTION_HOST", "127.0.0.1").strip() or "127.0.0.1",
    )
    parser.add_argument("--port", type=int, default=_port("XINGBAO_VISION_POINT_ACTION_PORT", 10000))
    parser.add_argument(
        "--arm-host",
        default=os.getenv("XINGBAO_ARM_ACTION_HOST", "127.0.0.1").strip() or "127.0.0.1",
    )
    parser.add_argument("--arm-port", type=int, default=_port("XINGBAO_ARM_ACTION_PORT", 8764))
    parser.add_argument("--timeout", type=float, default=0.8)
    return parser.parse_args()


def forward_point(command: str, *, arm_host: str, arm_port: int, timeout: float) -> dict[str, Any]:
    """Forward only a reviewed six-point action to the existing 8764 server."""
    action = POINT_ACTIONS.get(str(command or "").strip())
    if action is None:
        return {"ok": False, "error": "invalid_command", "command": str(command or "").strip()}
    payload = (json.dumps({"arm_action": action}, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        with socket.create_connection((arm_host, int(arm_port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            raw = b""
            while b"\n" not in raw:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
    except OSError as exc:
        return {
            "ok": False,
            "error": "arm_endpoint_unavailable",
            "command": command,
            "upstream": f"{arm_host}:{arm_port}",
            "detail": type(exc).__name__,
        }
    if not raw:
        return {"ok": False, "error": "empty_arm_response", "command": command}
    try:
        response = json.loads(raw.split(b"\n", 1)[0].decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": "invalid_arm_response", "command": command, "detail": str(exc)}
    if not isinstance(response, dict):
        return {"ok": False, "error": "invalid_arm_response_shape", "command": command}
    return {
        **response,
        "vision_point_command": command,
        "forwarded_arm_action": action,
        "via": "vision_point_port_10000",
    }


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        command = self.rfile.readline(64).decode("utf-8", errors="replace").strip()
        config: argparse.Namespace = self.server.config  # type: ignore[attr-defined]
        response = forward_point(
            command,
            arm_host=config.arm_host,
            arm_port=config.arm_port,
            timeout=max(0.1, float(config.timeout)),
        )
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class PointCommandServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    args = parse_args()
    if args.host != "127.0.0.1":
        raise ValueError("vision_point_host_must_be_loopback")
    with PointCommandServer((args.host, args.port), _Handler) as server:
        server.config = args  # type: ignore[attr-defined]
        print(
            f"vision point adapter ready: {args.host}:{args.port} -> {args.arm_host}:{args.arm_port}",
            flush=True,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
