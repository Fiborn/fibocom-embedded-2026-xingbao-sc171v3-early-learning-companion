"""Loopback-only lifecycle control for the center-owned vision runtime."""

from __future__ import annotations

import json
import socketserver
import threading
from typing import Any, Callable


VisionConfigFactory = Callable[[], Any]
VisionBridgeFactory = Callable[[Any], Any]


class VisionRuntimeController:
    """Serialize lifecycle operations for exactly one VisionProcessBridge."""

    _ACTIONS = {"status", "start", "stop", "restart"}

    def __init__(
        self,
        config_factory: VisionConfigFactory,
        bridge_factory: VisionBridgeFactory,
    ) -> None:
        self._config_factory = config_factory
        self._bridge_factory = bridge_factory
        self._bridge: Any | None = None
        self._lock = threading.RLock()

    def handle(self, action: str) -> dict[str, Any]:
        requested = str(action or "").strip().lower()
        if requested not in self._ACTIONS:
            return {"ok": False, "error": "unsupported_action"}
        with self._lock:
            error = ""
            if requested == "start":
                error = self._start_if_stopped()
            elif requested == "stop":
                self._stop_current()
            elif requested == "restart":
                self._stop_current()
                error = self._start_if_stopped()
            status = self._status()
            response = {
                "ok": not bool(error),
                "action": requested,
                "running": status["running"],
                "pid": status["pid"],
            }
            if error:
                response["error"] = error
            return response

    def close(self) -> None:
        with self._lock:
            self._stop_current()

    def _start_if_stopped(self) -> str:
        if self._bridge is not None and bool(self._status()["running"]):
            return ""
        self._stop_current()
        config = self._config_factory()
        bridge = self._bridge_factory(config)
        try:
            result = bridge.start()
        except Exception as exc:  # Keep the loopback manager responsive.
            return "{}:{}".format(type(exc).__name__, exc)
        if not bool(result.get("ok")):
            return str(result.get("error") or "vision_start_failed")
        self._bridge = bridge
        return ""

    def _stop_current(self) -> None:
        bridge = self._bridge
        self._bridge = None
        if bridge is not None:
            bridge.close()

    def _status(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"running": False, "pid": None}
        status = self._bridge.status()
        return {
            "running": bool(status.get("running")),
            "pid": status.get("pid") if status.get("running") else None,
        }


class VisionControlServer:
    """Small NDJSON server limited to localhost vision lifecycle actions."""

    _MAX_LINE_BYTES = 4096

    def __init__(
        self,
        controller: VisionRuntimeController,
        *,
        host: str = "127.0.0.1",
        port: int = 8768,
    ) -> None:
        if str(host) != "127.0.0.1":
            raise ValueError("vision control server must bind to loopback")
        self._controller = controller

        class Handler(socketserver.StreamRequestHandler):
            def handle(handler_self) -> None:
                raw = handler_self.rfile.readline(VisionControlServer._MAX_LINE_BYTES + 1)
                if len(raw) > VisionControlServer._MAX_LINE_BYTES:
                    response = {"ok": False, "error": "request_too_large"}
                else:
                    try:
                        message = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        response = {"ok": False, "error": "invalid_json"}
                    else:
                        if not isinstance(message, dict):
                            response = {"ok": False, "error": "invalid_message"}
                        elif message.get("type") != "vision_runtime_control":
                            response = {"ok": False, "error": "unsupported_message_type"}
                        else:
                            response = controller.handle(str(message.get("action") or ""))
                handler_self.wfile.write(
                    (json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                )

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server((host, int(port)), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="xingbao-vision-control",
            daemon=True,
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> "VisionControlServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
