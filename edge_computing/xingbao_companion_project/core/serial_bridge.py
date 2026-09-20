"""Serial bridge that sends only sanitized high-level actions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.action_bus import ActionBus
from core.action_safety import SafeAction


DEFAULT_BAUDRATE = 115200


def import_serial() -> Any:
    try:
        import serial

        return serial
    except Exception as exc:  # pragma: no cover - depends on optional pyserial
        raise RuntimeError("Missing dependency: pyserial") from exc


@dataclass
class SerialBridge:
    """Sends sanitized high-level actions to a board over serial."""

    port: str
    baudrate: int = DEFAULT_BAUDRATE
    timeout: float = 1.0
    action_bus: ActionBus = field(default_factory=ActionBus)
    serial_connection: Any | None = None

    def connect(self) -> None:
        if self.serial_connection is not None:
            return
        serial_module = import_serial()
        self.serial_connection = serial_module.Serial(
            self.port,
            self.baudrate,
            timeout=self.timeout,
        )

    def close(self) -> None:
        if self.serial_connection is not None:
            self.serial_connection.close()
            self.serial_connection = None

    def send_action(self, proposal: SafeAction | dict[str, Any] | str | None) -> SafeAction:
        """Sanitize an action proposal and send it as one JSON line."""
        action = self.action_bus.emit(proposal)
        self.connect()
        assert self.serial_connection is not None
        self.serial_connection.write(encode_action(action))
        return action

    def __enter__(self) -> "SerialBridge":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def encode_action(action: SafeAction) -> bytes:
    """Encode a safe high-level action for the board firmware."""
    payload = {
        "type": "action",
        "action": action.as_dict(),
    }
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
