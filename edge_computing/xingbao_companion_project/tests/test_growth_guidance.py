import json
from pathlib import Path

from core.growth_guidance import (
    GrowthContext,
    GrowthGuidanceEngine,
)
from core.knowledge_base import KnowledgeBase


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _engine_with_daily_festival(tmp_path: Path) -> GrowthGuidanceEngine:
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"
    _write_json(
        knowledge_path,
        {
            "topics": [],
            "festivals": [],
        },
    )
    _write_json(
        daily_path,
        {
            "today_special_days": [
                {
                    "name": "端午节",
                    "keywords": ["端午", "粽子"],
                    "facts": ["端午节常见习俗有吃粽子、赛龙舟。"],
                    "child_hook": "可以观察粽叶是什么颜色。",
                }
            ]
        },
    )
    return GrowthGuidanceEngine(
        knowledge_base=KnowledgeBase(knowledge_path, daily_path),
        topic_cooldown_seconds=900,
        clock=lambda: 1000.0,
    )


def test_unclear_dialogue_builds_expression_scaffold() -> None:
    plan = GrowthGuidanceEngine().plan(
        {
            "type": "dialogue_event",
            "source": "dialogue",
            "payload": {"text": "今天那个……他不让我……然后我就……"},
        }
    )

    assert plan.scene == "expression_scaffold"
    assert plan.priority == 2
    assert plan.speak_text == ""
    assert plan.screen_text == ""
    assert "他不让我玩" in plan.screen_options
    assert plan.next_state == "expression_scaffold"


def test_emotion_dialogue_names_feelings() -> None:
    plan = GrowthGuidanceEngine().plan(
        {
            "type": "dialogue_event",
            "source": "dialogue",
            "payload": {"text": "我有点难过"},
        }
    )

    assert plan.scene == "emotion_naming"
    assert "生气" in plan.screen_options
    assert "难过" in plan.screen_options
    assert plan.expression == "comforting"


def test_opening_can_proactively_raise_daily_festival(tmp_path: Path) -> None:
    plan = _engine_with_daily_festival(tmp_path).plan(
        {
            "type": "proactive_opportunity",
            "source": "dialogue",
            "payload": {"opportunity": "opening"},
        },
        GrowthContext(state="opening", now=1000.0),
    )

    assert plan.scene == "proactive_topic"
    assert plan.topic_id == "festival"
    assert "端午节" in plan.speak_text
    assert "粽叶" in plan.speak_text
    assert "听一个小故事" in plan.screen_options


def test_proactive_topic_waits_when_child_is_speaking(tmp_path: Path) -> None:
    plan = _engine_with_daily_festival(tmp_path).plan(
        {
            "type": "proactive_opportunity",
            "source": "dialogue",
            "payload": {"opportunity": "opening"},
        },
        GrowthContext(state="opening", child_is_speaking=True, now=1000.0),
    )

    assert plan.scene == "proactive_topic_deferred"
    assert plan.handled is False
    assert plan.reason == "proactive_topic_not_allowed"


def test_proactive_topic_respects_cooldown(tmp_path: Path) -> None:
    plan = _engine_with_daily_festival(tmp_path).plan(
        {
            "type": "proactive_opportunity",
            "source": "dialogue",
            "payload": {"opportunity": "idle_gap"},
        },
        GrowthContext(
            state="listening",
            topic_last_spoken_at={"festival": 500.0},
            now=1000.0,
        ),
    )

    assert plan.scene == "proactive_topic_deferred"
    assert plan.reason == "topic_cooldown_active"


def test_game_finished_can_connect_to_daily_topic(tmp_path: Path) -> None:
    plan = _engine_with_daily_festival(tmp_path).plan(
        {
            "type": "game_event",
            "source": "mini_game",
            "payload": {"event": "game_finished", "game_id": "color_game"},
        },
        GrowthContext(state="playing_game", now=1000.0),
    )

    assert plan.scene == "proactive_topic"
    assert "你刚才很认真" in plan.speak_text
    assert "端午节" in plan.speak_text


def test_game_mistake_encourages_retry() -> None:
    plan = GrowthGuidanceEngine().plan(
        {
            "type": "game_event",
            "source": "mini_game",
            "payload": {"event": "child_made_mistake"},
        },
        GrowthContext(state="playing_game"),
    )

    assert plan.scene == "game_encouragement"
    assert "再试一次" in plan.speak_text
    assert plan.next_state == "playing_game"


def test_vision_sitting_too_long_has_safety_priority() -> None:
    plan = GrowthGuidanceEngine().plan(
        {
            "type": "vision_event",
            "source": "vision",
            "payload": {"event": "sitting_too_long"},
        }
    )

    assert plan.scene == "health_reminder"
    assert plan.priority == 3
    assert "伸个懒腰" in plan.speak_text


def test_danger_text_becomes_adult_help_prompt() -> None:
    plan = GrowthGuidanceEngine().plan(
        {
            "type": "dialogue_event",
            "source": "dialogue",
            "payload": {"text": "我受伤了，还流血了"},
        }
    )

    assert plan.scene == "safety_support"
    assert plan.priority == 3
    assert plan.speak_text == ""
    assert plan.screen_text == ""
    assert plan.interrupt_policy == "immediate"


def test_touch_choice_turns_into_expression_sentence() -> None:
    plan = GrowthGuidanceEngine().plan(
        {
            "type": "touch_event",
            "source": "touch",
            "payload": {
                "event": "child_selected_option",
                "label": "难过",
            },
        }
    )

    assert plan.scene == "expression_choice_confirmed"
    assert "我现在觉得难过" in plan.speak_text
    assert plan.memory_request == {"recent_topics": ["孩子练习表达：难过"]}
