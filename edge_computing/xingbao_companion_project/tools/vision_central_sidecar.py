"""Run the camera vision process and forward safe events to Xingbao central."""

from __future__ import annotations

import argparse
import json
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict

from multimodal.vision_runtime import VisionProcessBridge, VisionRuntimeConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward high-level vision events to the running central service."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--restart-delay", type=float, default=2.0)
    parser.add_argument(
        "--status-file",
        default="/tmp/xingbao_vision_sidecar_status.json",
    )
    return parser.parse_args()


class CentralVisionForwarder:
    """Forward one validated high-level event over the central NDJSON socket."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_timeout: float,
        status_file: Path,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.connect_timeout = max(0.2, float(connect_timeout))
        self.status_file = status_file
        self._lock = threading.Lock()
        self._forwarded = 0
        self._failures = 0

    def __call__(self, event: Dict[str, Any]) -> None:
        encoded = (
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        response: Dict[str, Any] = {}
        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.connect_timeout,
            ) as connection:
                connection.settimeout(self.connect_timeout)
                connection.sendall(encoded)
                response_line = _receive_line(connection)
            if response_line:
                decoded = json.loads(response_line)
                if isinstance(decoded, dict):
                    response = decoded
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            with self._lock:
                self._failures += 1
                self._write_status(
                    event=event,
                    ok=False,
                    error=f"{type(exc).__name__}:{exc}",
                )
            print(
                "[vision-sidecar] forward_failed {}:{}".format(
                    type(exc).__name__,
                    exc,
                ),
                flush=True,
            )
            return

        with self._lock:
            self._forwarded += 1
            ok = str(response.get("status") or "") not in {"failed", "rejected"}
            self._write_status(event=event, ok=ok, response=response)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        print(
            "[vision-sidecar] forwarded state={} emotion={} central_status={}".format(
                payload.get("state", ""),
                payload.get("emotion", ""),
                response.get("status", ""),
            ),
            flush=True,
        )

    def _write_status(
        self,
        *,
        event: Dict[str, Any],
        ok: bool,
        response: Dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        status = {
            "ok": bool(ok),
            "updated_unix": time.time(),
            "forwarded": self._forwarded,
            "failures": self._failures,
            "last_event": event,
            "last_response": response or {},
            "error": error,
        }
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_suffix(self.status_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.status_file)


def _receive_line(connection: socket.socket, limit: int = 65536) -> str:
    chunks = bytearray()
    while len(chunks) < limit:
        chunk = connection.recv(min(4096, limit - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
        if b"\n" in chunk:
            break
    return bytes(chunks).split(b"\n", 1)[0].decode("utf-8", "replace").strip()


def main() -> int:
    args = parse_args()
    stopping = threading.Event()

    def stop(_signum: int, _frame: Any) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    forwarder = CentralVisionForwarder(
        args.host,
        args.port,
        connect_timeout=args.connect_timeout,
        status_file=Path(args.status_file),
    )
    while not stopping.is_set():
        bridge = VisionProcessBridge(
            forwarder,
            config=VisionRuntimeConfig.from_environment(),
            log_handler=lambda line: print(f"[vision-runtime] {line}", flush=True),
        )
        started = bridge.start()
        print(
            "[vision-sidecar] startup {}".format(
                json.dumps(started, ensure_ascii=False, sort_keys=True)
            ),
            flush=True,
        )
        if not started.get("ok"):
            return 2
        while not stopping.wait(0.5):
            if not bridge.status().get("running"):
                break
        bridge.close()
        if not stopping.is_set():
            print("[vision-sidecar] runtime_exited restarting=true", flush=True)
            stopping.wait(max(0.2, float(args.restart_delay)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
