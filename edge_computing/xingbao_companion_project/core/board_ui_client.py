"""NDJSON client for the Xingbao touch desktop UI bridge."""

from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any

from core.arm_action_bridge import ARM_ACTION_HOST, ARM_ACTION_PORT, send_arm_action_ndjson
from core.coordinator import CoordinationPlan
from core.expression import ExpressionOutput
from core.kids_visual_tools_bridge import VISUAL_TOOLS_TARGET, build_visual_tools_ui_command


SCREEN_EXPRESSIONS = {
    "neutral",
    "smile",
    "thinking",
    "curious",
    "sad",
    "surprised",
    "sleepy",
}
LED_MODES = {
    "off",
    "blue_breath",
    "warm_breath",
    "yellow_blink",
    "rainbow",
    "red_flash",
}


def _safe_subtitle_priority(value: str) -> str:
    return "dialogue" if str(value or "").strip().casefold() == "dialogue" else "external"
ARM_ACTIONS = {
    "stay_still",
    "wave_hand",
    "nod",
    "shake_head",
    "point_left",
    "point_right",
    "small_dance",
    "bow",
    "high_five",
}


@dataclass(frozen=True)
class BoardUIClient:
    """Sends central-controller output to the Pygame desktop bridge."""

    host: str = "127.0.0.1"
    port: int = 8765
    timeout: float = 3.0
    arm_host: str = ARM_ACTION_HOST
    arm_port: int = ARM_ACTION_PORT
    arm_timeout: float = 12.0

    def send_assistant_output(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send one assistant_output envelope and return command_result."""
        encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with socket.create_connection((self.host, int(self.port)), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(encoded)
            raw = _read_one_line(sock)
        try:
            response = json.loads(raw.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            return {
                "type": "command_result",
                "ok": False,
                "error": "invalid_response_json",
                "message": str(exc),
                "raw": raw.decode("utf-8", errors="replace"),
            }
        return response if isinstance(response, dict) else {
            "type": "command_result",
            "ok": False,
            "error": "invalid_response_shape",
            "raw": response,
        }

    def send_ui_command(
        self,
        command: dict[str, Any] | None,
        *,
        screen_text: str = "",
        expression: str = "neutral",
        led_mode: str = "off",
        duration_ms: int = 4000,
        subtitle_priority: str = "external",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a direct UI state update without asking the desktop to speak."""
        ui_command = dict(command) if isinstance(command, dict) else None
        camera_snapshot = None
        if isinstance(ui_command, dict) and ui_command.get("name") == "camera_snapshot":
            camera_snapshot = {
                key: ui_command[key]
                for key in ("action", "data_uri", "width", "height", "mirror")
                if key in ui_command
            }
        message = {
            "version": "1.0",
            "request_id": request_id or str(uuid.uuid4()),
            "type": "assistant_output",
            "source": "central_controller",
            "target": "desktop_ui",
            "payload": {
                "speech": {
                    "text": "",
                    "request_tts": False,
                    "interrupt": False,
                },
                "screen_text": str(screen_text or ""),
                "subtitle_priority": _safe_subtitle_priority(subtitle_priority),
                "screen_expression": {
                    "name": _safe_expression(expression),
                    "duration_ms": max(200, min(30000, int(duration_ms or 4000))),
                },
                "arm_action": "stay_still",
                "led": {
                    "mode": _safe_led(led_mode),
                },
                "ui_command": ui_command,
                "camera_snapshot": camera_snapshot,
            },
        }
        response = self.send_assistant_output(message)
        return {
            "request": message,
            "response": response,
            "ok": bool(response.get("ok")),
        }

    def send_plan(
        self,
        plan: CoordinationPlan,
        *,
        duration_ms: int = 4000,
        request_id: str | None = None,
        include_screen_text: bool = True,
        subtitle_priority: str = "external",
    ) -> dict[str, Any]:
        """Convert one coordination plan to assistant_output and send it.

        ``include_screen_text=False`` preserves non-text plan effects (UI
        expression, LED, arm action, and tool command) while protecting a
        higher-priority dialogue subtitle already shown on the desktop.
        """
        message = assistant_output_from_plan(
            plan,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        if not include_screen_text:
            message["payload"]["screen_text"] = ""
        message["payload"]["subtitle_priority"] = _safe_subtitle_priority(subtitle_priority)
        response = self.send_assistant_output(message)
        arm_action = arm_action_from_plan(plan)
        arm_result = {"ok": True, "skipped": True, "arm_action": ""}
        if arm_action:
            arm_result = self.send_arm_action(arm_action)
        return {
            "request": message,
            "response": response,
            "arm": arm_result,
            "ok": bool(response.get("ok")) and bool(arm_result.get("ok")),
        }

    def send_dialogue_subtitle_state(
        self,
        active: bool,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Tell the touch UI whether dialogue owns the subtitle strip."""
        message = {
            "version": "1.0",
            "request_id": request_id or str(uuid.uuid4()),
            "type": "assistant_output",
            "source": "central_controller",
            "target": "desktop_ui",
            "payload": {"dialogue_subtitle_state": {"active": bool(active)}},
        }
        response = self.send_assistant_output(message)
        return {"request": message, "response": response, "ok": bool(response.get("ok"))}

    def send_xingbao_scene(
        self,
        scene_id: int,
        *,
        source: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Select a validated GIF scene on the Wayland touch UI."""
        if type(scene_id) is not int or not 0 <= scene_id <= 27:
            raise ValueError("scene_id must be an integer from 0 through 27")
        message = {
            "version": "1.0",
            "request_id": request_id or str(uuid.uuid4()),
            "type": "assistant_output",
            "source": "central_controller",
            "target": "desktop_ui",
            "payload": {
                "xingbao_scene": {"id": scene_id, "source": str(source or "unknown")},
            },
        }
        response = self.send_assistant_output(message)
        return {"request": message, "response": response, "ok": bool(response.get("ok"))}

    def probe_plan(
        self,
        plan: CoordinationPlan,
        *,
        duration_ms: int = 1500,
    ) -> dict[str, Any]:
        """Check UI availability and update expression without executing the tool."""
        message = assistant_output_from_plan(plan, duration_ms=duration_ms)
        message["payload"]["ui_command"] = None
        message["payload"]["speech"] = {
            "text": "",
            "request_tts": False,
            "interrupt": False,
        }
        response = self.send_assistant_output(message)
        return {
            "request": message,
            "response": response,
            "ok": bool(response.get("ok")),
        }

    def send_arm_action(
        self,
        arm_action: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one high-level arm action directly to the arm IPC service."""
        message = assistant_arm_action_output(arm_action, request_id=request_id)
        response = send_arm_action_ndjson(
            message["arm_action"],
            host=self.arm_host,
            port=self.arm_port,
            timeout=self.arm_timeout,
            wait_for_response=True,
        )
        safe_response = response if isinstance(response, dict) else {
            "type": "command_result",
            "ok": False,
            "error": "missing_arm_response",
        }
        return {
            "request": message,
            "response": safe_response,
            "ok": bool(safe_response.get("ok")),
        }

    def send_game_command(
        self,
        command: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one fixed game_command to the current touch game."""
        message = assistant_game_command_output(command, request_id=request_id)
        response = self.send_assistant_output(message)
        game_response = extract_game_response(response)
        return {
            "request": message,
            "response": response,
            "game_response": game_response,
            "ok": bool(response.get("ok")) and bool((game_response or {}).get("ok", True)),
        }


def board_action_from_plan(plan: CoordinationPlan) -> dict[str, Any] | None:
    """Return the board UI command for a plan, or None when no fixed action matched."""
    return _ui_command_for_plan(plan)


def arm_action_from_plan(plan: CoordinationPlan) -> str:
    """Return the direct arm IPC action for a coordination plan."""
    if plan.tool_request is not None and plan.tool_request.target == "mini_game_hub":
        return ""
    feedback = _feedback_from_events(plan.events)
    action = str(feedback.get("arm_action") or "").strip()
    return _arm_ipc_action(action)


def plan_has_board_action(plan: CoordinationPlan) -> bool:
    """Whether the fixed action line should execute for this plan."""
    return board_action_from_plan(plan) is not None


def assistant_arm_action_output(
    arm_action: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the raw arm IPC payload for one high-level action."""
    clean_action = _arm_ipc_action(str(arm_action or ""))
    if not clean_action:
        raise ValueError(f"unsupported arm action: {arm_action}")
    return {"arm_action": clean_action}


def assistant_game_command_output(
    command: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build an assistant_output envelope carrying a fixed game command."""
    safe_command = dict(command or {})
    safe_command["type"] = "game_command"
    if not str(safe_command.get("game_id") or "").strip():
        safe_command["game_id"] = "current_game"
    return {
        "version": "1.0",
        "request_id": request_id or str(uuid.uuid4()),
        "type": "assistant_output",
        "source": "central_controller",
        "target": "desktop_ui",
        "payload": {
            "game_command": safe_command,
        },
    }


def extract_game_response(command_result: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a game_response item from a desktop command_result."""
    results = command_result.get("results")
    if not isinstance(results, list):
        return None
    for item in results:
        if isinstance(item, dict) and item.get("type") == "game_response":
            return item
    return None


def assistant_output_from_plan(
    plan: CoordinationPlan,
    *,
    duration_ms: int = 4000,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the desktop UI bridge message from a central coordination plan."""
    output = plan.expression_output
    feedback = _feedback_from_events(plan.events)
    expression = _safe_expression(
        str(feedback.get("screen_expression") or _screen_expression_for(output.expression))
    )
    led_mode = _safe_led(str(feedback.get("led_mode") or _led_mode_for(output.expression)))
    payload: dict[str, Any] = {
        "speech": {
            "text": "",
            "request_tts": False,
            "interrupt": output.interrupt_policy == "interrupt",
        },
        "screen_text": output.screen_text,
        "screen_expression": {
            "name": expression,
            "duration_ms": max(200, min(30000, int(duration_ms or 4000))),
        },
        "arm_action": "stay_still",
        "led": {
            "mode": led_mode,
            "duration_ms": max(200, min(30000, int(duration_ms or 4000))),
        },
        "ui_command": _ui_command_for_plan(plan),
    }
    return {
        "version": "1.0",
        "request_id": request_id or str(uuid.uuid4()),
        "type": "assistant_output",
        "source": "central_controller",
        "target": "desktop_ui",
        "payload": payload,
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
    data = b"".join(chunks)
    return data.split(b"\n", 1)[0]


def _ui_command_for_plan(plan: CoordinationPlan) -> dict[str, Any] | None:
    if plan.intent.intent == "exit_activity":
        return {"name": "return_to_desktop", "params": {}}
    request = plan.tool_request
    if request is None:
        return None
    if request.target == VISUAL_TOOLS_TARGET or request.target.startswith(
        f"{VISUAL_TOOLS_TARGET}:"
    ):
        return build_visual_tools_ui_command(request.target)
    if request.target != "mini_game_hub":
        return None
    game_id = _requested_game_id(plan.user_text)
    if game_id:
        return {"name": "start_game", "params": {"game_id": game_id, "difficulty": 1}}
    return {"name": "open_game_center", "params": {}}


def _requested_game_id(text: str) -> str:
    compact = (text or "").replace(" ", "")
    mapping = (
        ("找颜色", "color_game"),
        ("颜色游戏", "color_game"),
        ("颜色", "color_game"),
        ("色彩", "color_game"),
        ("认形状", "shape_game"),
        ("形状游戏", "shape_game"),
        ("形状", "shape_game"),
        ("图形", "shape_game"),
        ("记忆游戏", "memory_game"),
        ("记忆", "memory_game"),
        ("小路", "memory_game"),
        ("数数游戏", "counting_game"),
        ("数数", "counting_game"),
        ("数字", "counting_game"),
        ("英语游戏", "english_game"),
        ("英语", "english_game"),
        ("英文", "english_game"),
        ("挑战", "skill_game"),
    )
    for keyword, game_id in mapping:
        if keyword in compact:
            return game_id
    return ""


def _feedback_from_events(events: tuple[dict[str, Any], ...]) -> dict[str, str]:
    for event in reversed(events):
        feedback = event.get("feedback")
        if not isinstance(feedback, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                feedback = payload.get("feedback")
        if isinstance(feedback, dict):
            result: dict[str, str] = {}
            expression = str(feedback.get("screen_expression") or feedback.get("expression") or "")
            led_mode = str(feedback.get("led_mode") or feedback.get("light") or "")
            arm_action = str(feedback.get("arm_action") or feedback.get("action") or "")
            if expression:
                result["screen_expression"] = _safe_expression(expression)
            if led_mode:
                result["led_mode"] = _safe_led(led_mode)
            if arm_action:
                result["arm_action"] = arm_action
            if result:
                return result
    return {}


def _screen_expression_for(expression: str) -> str:
    mapping = {
        "smile": "smile",
        "happy": "smile",
        "encouraging": "smile",
        "caring": "smile",
        "comforting": "smile",
        "listening": "curious",
        "thinking": "thinking",
        "confused": "curious",
        "calm": "neutral",
        "neutral": "neutral",
        "sleepy": "sleepy",
        "sad": "sad",
        "surprised": "surprised",
    }
    return mapping.get((expression or "").strip(), "neutral")


def _led_mode_for(expression: str) -> str:
    mapping = {
        "happy": "warm_breath",
        "smile": "warm_breath",
        "encouraging": "warm_breath",
        "caring": "blue_breath",
        "comforting": "blue_breath",
        "listening": "blue_breath",
        "thinking": "blue_breath",
    }
    return mapping.get((expression or "").strip(), "off")


def _safe_expression(value: str) -> str:
    return value if value in SCREEN_EXPRESSIONS else "neutral"


def _safe_led(value: str) -> str:
    return value if value in LED_MODES else "off"


def _safe_arm(value: str) -> str:
    return value if value in ARM_ACTIONS else "stay_still"


def _arm_ipc_action(value: str) -> str:
    clean = str(value or "").strip()
    if clean == "stay_still":
        return ""
    if clean in {"bow", "high_five", "mouth", "nod", "shake_head"}:
        return clean
    return ""


def _event_names_from_plan(plan: CoordinationPlan) -> set[str]:
    names: set[str] = set()
    for event in reversed(plan.events):
        for key in ("event", "intent", "state"):
            value = event.get(key)
            if value:
                names.add(str(value))
        payload = event.get("payload")
        if isinstance(payload, dict):
            for key in ("event", "intent", "state"):
                value = payload.get(key)
                if value:
                    names.add(str(value))
    return names
