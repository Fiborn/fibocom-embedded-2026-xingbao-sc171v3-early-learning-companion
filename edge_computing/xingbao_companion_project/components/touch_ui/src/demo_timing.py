"""Central timing presets for automated demonstrations."""

DEFAULT_DEMO_SPEED = "slow"

DEMO_SPEED_PRESETS = {
    "normal": {
        "page_intro": 1.2, "pointer_move": 0.8, "pointer_press": 0.5,
        "after_click": 1.2, "feedback_hold": 1.6, "summary_hold": 2.0,
        "memory_flash": 1.0, "memory_gap": 0.55,
        "memory_before_input": 0.5, "between_steps": 0.8,
    },
    "slow": {
        "page_intro": 1.3, "pointer_move": 1.0, "pointer_press": 0.6,
        "after_click": 1.25, "feedback_hold": 1.8, "summary_hold": 2.4,
        "memory_flash": 1.25, "memory_gap": 0.75,
        "memory_before_input": 0.8, "between_steps": 0.85,
    },
}


def normalize_demo_speed(name):
    value = str(name or DEFAULT_DEMO_SPEED).lower()
    return value if value in DEMO_SPEED_PRESETS else DEFAULT_DEMO_SPEED


def get_demo_timing(name=DEFAULT_DEMO_SPEED):
    return dict(DEMO_SPEED_PRESETS[normalize_demo_speed(name)])
