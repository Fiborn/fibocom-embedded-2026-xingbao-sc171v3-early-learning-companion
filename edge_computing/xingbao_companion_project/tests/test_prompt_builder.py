import json
from pathlib import Path

from core.knowledge_base import KnowledgeBase
from core.memory import MemoryManager
from intelligence.prompt_builder import PromptBuilder


def test_prompt_builder_uses_local_config_and_safe_memory(tmp_path: Path) -> None:
    role_config = tmp_path / "role_config.json"
    child_profile = tmp_path / "child_profile.json"
    memory_path = tmp_path / "memory.json"
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"

    role_config.write_text(
        json.dumps(
            {
                "default_name": "星宝",
                "identity": "住在智能陪伴桌里的小星球机器人",
                "age_range": "4-6岁",
                "base_style": "温暖、简短",
                "max_reply_chars": 80,
                "safety_rules": ["不询问隐私"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    child_profile.write_text(
        json.dumps(
            {
                "pet_display_name": "星宝",
                "child_nickname": "小朋友",
                "interests": ["画画"],
                "favorite_games": [],
                "recent_mood": "neutral",
                "communication_style": {
                    "likes_short_answers": True,
                    "needs_encouragement": True,
                    "prefers_choice_questions": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    knowledge_path.write_text(
        json.dumps(
            {
                "topics": [
                    {
                        "name": "恐龙",
                        "keywords": ["恐龙"],
                        "facts": ["三角龙有三只角。"],
                    }
                ],
                "festivals": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    daily_path.write_text(
        json.dumps(
            {
                "city": "杭州",
                "weather": {
                    "condition": "多云",
                    "temperature_range": "26到32度",
                    "child_advice": "可以喝一小口水。",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    MemoryManager(memory_path).save(
        {
            "interests": ["恐龙"],
            "summary": "喜欢问为什么",
        }
    )

    prompt = PromptBuilder(
        role_config_path=role_config,
        child_profile_path=child_profile,
        memory_manager=MemoryManager(memory_path),
        knowledge_base=KnowledgeBase(knowledge_path, daily_path),
    ).build_system_prompt("讲一个恐龙故事")

    assert "你叫星宝" in prompt
    assert "4-6岁" in prompt
    assert "先直接说结论" in prompt
    assert "遇到学习类问题，先准确回答" in prompt
    assert "讲古诗词时" in prompt
    assert "偏好简短回答、需要温和鼓励" in prompt
    assert "不要询问或保存家庭住址" in prompt
    assert "恐龙" in prompt
    assert "喜欢问为什么" in prompt
    assert "家长可控的陪伴总结" in prompt
    assert "绝不能作为这些实时信息的事实来源" in prompt
    assert "今日天气" not in prompt
    assert "三角龙有三只角" in prompt
