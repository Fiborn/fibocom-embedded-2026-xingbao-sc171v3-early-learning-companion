from core.game_status_query import resolve_game_status_query
from core.intent_router import IntentRouter


def test_resolves_star_query_to_fixed_game_command() -> None:
    query = resolve_game_status_query("星宝，我现在有几颗星？")

    assert query is not None
    assert query.intent == "get_stars"
    assert query.as_command("星宝，我现在有几颗星？") == {
        "type": "game_command",
        "game_id": "current_game",
        "intent": "get_stars",
        "user_text": "星宝，我现在有几颗星？",
        "context": {"source": "voice"},
    }


def test_intent_router_prioritizes_game_status_over_general_help() -> None:
    result = IntentRouter().route("星宝提示一下")

    assert result.intent == "game_status_query"
    assert result.target == "get_hint"


def test_covers_common_game_status_questions() -> None:
    examples = {
        "我有多少分": "get_score",
        "现在第几轮": "get_round",
        "还剩几题": "get_remaining",
        "目标是什么": "get_goal",
        "怎么玩": "get_rule",
        "再说一遍": "repeat_prompt",
        "现在什么游戏": "get_current_game",
        "游戏状态怎么样": "get_status",
        "现在几级": "get_level",
        "还有多少能量": "get_energy",
        "我答对几个": "get_correct",
        "我错了几个": "get_errors",
        "我试了几次": "get_attempts",
        "拿到几颗星": "get_stars",
        "还剩多少题": "get_remaining",
        "应该点哪个": "get_goal",
        "玩到哪里了": "get_progress",
    }

    for text, intent in examples.items():
        query = resolve_game_status_query(text)
        assert query is not None
        assert query.intent == intent
