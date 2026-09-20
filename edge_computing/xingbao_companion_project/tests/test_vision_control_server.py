import json
import socket

import pytest

from core.vision_control_server import VisionControlServer, VisionRuntimeController


class FakeBridge:
    def __init__(self, config):
        self.config = config
        self.closed = False

    def start(self):
        return {"ok": True, "pid": self.config["pid"]}

    def close(self):
        self.closed = True

    def status(self):
        return {"running": not self.closed, "pid": self.config["pid"] if not self.closed else None}


def test_controller_stop_and_restart_own_exactly_one_fresh_bridge():
    configs = iter([{"pid": 101}, {"pid": 202}])
    bridges = []

    def make_bridge(config):
        bridge = FakeBridge(config)
        bridges.append(bridge)
        return bridge

    controller = VisionRuntimeController(lambda: next(configs), make_bridge)

    assert controller.handle("start") == {"ok": True, "action": "start", "running": True, "pid": 101}
    assert controller.handle("stop") == {"ok": True, "action": "stop", "running": False, "pid": None}
    assert bridges[0].closed is True
    assert controller.handle("restart") == {"ok": True, "action": "restart", "running": True, "pid": 202}
    assert len(bridges) == 2


def test_controller_reports_a_bridge_start_failure_without_retaining_it():
    class FailingBridge:
        def start(self):
            return {"ok": False, "error": "camera_unavailable"}

        def close(self):
            raise AssertionError("a failed bridge must not be retained")

        def status(self):
            return {"running": False, "pid": None}

    controller = VisionRuntimeController(lambda: {}, lambda _config: FailingBridge())

    assert controller.handle("start") == {
        "ok": False,
        "action": "start",
        "running": False,
        "pid": None,
        "error": "camera_unavailable",
    }


def _request(address, payload):
    with socket.create_connection(address, timeout=2.0) as sock:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        return json.loads(sock.makefile("rb").readline().decode("utf-8"))


def test_loopback_server_allows_only_fixed_control_actions():
    controller = VisionRuntimeController(lambda: {"pid": 303}, FakeBridge)
    server = VisionControlServer(controller, host="127.0.0.1", port=0).start()
    try:
        assert _request(server.address, {"type": "vision_runtime_control", "action": "status"}) == {
            "ok": True, "action": "status", "running": False, "pid": None,
        }
        assert _request(server.address, {"type": "vision_runtime_control", "action": "shell"}) == {
            "ok": False, "error": "unsupported_action",
        }
        assert _request(server.address, {"type": "speech_request", "action": "status"}) == {
            "ok": False, "error": "unsupported_message_type",
        }
    finally:
        server.close()


def test_server_refuses_non_loopback_host():
    controller = VisionRuntimeController(lambda: {"pid": 404}, FakeBridge)

    with pytest.raises(ValueError, match="loopback"):
        VisionControlServer(controller, host="0.0.0.0", port=8768)
