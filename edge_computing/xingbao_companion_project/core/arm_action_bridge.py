"""Reserved high-level bridge for board arm actions."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


VISION_HIGH_FIVE_ACTIONS = frozenset(
    {
        "vision_high_five_11",
        "vision_high_five_12",
        "vision_high_five_13",
        "vision_high_five_21",
        "vision_high_five_22",
        "vision_high_five_23",
    }
)
ARM_ACTIONS = frozenset({"bow", "high_five", "mouth", "nod", "shake_head"}) | VISION_HIGH_FIVE_ACTIONS


def _configured_port(name: str, default: int) -> int:
    """Read one local IPC port and reject invalid runtime configuration early."""
    raw = os.getenv(name, str(default)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid_{name.lower()}:{raw}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"invalid_{name.lower()}:{raw}")
    return port


# Both services receive these values from /home/fibo/.config/xingbao/runtime.env.
# Defaults keep the reviewed local-only IPC topology available for development.
ARM_ACTION_HOST = os.getenv("XINGBAO_ARM_ACTION_HOST", "127.0.0.1").strip() or "127.0.0.1"
ARM_ACTION_PORT = _configured_port("XINGBAO_ARM_ACTION_PORT", 8764)
HAND_RECOGNITION_CONTROL_HOST = (
    os.getenv("XINGBAO_HAND_RECOGNITION_CONTROL_HOST", "127.0.0.1").strip() or "127.0.0.1"
)
HAND_RECOGNITION_CONTROL_PORT = _configured_port("XINGBAO_HAND_RECOGNITION_CONTROL_PORT", 10001)
VISION_POINT_ACTION_HOST = (
    os.getenv("XINGBAO_VISION_POINT_ACTION_HOST", "127.0.0.1").strip() or "127.0.0.1"
)
VISION_POINT_ACTION_PORT = _configured_port("XINGBAO_VISION_POINT_ACTION_PORT", 10000)
VISION_POINT_COMMANDS = frozenset({"11", "12", "13", "21", "22", "23"})
# Voice commands stay deliberately small and map only to reviewed, high-level
# expressions.  They never contain hardware angles, serial commands, or other
# low-level controls.
VOICE_ACTION_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "high_five",
        (
            "击掌",
            "击个掌",
            "拍个掌",
            # Observed board ASR rendering of a child's "击个掌".  Keep this
            # alias narrow so unrelated speech cannot trigger arm motion.
            "叽叽掌",
            "highfive",
            "high-five",
            "握握手",
            "握手",
        ),
    ),
    ("shake_head", ("摇摇头", "摇头")),
)
VOICE_ACTION_NEGATIONS = ("不", "不要", "别", "不用")
VOICE_ACTION_EXPECTED_DURATION_SECONDS = {
    "high_five": 9,
    "shake_head": 3,
}
# One invitation may include up to three fixed-position redirects and a final
# neutral return.  The arm service owns the bounded session; callers still
# cannot pass poses, speed, or arbitrary timing.
VISION_HIGH_FIVE_EXPECTED_DURATION_SECONDS = 24


class ArmActionRateLimiter:
    """Prevent repeated recognized speech from flooding the arm service."""

    def __init__(self, min_interval_seconds: float = 2.0) -> None:
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._lock = threading.Lock()
        self._last_action_at = float("-inf")

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_action_at < self.min_interval_seconds:
                return False
            self._last_action_at = now
            return True


_VOICE_ARM_RATE_LIMITER = ArmActionRateLimiter()


@dataclass(frozen=True)
class ArmActionRequest:
    """A sanitized high-level arm action request."""

    arm_action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm_action": self.arm_action,
        }


ArmActionHandler = Callable[[ArmActionRequest], dict]


class ArmActionBridge:
    """Validates high-level arm actions and delegates to a hardware handler."""

    def __init__(self, handler: ArmActionHandler | None = None) -> None:
        self.handler = handler

    def execute(
        self,
        arm_action: str,
    ) -> dict[str, Any]:
        clean_action = (arm_action or "").strip()
        if clean_action not in ARM_ACTIONS:
            return {
                "ok": False,
                "action": "arm_action",
                "arm_action": "stay_still",
                "requested_arm_action": clean_action,
                "error": "unsupported_arm_action",
            }
        request = ArmActionRequest(arm_action=clean_action)
        if self.handler is None:
            return {
                "ok": True,
                "action": "arm_action",
                "arm_action": request.arm_action,
                "implemented": False,
                "implemented_by": "board_hardware_team",
                "message": "validated_only",
            }
        result = self.handler(request)
        if not isinstance(result, dict):
            return {
                "ok": False,
                "action": "arm_action",
                "arm_action": request.arm_action,
                "error": "invalid_handler_result",
            }
        return {
            "action": "arm_action",
            "arm_action": request.arm_action,
            **result,
        }


def arm_action_for_voice_text(user_text: str) -> str:
    """Return the fixed high-level arm action matched by recognized speech."""
    compact = "".join(str(user_text or "").split())
    for arm_action, phrases in VOICE_ACTION_PHRASES:
        for phrase in phrases:
            position = compact.find(phrase)
            if position < 0:
                continue
            # Inspect the short clause before the requested action.  A child
            # may say "我不要和你握手"; the negation is not necessarily
            # immediately adjacent to the word "握手".
            prefix = compact[max(0, position - 8) : position]
            if any(negation in prefix for negation in VOICE_ACTION_NEGATIONS):
                continue
            return arm_action
    return ""


def send_arm_action_ndjson(
    arm_action: str,
    *,
    host: str = ARM_ACTION_HOST,
    port: int = ARM_ACTION_PORT,
    timeout: float = 0.5,
    wait_for_response: bool = False,
) -> dict[str, Any] | None:
    """Send only a whitelisted action name, optionally waiting for its receipt."""
    clean_action = (arm_action or "").strip()
    if clean_action not in ARM_ACTIONS:
        raise ValueError(f"unsupported arm action: {clean_action}")
    payload = (json.dumps({"arm_action": clean_action}, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        if not wait_for_response:
            return None
        raw = b""
        while b"\n" not in raw:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
        if not raw:
            return {
                "type": "command_result",
                "ok": False,
                "error": "empty_arm_response",
            }
        try:
            response = json.loads(raw.split(b"\n", 1)[0].decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {
                "type": "command_result",
                "ok": False,
                "error": "invalid_arm_response",
                "message": str(exc),
            }
        return response if isinstance(response, dict) else {
            "type": "command_result",
            "ok": False,
            "error": "invalid_arm_response_shape",
        }


def send_hand_recognition_control(
    command: str,
    *,
    host: str = HAND_RECOGNITION_CONTROL_HOST,
    port: int = HAND_RECOGNITION_CONTROL_PORT,
    timeout: float = 0.5,
) -> dict[str, Any]:
    """Control or inspect the local, fixed-grid high-five vision runtime."""
    clean_command = str(command or "").strip().lower()
    if clean_command not in {"enable", "disable", "status"}:
        raise ValueError(f"unsupported hand recognition command: {clean_command}")
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((clean_command + "\n").encode("utf-8"))
        raw = sock.makefile("r", encoding="utf-8").readline()
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("invalid_hand_recognition_response")
    return response


def send_vision_point_command(
    command: str,
    *,
    host: str = VISION_POINT_ACTION_HOST,
    port: int = VISION_POINT_ACTION_PORT,
    timeout: float = 0.8,
) -> dict[str, Any]:
    """Send one reviewed six-point command to the local 10000 compatibility port."""
    clean_command = str(command or "").strip()
    if clean_command not in VISION_POINT_COMMANDS:
        raise ValueError(f"unsupported_vision_point_command:{clean_command}")
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((clean_command + "\n").encode("utf-8"))
        raw = b""
        while b"\n" not in raw:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    if not raw:
        return {"ok": False, "error": "empty_vision_point_response", "command": clean_command}
    try:
        response = json.loads(raw.split(b"\n", 1)[0].decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": "invalid_vision_point_response",
            "command": clean_command,
            "message": str(exc),
        }
    return response if isinstance(response, dict) else {
        "ok": False,
        "error": "invalid_vision_point_response_shape",
        "command": clean_command,
    }


def enable_hand_recognition() -> dict[str, Any]:
    return send_hand_recognition_control("enable")


def get_hand_recognition_status() -> dict[str, Any]:
    """Return only high-level session state; never expose camera frames."""
    return send_hand_recognition_control("status")


def dispatch_voice_arm_action(
    user_text: str,
    *,
    sender: Callable[[str], None] = send_arm_action_ndjson,
    hand_recognition_enabler: Callable[[], Any] = enable_hand_recognition,
    rate_limiter: ArmActionRateLimiter | None = None,
) -> dict[str, Any]:
    """Queue a matched voice action without blocking the voice interaction loop."""
    arm_action = arm_action_for_voice_text(user_text)
    if not arm_action:
        return {"matched": False, "queued": False, "arm_action": ""}
    active_rate_limiter = rate_limiter or _VOICE_ARM_RATE_LIMITER
    if not active_rate_limiter.allow():
        return {
            "matched": True,
            "queued": False,
            "arm_action": arm_action,
            "reason": "rate_limited",
        }

    def send_quietly() -> None:
        if arm_action == "high_five":
            try:
                hand_recognition_enabler()
                return
            except (OSError, ValueError, json.JSONDecodeError):
                # A spoken high-five stays useful if the optional vision
                # runtime is unavailable: only the reviewed fallback action
                # is sent, never a pose or timing value.
                pass
        try:
            sender(arm_action)
        except (OSError, ValueError):
            return

    threading.Thread(
        target=send_quietly,
        name="voice-arm-action",
        daemon=True,
    ).start()
    result = {
        "matched": True,
        "queued": True,
        "arm_action": arm_action,
    }
    if arm_action == "high_five":
        result.update({
            "port": HAND_RECOGNITION_CONTROL_PORT,
            "hand_recognition_enable": True,
            "vision_point_port": VISION_POINT_ACTION_PORT,
            "fallback_port": ARM_ACTION_PORT,
            "expected_duration_seconds": VISION_HIGH_FIVE_EXPECTED_DURATION_SECONDS,
            "fallback_expected_duration_seconds": VOICE_ACTION_EXPECTED_DURATION_SECONDS[arm_action],
        })
    else:
        result.update({
            "port": ARM_ACTION_PORT,
            "expected_duration_seconds": VOICE_ACTION_EXPECTED_DURATION_SECONDS[arm_action],
        })
    return result
