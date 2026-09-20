from core.action_bus import ActionBus
from core.action_safety import ActionSanitizer, SafeAction


def test_action_sanitizer_allows_whitelisted_action() -> None:
    action = ActionSanitizer().sanitize(
        {
            "screen_expression": "smile",
            "led_mode": "warm_breath",
            "arm_action": "wave_hand",
        }
    )

    assert action == SafeAction(
        screen_expression="smile",
        led_mode="off",
        arm_action="wave_hand",
    )


def test_safe_action_dict_keeps_screen_and_led_feedback() -> None:
    action = ActionSanitizer().sanitize(
        {
            "screen_expression": "smile",
            "led_mode": "warm_breath",
        }
    )

    assert action.as_dict() == {
        "screen_expression": "smile",
        "led_mode": "warm_breath",
    }


def test_action_sanitizer_rejects_unknown_and_raw_hardware_values() -> None:
    action = ActionSanitizer().sanitize(
        {
            "screen_expression": "servo_face_90",
            "led_mode": "uart:rainbow",
            "arm_action": "servo angle 120",
        }
    )

    assert action == SafeAction()


def test_action_sanitizer_rejects_chinese_raw_hardware_values() -> None:
    action = ActionSanitizer().sanitize("舵机角度120度")

    assert action == SafeAction()


def test_action_bus_records_sanitized_actions() -> None:
    bus = ActionBus()

    action = bus.emit("nod")

    assert action.arm_action == "nod"
    assert bus.last_action() == action


def test_action_sanitizer_allows_named_arm_actions() -> None:
    action = ActionSanitizer().sanitize("nod")

    assert action == SafeAction(arm_action="nod")
