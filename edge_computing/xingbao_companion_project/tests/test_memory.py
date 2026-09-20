from pathlib import Path

from core.memory import MemoryManager, sanitize_memory


def test_sanitize_memory_removes_unknown_and_sensitive_fields() -> None:
    raw = {
        "interests": ["画画", "家庭地址在某小区"],
        "recent_topics": ["恐龙"],
        "phone": "123456",
        "summary": "喜欢拼图",
        "school": "某某小学",
    }

    memory = sanitize_memory(raw)

    assert memory["interests"] == ["画画"]
    assert memory["recent_topics"] == ["恐龙"]
    assert memory["summary"] == "喜欢拼图"
    assert "phone" not in memory
    assert "school" not in memory


def test_memory_manager_saves_sanitized_memory(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    manager = MemoryManager(memory_path)

    saved = manager.save(
        {
            "favorite_games": ["积木"],
            "summary": "电话是123456",
            "recent_mood": "happy",
        }
    )

    loaded = manager.load()
    assert saved["favorite_games"] == ["积木"]
    assert saved["summary"] == ""
    assert loaded["recent_mood"] == "happy"


def test_memory_manager_update_merges_only_supplied_safe_fields(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    manager = MemoryManager(memory_path)
    manager.save(
        {
            "interests": ["画画"],
            "favorite_games": ["积木"],
            "summary": "喜欢问为什么",
        }
    )

    updated = manager.update(
        {
            "interests": ["画画", "恐龙"],
            "school": "某某小学",
        }
    )

    assert updated["interests"] == ["画画", "恐龙"]
    assert updated["favorite_games"] == ["积木"]
    assert updated["summary"] == "喜欢问为什么"
    assert "school" not in updated
