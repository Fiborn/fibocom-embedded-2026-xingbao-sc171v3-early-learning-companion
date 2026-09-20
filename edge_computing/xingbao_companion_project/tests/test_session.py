from pathlib import Path

from core.memory import MemoryManager
from core.session import DEFAULT_TEXT_DEMO_INPUT, SessionManager


def test_text_demo_records_one_placeholder_turn(tmp_path: Path) -> None:
    session = SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))

    output = session.run_text_demo()

    assert DEFAULT_TEXT_DEMO_INPUT in output
    assert "Xingbao:" in output
    assert "Action:" in output
    assert "Prompt preview:" in output
    assert len(session.history) == 1


def test_text_turn_normalizes_empty_input(tmp_path: Path) -> None:
    session = SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))

    turn = session.run_text_turn("   ")

    assert turn.user_text == DEFAULT_TEXT_DEMO_INPUT
    assert turn.action == {"screen_expression": "smile"}
    assert session.history == [turn]


def test_text_turn_applies_safe_profile_updates(tmp_path: Path) -> None:
    session = SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))

    session.run_text_turn("我喜欢画画，我的电话是123456")

    memory = session.memory_manager.load()
    assert memory["interests"] == ["画画"]
    assert "电话" not in str(memory)


def test_text_turn_persists_both_messages_for_memory_book(tmp_path: Path) -> None:
    session = SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))

    turn = session.run_text_turn("我想画画")

    assert session.conversation_history_store is not None
    records = session.conversation_history_store.load()
    assert [item["role"] for item in records] == ["child", "xingbao"]
    assert records[0]["content"] == "我想画画"
    assert records[1]["content"] == turn.assistant_text
