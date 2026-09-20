import json
from pathlib import Path

from core.knowledge_base import KnowledgeBase


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_knowledge_base_never_returns_fixed_weather_reply(tmp_path: Path) -> None:
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"
    _write_json(knowledge_path, {"topics": [], "festivals": []})
    _write_json(
        daily_path,
        {
            "city": "杭州",
            "weather": {
                "condition": "多云",
                "temperature_range": "26到32度",
                "child_advice": "可以喝一小口水，出去玩别晒太久。",
            },
        },
    )

    reply = KnowledgeBase(knowledge_path, daily_path).prepared_reply("今天天气怎么样")

    assert reply is None


def test_knowledge_base_adds_matched_topic_to_prompt_context(tmp_path: Path) -> None:
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"
    _write_json(
        knowledge_path,
        {
            "topics": [
                {
                    "name": "恐龙",
                    "keywords": ["恐龙", "三角龙"],
                    "facts": ["三角龙有三只角。"],
                    "story_seed": "小三角龙在河边发现脚印。",
                }
            ],
            "festivals": [],
        },
    )
    _write_json(daily_path, {})

    context = KnowledgeBase(knowledge_path, daily_path).build_prompt_context("讲一个恐龙故事")

    assert "主题准备: 恐龙" in context
    assert "三角龙有三只角" in context
    assert "小三角龙在河边发现脚印" in context


def test_knowledge_base_answers_known_festival(tmp_path: Path) -> None:
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"
    _write_json(
        knowledge_path,
        {
            "topics": [],
            "festivals": [
                {
                    "name": "端午节",
                    "keywords": ["端午", "粽子"],
                    "facts": ["端午节常见习俗有吃粽子、赛龙舟、挂艾草。"],
                    "child_hook": "可以观察粽叶是什么颜色。",
                }
            ],
        },
    )
    _write_json(daily_path, {})

    reply = KnowledgeBase(knowledge_path, daily_path).prepared_reply("端午是什么")

    assert reply is not None
    assert reply.source == "festival"
    assert "吃粽子" in reply.text
