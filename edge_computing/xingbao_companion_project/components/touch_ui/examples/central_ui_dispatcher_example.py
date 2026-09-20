"""Real central-to-UI dispatcher and UTF-8 NDJSON server on 127.0.0.1:8765."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socketserver
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.board_adapter import (
    apply_hardware_feedback,
    open_game,
    return_to_desktop,
    set_xingbao_expression,
)

try:
    from src.board_adapter import handle_game_command
except ImportError:
    handle_game_command = None


def dispatch_assistant_output(message):
    payload = dict(message.get("payload") or message.get("assistant_output") or message)
    expression = dict(payload.get("screen_expression") or {})
    results = []
    if expression:
        context = {
            "duration_ms": expression.get("duration_ms", 4000),
            "subtitle_priority": payload.get("subtitle_priority", "external"),
        }
        results.append(set_xingbao_expression(expression.get("name", "neutral"),
                                              payload.get("screen_text", ""),
                                              source="central", context=context))
    command = dict(payload.get("ui_command") or {})
    name, params = command.get("name"), dict(command.get("params") or {})
    if name == "open_game_center":
        results.append(open_game(source="central", context=params))
    elif name == "start_game":
        results.append(open_game(params.get("game_id"), source="central", context=params))
    elif name == "return_to_desktop":
        results.append(return_to_desktop(source="central", context=params))
    elif name:
        results.append({"ok": False, "action": name, "error": "unknown_ui_command"})
    game_command = payload.get("game_command")
    if isinstance(game_command, dict):
        if handle_game_command is not None:
            results.append(handle_game_command(game_command))
        else:
            results.append({
                "type": "game_response",
                "ok": False,
                "error": {"code": "game_command_not_supported"},
                "message": "当前界面版本暂不支持游戏状态查询。",
            })
    raw_arm = payload.get("arm_action")
    if isinstance(raw_arm, dict):
        arm = raw_arm.get("name", "stay_still")
    elif isinstance(raw_arm, str):
        arm = raw_arm
    else:
        arm = "stay_still"
    raw_led = payload.get("led")
    led = dict(raw_led or {}).get("mode", "off") if isinstance(raw_led, dict) else "off"
    hardware = apply_hardware_feedback(arm, led)
    ok = all(item.get("ok", False) for item in results) if results else True
    return {"type": "command_result", "request_id": message.get("request_id"),
            "ok": ok, "results": results, "hardware_feedback": hardware}


class NDJSONHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            try:
                message = json.loads(raw.decode("utf-8"))
                response = dispatch_assistant_output(message)
            except Exception as exc:
                response = {"type": "command_result", "ok": False,
                            "error": type(exc).__name__, "message": str(exc)}
            self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class ThreadedNDJSONServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host="127.0.0.1", port=8765):
    with ThreadedNDJSONServer((host, port), NDJSONHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)
