import json
from pathlib import Path
from threading import Barrier, Thread

from core.parent_summary import ParentSummaryManager


def test_parent_summaries_cover_memory_and_chat_habits(tmp_path: Path) -> None:
    manager = ParentSummaryManager(tmp_path / "summaries.json")

    summaries = manager.refresh_from_memory(
        {
            "facts": ["第一次独立完成拼图"],
            "interests": ["好", "好啊", "恐龙", "画画"],
            "favorite_games": ["记忆游戏"],
            "recent_topics": ["星星"],
            "communication_style": {"pace": "喜欢慢慢说"},
            "preferences": {},
            "summary": "",
            "recent_mood": "happy",
        },
        [
            {"role": "child", "content": "为什么星星会亮？"},
            {"role": "child", "content": "我想画恐龙"},
        ],
    )

    text = "\n".join(item["content"] for item in summaries)
    assert "第一次独立完成拼图" in text
    assert "恐龙" in text
    assert "记忆游戏" in text
    assert "好啊" not in text
    assert "提问探索" in text
    assert "happy" in text
    assert any(item["title"] == "兴趣爱好" for item in summaries)
    assert any(item["title"] == "游戏偏好" for item in summaries)
    assert any(item["category"] == "memories" for item in summaries)


def test_deleted_summary_stays_out_of_prompt_and_identical_refresh(
    tmp_path: Path,
) -> None:
    manager = ParentSummaryManager(tmp_path / "summaries.json")
    summaries = manager.refresh_from_memory({"interests": ["恐龙"]})
    target = next(item for item in summaries if item["category"] == "interests")

    assert manager.delete(target["id"])
    assert "恐龙" not in manager.prompt_context()

    manager.refresh_from_memory({"interests": ["恐龙"]})
    assert "恐龙" not in manager.prompt_context()

    manager.refresh_from_memory({"interests": ["恐龙", "画画"]})
    assert "画画" in manager.prompt_context()


def test_sensitive_parent_summary_is_rejected(tmp_path: Path) -> None:
    manager = ParentSummaryManager(tmp_path / "summaries.json")

    result = manager.upsert(
        category="preferences",
        title="信息",
        content="孩子学校是某某小学",
        source_key="manual",
    )

    assert result is None
    assert manager.load() == []


def test_two_managers_preserve_concurrent_summary_updates(tmp_path: Path) -> None:
    path = tmp_path / "summaries.json"
    first = ParentSummaryManager(path)
    second = ParentSummaryManager(path)
    barrier = Barrier(2)

    def write(manager: ParentSummaryManager, source_key: str, content: str) -> None:
        barrier.wait()
        manager.upsert(
            category="preferences",
            title="互动偏好",
            content=content,
            source_key=source_key,
        )

    threads = [
        Thread(target=write, args=(first, "game.first", "喜欢先听例子")),
        Thread(target=write, args=(second, "game.second", "喜欢慢慢回答")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    contents = {item["content"] for item in first.load()}
    assert contents == {"喜欢先听例子", "喜欢慢慢回答"}


def test_dismissed_fingerprint_wins_over_stale_summary_copy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "summaries.json"
    manager = ParentSummaryManager(path)
    item = manager.upsert(
        category="preferences",
        title="互动偏好",
        content="喜欢慢慢回答",
        source_key="game.preference",
    )
    assert item is not None
    assert manager.delete(item["id"])

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summaries"].append(item)
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    assert manager.load() == []
