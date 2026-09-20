import json

from core.serial_bridge import SerialBridge, encode_action


class FakeSerialConnection:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.closed = True


def test_encode_action_outputs_json_line() -> None:
    bridge = SerialBridge("COM1", serial_connection=FakeSerialConnection())
    action = bridge.action_bus.emit("wave_hand")

    encoded = encode_action(action)
    payload = json.loads(encoded.decode("utf-8"))

    assert encoded.endswith(b"\n")
    assert payload == {
        "type": "action",
        "action": {
            "arm_action": "wave_hand",
        },
    }


def test_serial_bridge_sends_sanitized_action() -> None:
    fake_serial = FakeSerialConnection()
    bridge = SerialBridge("COM1", serial_connection=fake_serial)

    action = bridge.send_action("servo angle 120")

    assert action.arm_action == "stay_still"
    payload = json.loads(fake_serial.writes[0].decode("utf-8"))
    assert payload["action"] == {}
