import json
import socketserver
import threading

from core.arm_action_bridge import (
    ArmActionRateLimiter,
    ArmActionBridge,
    ArmActionRequest,
    arm_action_for_voice_text,
    dispatch_voice_arm_action,
    send_arm_action_ndjson,
    send_hand_recognition_control,
    send_vision_point_command,
)


def test_arm_action_bridge_validates_known_action_without_handler() -> None:
    result = ArmActionBridge().execute("nod")

    assert result["ok"] is True
    assert result["arm_action"] == "nod"
    assert result["implemented"] is False


def test_arm_action_bridge_accepts_reviewed_high_five_action() -> None:
    result = ArmActionBridge().execute("high_five")

    assert result["ok"] is True
    assert result["arm_action"] == "high_five"


def test_arm_action_bridge_rejects_unknown_action() -> None:
    result = ArmActionBridge().execute("servo_angle_120")

    assert result["ok"] is False
    assert result["arm_action"] == "stay_still"
    assert result["error"] == "unsupported_arm_action"


def test_arm_action_bridge_delegates_to_handler() -> None:
    seen: list[ArmActionRequest] = []

    def handler(request: ArmActionRequest) -> dict:
        seen.append(request)
        return {"ok": True, "implemented": True}

    result = ArmActionBridge(handler=handler).execute("shake_head")

    assert result["ok"] is True
    assert result["implemented"] is True
    assert seen[0].arm_action == "shake_head"


def test_voice_game_navigation_does_not_trigger_an_arm_action() -> None:
    assert arm_action_for_voice_text("可以摇摇头吗？") == "shake_head"
    assert arm_action_for_voice_text("和我握握手。") == "high_five"
    assert arm_action_for_voice_text("和我击个掌。") == "high_five"
    assert arm_action_for_voice_text("我想和你叽叽掌。") == "high_five"
    assert arm_action_for_voice_text("不要握手。") == ""
    assert arm_action_for_voice_text("不要和我击个掌。") == ""
    assert arm_action_for_voice_text("不要叽叽掌。") == ""
    assert arm_action_for_voice_text("我不要和你握手。") == ""
    assert arm_action_for_voice_text("星宝，我要玩游戏。") == ""
    assert arm_action_for_voice_text("今天天气怎么样") == ""


def test_voice_arm_dispatch_is_non_blocking_and_reports_demo_duration() -> None:
    enabled = threading.Event()

    result = dispatch_voice_arm_action(
        "high five",
        sender=lambda _action: None,
        hand_recognition_enabler=lambda: enabled.set(),
        rate_limiter=ArmActionRateLimiter(min_interval_seconds=0),
    )

    assert result == {
        "matched": True,
        "queued": True,
        "arm_action": "high_five",
        "port": 10001,
        "hand_recognition_enable": True,
        "vision_point_port": 10000,
        "fallback_port": 8764,
        "expected_duration_seconds": 24,
        "fallback_expected_duration_seconds": 9,
    }
    assert enabled.wait(timeout=1.0)


def test_high_five_voice_command_falls_back_to_reviewed_arm_motion() -> None:
    calls: list[str] = []
    finished = threading.Event()

    result = dispatch_voice_arm_action(
        "high five",
        sender=lambda action: (calls.append(action), finished.set()),
        hand_recognition_enabler=lambda: (_ for _ in ()).throw(OSError("offline")),
        rate_limiter=ArmActionRateLimiter(min_interval_seconds=0),
    )

    assert result["arm_action"] == "high_five"
    assert finished.wait(timeout=1.0)
    assert calls == ["high_five"]


def test_voice_arm_dispatch_rate_limits_repeated_commands() -> None:
    limiter = ArmActionRateLimiter(min_interval_seconds=60)
    first = dispatch_voice_arm_action(
        "high five",
        sender=lambda _action: None,
        hand_recognition_enabler=lambda: None,
        rate_limiter=limiter,
    )
    second = dispatch_voice_arm_action(
        "high five",
        sender=lambda _action: None,
        hand_recognition_enabler=lambda: None,
        rate_limiter=limiter,
    )

    assert first["queued"] is True
    assert second == {
        "matched": True,
        "queued": False,
        "arm_action": "high_five",
        "reason": "rate_limited",
    }


def test_arm_action_ndjson_uses_action_name_only() -> None:
    received: list[bytes] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            received.append(self.rfile.readline())

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        send_arm_action_ndjson("shake_head", host=host, port=port)
        thread.join(timeout=1.0)

    assert json.loads(received[0]) == {"arm_action": "shake_head"}


def test_high_five_ndjson_keeps_only_high_level_action_name() -> None:
    received: list[bytes] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            received.append(self.rfile.readline())

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        send_arm_action_ndjson("high_five", host=host, port=port)
        thread.join(timeout=1.0)

    assert json.loads(received[0]) == {"arm_action": "high_five"}


def test_hand_recognition_status_command_is_read_only_text() -> None:
    received: list[bytes] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            received.append(self.rfile.readline())
            self.wfile.write(
                b'{"ok":true,"command":"status","hand_recognition_enabled":false,"generation":4}\n'
            )

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        result = send_hand_recognition_control("status", host=host, port=port)
        thread.join(timeout=1.0)

    assert received == [b"status\n"]
    assert result["generation"] == 4


def test_vision_point_command_keeps_only_one_reviewed_grid_code() -> None:
    received: list[bytes] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            received.append(self.rfile.readline())
            self.wfile.write(b'{"ok":true}\n')

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        assert send_vision_point_command("22", host=host, port=port) == {"ok": True}
        thread.join(timeout=1.0)

    assert received == [b"22\n"]


def test_vision_point_command_rejects_non_grid_input() -> None:
    try:
        send_vision_point_command("servo_angle_120")
    except ValueError as exc:
        assert str(exc) == "unsupported_vision_point_command:servo_angle_120"
    else:
        raise AssertionError("raw hardware command must be rejected")
