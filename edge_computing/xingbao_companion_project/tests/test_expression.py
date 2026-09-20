from core.expression import ExpressionDispatcher, ExpressionEvent


def test_dialogue_unclear_text_does_not_emit_a_fixed_reply() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "child_unclear_text",
            "source": "dialogue",
            "payload": {"text": "今天那个……他不让我……"},
        }
    )

    assert output.intent == "guide_expression"
    assert output.expression == "listening"
    assert output.tts is False
    assert output.speak_text == ""
    assert output.screen_text == ""
    assert output.priority == 2


def test_legacy_fixed_fallback_events_are_silent() -> None:
    dispatcher = ExpressionDispatcher()

    cases = (
        {"type": "child_expressed_mood", "source": "dialogue"},
        {
            "type": "vision_event",
            "source": "vision",
            "payload": {"event": "camera_blocked"},
        },
        {"type": "module_error", "source": "system", "payload": {}},
    )

    for event in cases:
        output = dispatcher.handle(event)
        assert output.speak_text == ""
        assert output.screen_text == ""
        assert output.tts is False


def test_game_mistake_becomes_encouraging_retry() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "game_event",
            "source": "mini_game",
            "payload": {"event": "child_made_mistake"},
        }
    )

    assert output.intent == "encourage_retry"
    assert output.expression == "encouraging"
    assert output.state == "playing_game"
    assert "换个办法" in output.speak_text


def test_vision_health_event_has_high_priority() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "vision_event",
            "source": "vision",
            "priority": 1,
            "payload": {"event": "face_too_close", "confidence": 0.9},
        }
    )

    assert output.intent == "eye_distance"
    assert output.priority == 3
    assert output.state == "health_reminding"
    assert "往后坐" in output.speak_text


def test_memory_write_request_rejects_sensitive_content() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "memory_write_request",
            "source": "dialogue",
            "payload": {
                "memory_kind": "interest",
                "content": "孩子学校是某某幼儿园",
            },
        }
    )

    assert output.handled is False
    assert output.memory_request is None
    assert output.tts is False


def test_memory_write_request_maps_safe_interest() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "memory_write_request",
            "source": "dialogue",
            "payload": {
                "memory_kind": "interest",
                "content": "三角龙",
            },
        }
    )

    assert output.intent == "acknowledge_memory"
    assert output.memory_request == {"interests": ["三角龙"]}
    assert output.tts is True


def test_expression_request_sanitizes_sensitive_text() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "xingbao_expression_request",
            "source": "mini_game",
            "payload": {
                "intent": "respond",
                "text": "你的家庭地址是什么？",
                "tts": True,
            },
        }
    )

    assert output.tts is False
    assert output.speak_text == ""
    assert output.screen_text == ""


def test_event_mapping_normalizes_payload() -> None:
    event = ExpressionEvent.from_mapping(
        {"type": "touch_event", "source": "touch", "priority": "3", "payload": []}
    )

    assert event.type == "touch_event"
    assert event.source == "touch"
    assert event.priority == 3
    assert event.payload == {}


def test_toolbox_status_events_are_handled_without_speech() -> None:
    dispatcher = ExpressionDispatcher()

    for event_type in ("game_event", "touch_event"):
        for event_name in (
            "toolbox_opened",
            "toolbox_activity_started",
            "toolbox_result_saved",
            "drawing_started",
            "drawing_completed",
        ):
            output = dispatcher.handle(
                {
                    "type": event_type,
                    "source": "touch_ui",
                    "payload": {"event": event_name},
                }
            )

            assert output.handled is True
            assert output.intent == "acknowledge_toolbox_state"
            assert output.speak_text == ""
            assert output.tts is False


def test_unknown_touch_event_keeps_the_safety_fallback() -> None:
    output = ExpressionDispatcher().handle(
        {
            "type": "touch_event",
            "source": "touch_ui",
            "payload": {"event": "unexpected_touch_state"},
        }
    )

    assert output.handled is False
    assert output.intent == "fallback"
    assert output.tts is True
    assert output.reason == "unsupported_payload_event:unexpected_touch_state"
