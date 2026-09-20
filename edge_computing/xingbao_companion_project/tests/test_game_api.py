from src.game_api import GameCommandAdapter, sanitize_feedback


def test_game_command_adapter_returns_hint_response_without_real_game() -> None:
    response = GameCommandAdapter(app=object()).handle_command(
        {
            "type": "game_command",
            "game_id": "shape_game",
            "intent": "get_hint",
            "user_text": "\u6211\u4e0d\u4f1a",
            "context": {"source": "voice", "child_age_group": "preschool"},
        }
    )

    assert response["type"] == "game_response"
    assert response["ok"] is True
    assert response["game_id"] == "shape_game"
    assert response["intent"] == "get_hint"
    assert response["message"]
    assert response["feedback"]["screen_expression"] == "thinking"
    assert response["feedback"]["led_mode"] == "blue_breath"


def test_game_command_adapter_delegates_to_real_game_handler() -> None:
    class GameApp:
        def handle_game_command(self, command):
            assert command["intent"] == "get_goal"
            return {
                "type": "game_response",
                "ok": True,
                "message": "\u8bf7\u627e\u5230\u5706\u5f62\u3002",
                "state": {"round": 2},
                "feedback": {"screen_expression": "smile", "led_mode": "warm_breath"},
            }

    response = GameCommandAdapter(GameApp()).handle_command(
        {
            "type": "game_command",
            "game_id": "shape_game",
            "intent": "get_goal",
            "user_text": "\u8981\u505a\u4ec0\u4e48",
        }
    )

    assert response["game_id"] == "shape_game"
    assert response["intent"] == "get_goal"
    assert response["message"] == "\u8bf7\u627e\u5230\u5706\u5f62\u3002"
    assert response["state"] == {"round": 2}


def test_game_command_adapter_rejects_unknown_intent() -> None:
    response = GameCommandAdapter(app=object()).handle_command(
        {
            "type": "game_command",
            "game_id": "shape_game",
            "intent": "free_chat",
            "user_text": "\u968f\u4fbf\u804a\u804a",
        }
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "unknown_intent"


def test_game_feedback_sanitizer_keeps_only_high_level_whitelist() -> None:
    feedback = sanitize_feedback(
        {
            "screen_expression": "smile",
            "led_mode": "warm_breath",
            "arm_action": "servo:180",
            "gpio": "on",
            "pwm": "255",
        }
    )

    assert feedback == {
        "screen_expression": "smile",
        "led_mode": "warm_breath",
    }
