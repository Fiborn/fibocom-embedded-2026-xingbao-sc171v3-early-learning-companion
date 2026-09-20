"""Whitelist for high-level expression, arm action, and LED feedback names."""

SCREEN_EXPRESSIONS = {
    "neutral",
    "smile",
    "thinking",
    "curious",
    "sad",
    "surprised",
    "sleepy",
}

ARM_ACTIONS = {
    "stay_still",
    "wave_hand",
    "nod",
    "shake_head",
    "point_left",
    "point_right",
    "small_dance",
    "group_1",
    "group_2",
    "group_3",
}

LED_MODES = {
    "off",
    "blue_breath",
    "warm_breath",
    "yellow_blink",
    "rainbow",
    "red_flash",
}

DEFAULT_FEEDBACK = {
    "screen_expression": "neutral",
    "arm_action": "stay_still",
    "led_mode": "off",
}


def sanitize_feedback(feedback):
    feedback = dict(feedback or {})
    return {
        "screen_expression": (
            feedback.get("screen_expression")
            if feedback.get("screen_expression") in SCREEN_EXPRESSIONS
            else DEFAULT_FEEDBACK["screen_expression"]
        ),
        "arm_action": (
            feedback.get("arm_action")
            if feedback.get("arm_action") in ARM_ACTIONS
            else DEFAULT_FEEDBACK["arm_action"]
        ),
        "led_mode": (
            feedback.get("led_mode")
            if feedback.get("led_mode") in LED_MODES
            else DEFAULT_FEEDBACK["led_mode"]
        ),
    }
