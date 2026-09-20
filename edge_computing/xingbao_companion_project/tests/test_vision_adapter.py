from core.board_ui_client import arm_action_from_plan
from core.coordinator import XingbaoCoordinator
from core.expression import ExpressionDispatcher
from core.state_inputs import normalize_state_input
from multimodal.vision_adapter import (
    VisionEventAdapter,
    vision_json_to_flags,
    vision_json_to_state_events,
)
from multimodal.vision_system.app import (
    DEFAULT_EMOTION_MODEL_PATH,
    DEFAULT_MODEL_PATH,
    build_parser,
)


def _emotion_payload(code: int, confidence: float = 0.8) -> dict:
    return {
        "return_code": 0,
        "drink_return_code": 0,
        "emotion_return_code": code,
        "emotions": [
            {
                "face_index": 0,
                "label": "sadness",
                "confidence": confidence,
                "return_code": code,
                "confirmed": code != 0,
            }
        ],
    }


def test_legacy_flags_keep_original_meaning() -> None:
    assert vision_json_to_flags({"return_code": 1, "drink_return_code": 0}) == (1, 0)
    assert vision_json_to_flags({"return_code": 2, "drink_return_code": 1}) == (0, 1)
    assert vision_json_to_flags({"return_code": "1", "drink_return_code": True}) == (0, 0)


def test_raw_result_preserves_independent_health_and_emotion_signals() -> None:
    payload = _emotion_payload(2, confidence=0.83)
    payload.update(
        {
            "return_code": 1,
            "drink_return_code": 1,
            "return_status": {
                "smoothed_distance_m": 0.31,
                "close_seconds": 2.5,
            },
        }
    )

    events = vision_json_to_state_events(payload)

    assert [event["payload"]["state"] for event in events] == [
        "face_too_close",
        "drink_water_reminder_due",
        "child_emotion_detected",
    ]
    assert events[0]["payload"]["distance_m"] == 0.31
    assert events[2]["payload"]["emotion"] == "sadness"
    assert events[2]["payload"]["confidence"] == 0.83


def test_uncertain_emotion_does_not_emit_an_emotion_event() -> None:
    assert vision_json_to_state_events(_emotion_payload(0)) == []


def test_adapter_debounces_health_and_requires_stable_emotion() -> None:
    adapter = VisionEventAdapter(emotion_stable_frames=3)
    payload = _emotion_payload(2)
    payload["return_code"] = 1

    first = adapter.update(payload)
    second = adapter.update(payload)
    third = adapter.update(payload)

    assert [event["payload"]["state"] for event in first] == ["face_too_close"]
    assert second == []
    assert [event["payload"]["state"] for event in third] == [
        "child_emotion_detected"
    ]
    assert adapter.update(payload) == []


def test_adapter_emits_one_hydration_reset_when_bottle_overlaps_face() -> None:
    """Catch a pending drink prompt surviving a new detected drink."""
    adapter = VisionEventAdapter()

    assert adapter.update({"drink_reminder": {"overlap_now": False}}) == []
    reset_events = adapter.update({"drink_reminder": {"overlap_now": True}})
    assert [event["payload"]["state"] for event in reset_events] == [
        "drink_reminder_reset"
    ]
    assert adapter.update({"drink_reminder": {"overlap_now": True}}) == []


def test_happy_emotion_normalizes_to_supportive_high_level_expression() -> None:
    raw_event = vision_json_to_state_events(_emotion_payload(1))[0]

    normalized = normalize_state_input(raw_event)

    assert normalized["type"] == "xingbao_expression_request"
    assert normalized["source"] == "vision"
    assert normalized["payload"]["intent"] == "observe_child_emotion"
    assert normalized["payload"]["emotion"] == "happy"
    assert normalized["payload"]["tts"] is True
    assert normalized["payload"]["detected_emotion"] == "happiness"

    output = ExpressionDispatcher().handle(normalized)
    assert output.handled is True
    assert output.intent == "observe_child_emotion"
    assert output.expression == "happy"
    assert output.tts is True


def test_sad_emotion_routes_to_supportive_voice_and_current_safe_arm_action() -> None:
    raw_event = vision_json_to_state_events(_emotion_payload(2))[0]

    plan = XingbaoCoordinator().plan_event(raw_event)

    assert "\u5982\u679c" in plan.expression_output.speak_text
    assert plan.expression_output.tts is True
    assert plan.expression_output.expression == "caring"
    assert arm_action_from_plan(plan) == "shake_head"


def test_same_emotion_respects_repeat_cooldown_after_uncertain_frame() -> None:
    now = [100.0]
    adapter = VisionEventAdapter(
        emotion_stable_frames=1,
        emotion_min_interval_seconds=5.0,
        emotion_repeat_cooldown_seconds=90.0,
        clock=lambda: now[0],
    )
    payload = _emotion_payload(2)

    assert len(adapter.update(payload)) == 1
    assert adapter.update(_emotion_payload(0)) == []
    now[0] += 10.0
    assert adapter.update(payload) == []
    now[0] += 81.0
    assert len(adapter.update(payload)) == 1


def test_vision_cli_uses_project_models_and_supports_xingbao_events() -> None:
    args = build_parser().parse_args(["--headless", "--xingbao-events"])

    assert args.model == str(DEFAULT_MODEL_PATH)
    assert args.emotion_model == str(DEFAULT_EMOTION_MODEL_PATH)
    assert args.headless is True
    assert args.xingbao_events is True
