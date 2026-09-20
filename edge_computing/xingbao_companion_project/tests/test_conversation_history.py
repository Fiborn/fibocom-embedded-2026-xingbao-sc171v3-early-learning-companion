import json
from pathlib import Path

from core.conversation_history import ConversationHistoryStore


def test_history_keeps_complete_transcript_by_default(tmp_path: Path) -> None:
    store = ConversationHistoryStore(tmp_path / "history.json")

    for index in range(45):
        store.append_turn(
            child_text=f"孩子消息{index}",
            xingbao_text=f"星宝回复{index}",
        )

    entries = store.load()
    assert len(entries) == 90
    assert entries[0]["content"] == "孩子消息0"
    assert entries[-1]["content"] == "星宝回复44"
    assert store.recent(1)[0]["content"] == "星宝回复44"


def test_history_does_not_persist_sensitive_messages(tmp_path: Path) -> None:
    store = ConversationHistoryStore(tmp_path / "history.json")

    additions = store.append_turn(
        child_text="我的学校是某某小学",
        xingbao_text="我们可以聊聊今天的心情。",
    )

    assert additions == []
    assert store.load() == []


def test_history_recovers_from_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{broken", encoding="utf-8")

    store = ConversationHistoryStore(path)
    assert store.load() == []
    store.append("child", "我喜欢画画")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["role"] == "child"
