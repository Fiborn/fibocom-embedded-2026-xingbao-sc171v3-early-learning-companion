import json
import socketserver
import threading

from soarm101_module.arm_command_server_10000 import POINT_ACTIONS, forward_point


def test_six_point_adapter_exposes_only_the_reviewed_grid() -> None:
    assert POINT_ACTIONS == {
        "11": "vision_high_five_11",
        "12": "vision_high_five_12",
        "13": "vision_high_five_13",
        "21": "vision_high_five_21",
        "22": "vision_high_five_22",
        "23": "vision_high_five_23",
    }


def test_six_point_adapter_rejects_non_grid_input_without_network() -> None:
    assert forward_point("servo_angle_120", arm_host="127.0.0.1", arm_port=8764, timeout=0.1) == {
        "ok": False,
        "error": "invalid_command",
        "command": "servo_angle_120",
    }


def test_six_point_adapter_forwards_only_the_mapped_high_level_action() -> None:
    received: list[dict[str, str]] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            received.append(json.loads(self.rfile.readline()))
            self.wfile.write(
                b'{"ok":true,"hardware_feedback":{"ok":true,"queue_status":"follow_session_started"}}\n'
            )

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        response = forward_point("22", arm_host=host, arm_port=port, timeout=0.5)
        thread.join(timeout=1.0)

    assert received == [{"arm_action": "vision_high_five_22"}]
    assert response["vision_point_command"] == "22"
    assert response["forwarded_arm_action"] == "vision_high_five_22"
    assert response["via"] == "vision_point_port_10000"
