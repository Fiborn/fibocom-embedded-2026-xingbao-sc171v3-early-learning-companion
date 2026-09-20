from components.arm_soarm101.arm_action_library import compile_registry, load_registry
from components.touch_ui.src.growth_support import FirstMistakeSupport


def test_six_point_high_five_has_a_twelve_second_watchdog() -> None:
    compiled = compile_registry(load_registry())

    for point in ("11", "12", "13", "21", "22", "23"):
        action_name = f"vision_high_five_{point}"
        assert compiled["action_max_durations"][action_name] == 12.0
        outbound, returning = compiled["action_segments"][action_name][1:]
        assert outbound == {"steps": 64, "delay_seconds": 0.03, "smoothstep": True, "hold_after_seconds": 3.5}
        assert returning == {"steps": 64, "delay_seconds": 0.03, "smoothstep": True, "hold_after_seconds": 0.0}
    assert compiled["action_max_durations"]["high_five"] != 12.0


def test_first_failure_waits_for_visual_high_five_not_generic_fallback() -> None:
    support = FirstMistakeSupport()
    sequence = support.observe_answer(
        game_id="shape",
        correct=False,
        question_id="shape-q1",
        target_id="triangle",
        target_label="三角形",
    )

    assert sequence is not None
    assert sequence.high_five_hold_seconds == 24.5
    assert support.start_high_five() is True
    assert support.public_state()["action"] == "high_five"
