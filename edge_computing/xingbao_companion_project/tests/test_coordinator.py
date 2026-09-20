from core.coordinator import XingbaoCoordinator
from core.intent_router import IntentRouter
from core.tool_registry import ToolRegistry


def test_coordinator_plans_game_event_as_expression_output() -> None:
    plan = XingbaoCoordinator().plan_event(
        {
            "type": "game_event",
            "source": "mini_game",
            "payload": {"event": "child_made_mistake"},
        }
    )

    assert plan.intent.intent == "game_event"
    assert plan.intent.source_text == "child_made_mistake"
    assert plan.expression_output.intent == "encourage_retry"
    assert plan.expression_output.state == "playing_game"
    assert plan.expression_output.tts is True


def test_intent_router_detects_game_request_as_reserved_hub() -> None:
    result = IntentRouter().route("\u661f\u5b9d\uff0c\u6211\u8981\u73a9\u6e38\u620f\u5566")

    assert result.intent == "open_tool"
    assert result.target == "mini_game_hub"
    assert result.confidence > 0.8


def test_intent_router_does_not_open_game_for_plain_game_topic_chat() -> None:
    result = IntentRouter().route("我今天最开心的事情就是玩游戏")

    assert result.intent == "chat"
    assert result.target == ""


def test_intent_router_does_not_open_game_for_color_knowledge_question() -> None:
    result = IntentRouter().route("我想知道彩虹为什么有颜色")

    assert result.intent == "chat"
    assert result.target == ""


def test_intent_router_routes_color_story_to_story_instead_of_game() -> None:
    result = IntentRouter().route("我想听颜色的故事")

    assert result.intent == "open_tool"
    assert result.target == "story_time"


def test_intent_router_keeps_song_request_in_chat() -> None:
    result = IntentRouter().route("我想听你唱歌")

    assert result.intent == "chat"


def test_intent_router_does_not_exit_on_negated_end_word() -> None:
    result = IntentRouter().route("故事不要结束")

    assert result.intent == "chat"


def test_tool_registry_exposes_touch_mini_game_entry() -> None:
    request = ToolRegistry().build_launch_request("mini_game_hub")

    assert request.status == "ready"
    assert request.available is True
    assert request.launch_mode == "board_ui"


def test_intent_router_detects_migrated_visual_tool_home() -> None:
    result = IntentRouter().route("星宝打开白宝箱")

    assert result.intent == "open_tool"
    assert result.target == "kids_visual_tools"
    assert result.confidence > 0.8


def test_intent_router_leaves_drawing_board_to_llm_tool_call() -> None:
    result = IntentRouter().route("星宝我要画画")

    assert result.intent == "chat"
    assert result.target == ""


def test_tool_registry_exposes_migrated_visual_tool_entry() -> None:
    request = ToolRegistry().build_launch_request("kids_visual_tools:draw")

    assert request.status == "ready"
    assert request.available is True
    assert request.launch_mode == "board_ui"
    assert request.display_name == "白宝箱：儿童画板"


def test_coordinator_plans_reserved_game_expression_and_tool_request() -> None:
    plan = XingbaoCoordinator().plan_text("\u661f\u5b9d\u6211\u8981\u73a9\u6e38\u620f\u5566")

    assert plan.intent.intent == "open_tool"
    assert plan.tool_request is not None
    assert plan.tool_request.target == "mini_game_hub"
    assert plan.expression_output.intent == "open_tool"
    assert plan.expression_output.expression == "happy"
    assert plan.expression_output.tts is True
    assert "选择一个游戏" in plan.expression_output.speak_text


def test_coordinator_does_not_locally_plan_drawing_board_request() -> None:
    plan = XingbaoCoordinator().plan_text("星宝打开画板")

    assert plan.intent.intent == "chat"
    assert plan.tool_request is None


def test_coordinator_normalizes_mini_game_state_input() -> None:
    plan = XingbaoCoordinator().plan_event(
        {
            "type": "mini_game_state",
            "source": "new_game",
            "payload": {"game_id": "shape_match", "state": "child_made_mistake"},
        }
    )

    assert plan.intent.intent == "mini_game_state"
    assert plan.intent.source_text == "child_made_mistake"
    assert plan.intent.reason == "state_input:game_event"
    assert plan.expression_output.intent == "encourage_retry"
    assert [event["type"] for event in plan.events] == ["mini_game_state", "game_event"]


def test_coordinator_normalizes_vision_state_input() -> None:
    plan = XingbaoCoordinator().plan_event(
        {
            "type": "vision_state",
            "source": "vision",
            "payload": {"state": "face_too_close", "confidence": 0.93},
        }
    )

    assert plan.intent.intent == "vision_state"
    assert plan.intent.source_text == "face_too_close"
    assert plan.expression_output.intent == "eye_distance"
    assert [event["type"] for event in plan.events] == ["vision_state", "vision_event"]
