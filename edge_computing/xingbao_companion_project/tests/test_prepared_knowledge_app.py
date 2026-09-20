from pathlib import Path
from app import XingbaoApp
from core.knowledge_base import KnowledgeBase
from core.memory import MemoryManager
from core.session import SessionManager
from core.settings import AppSettings
from intelligence.prompt_builder import PromptBuilder


def test_weather_bypasses_static_prepared_reply_for_realtime_agent(tmp_path: Path) -> None:
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"
    role_config = tmp_path / "role_config.json"
    child_profile = tmp_path / "child_profile.json"
    memory_path = tmp_path / "memory.json"
    knowledge_path.write_text('{"topics":[],"festivals":[]}', encoding="utf-8")
    daily_path.write_text(
        (
            '{"city":"杭州","weather":'
            '{"condition":"多云","temperature_range":"26到32度",'
            '"child_advice":"可以喝一小口水。"}}'
        ),
        encoding="utf-8",
    )
    role_config.write_text(
        '{"default_name":"星宝","identity":"小星球机器人","age_range":"3-8岁"}',
        encoding="utf-8",
    )
    child_profile.write_text("{}", encoding="utf-8")

    prompt_builder = PromptBuilder(
        role_config_path=role_config,
        child_profile_path=child_profile,
        memory_manager=MemoryManager(memory_path),
        knowledge_base=KnowledgeBase(knowledge_path, daily_path),
    )
    app = XingbaoApp(
        settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0),
        session=SessionManager(
            memory_manager=MemoryManager(memory_path),
            prompt_builder=prompt_builder,
        ),
    )

    assert app._prepared_reply_for_user_text("今天天气怎么样") == ""
