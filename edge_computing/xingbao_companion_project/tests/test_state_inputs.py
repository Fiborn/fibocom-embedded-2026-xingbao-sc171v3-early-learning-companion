from core.state_inputs import normalize_state_input


def test_mini_game_state_maps_known_state_to_game_event() -> None:
    event = normalize_state_input(
        {
            "type": "mini_game_state",
            "source": "new_game",
            "payload": {
                "game_id": "shape_match",
                "state": "child_made_mistake",
                "confidence": 0.91,
                "progress": {"round": 2},
            },
        }
    )

    assert event["type"] == "game_event"
    assert event["source"] == "new_game"
    assert event["payload"]["event"] == "child_made_mistake"
    assert event["payload"]["game_id"] == "shape_match"
    assert event["payload"]["state"] == "child_made_mistake"
    assert event["payload"]["progress"] == {"round": 2}


def test_mini_game_state_can_send_explicit_feedback_message() -> None:
    event = normalize_state_input(
        {
            "type": "mini_game_state",
            "payload": {
                "game_id": "shape_match",
                "state": "child_succeeded",
                "message": "\u505a\u5f97\u597d\uff0c\u6211\u4eec\u7ee7\u7eed\u4e0b\u4e00\u5173\u3002",
                "feedback": {"expression": "happy", "tts": True},
            },
        }
    )

    assert event["type"] == "xingbao_expression_request"
    assert event["source"] == "mini_game"
    assert event["payload"]["intent"] == "celebrate_success"
    assert event["payload"]["emotion"] == "happy"
    assert event["payload"]["tts"] is True


def test_vision_state_maps_health_signal_to_vision_event() -> None:
    event = normalize_state_input(
        {
            "type": "vision_state",
            "payload": {
                "state": "face_too_close",
                "confidence": 0.88,
                "duration_seconds": 3,
                "simulated": True,
            },
        }
    )

    assert event["type"] == "vision_event"
    assert event["source"] == "vision"
    assert event["payload"]["event"] == "face_too_close"
    assert event["payload"]["state"] == "face_too_close"
    assert event["payload"]["confidence"] == 0.88
    assert event["payload"]["simulated"] is True


def test_vision_state_can_update_ui_without_tts() -> None:
    event = normalize_state_input(
        {
            "type": "vision_state",
            "payload": {"state": "child_left_seat", "confidence": 0.75},
        }
    )

    assert event["type"] == "xingbao_expression_request"
    assert event["payload"]["intent"] == "wait_for_child"
    assert event["payload"]["tts"] is False


def test_game_response_maps_message_to_expression_request() -> None:
    event = normalize_state_input(
        {
            "type": "game_response",
            "ok": True,
            "game_id": "shape_game",
            "intent": "get_hint",
            "message": "\u5148\u627e\u6700\u50cf\u5706\u5f62\u7684\u90a3\u4e2a\u3002",
            "state": {"round": 1},
            "feedback": {
                "screen_expression": "thinking",
                "led_mode": "blue_breath",
                "arm_action": "stay_still",
                "gpio": "on",
            },
        }
    )

    assert event["type"] == "xingbao_expression_request"
    assert event["source"] == "game"
    assert event["payload"]["intent"] == "get_hint"
    assert event["payload"]["text"] == "\u5148\u627e\u6700\u50cf\u5706\u5f62\u7684\u90a3\u4e2a\u3002"
    assert event["payload"]["emotion"] == "thinking"
    assert event["payload"]["feedback"] == {
        "screen_expression": "thinking",
        "led_mode": "blue_breath",
        "action": "stay_still",
        "arm_action": "stay_still",
    }


def test_non_state_event_is_unchanged() -> None:
    raw = {"type": "game_event", "payload": {"event": "game_started"}}

    assert normalize_state_input(raw) is raw
