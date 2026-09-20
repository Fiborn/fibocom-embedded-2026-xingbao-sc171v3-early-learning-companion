"""Verify the memory-book and parent-summary flow across central and touch UI."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.conversation_history import ConversationHistoryStore
from core.knowledge_base import KnowledgeBase
from core.memory import MemoryManager
from core.parent_summary import ParentSummaryManager
from core.session import SessionManager
from intelligence.prompt_builder import PromptBuilder


DEFAULT_TOUCH_ROOT = (
    PROJECT_ROOT
    / "work"
    / "incoming"
    / "xingbao_touch_game_latest"
    / "xingbao_touch_game"
)


def run_verification(touch_root: Path | str | None = None) -> dict[str, Any]:
    """Exercise one shared-data flow and raise when any contract is broken."""
    touch_root = _resolve_touch_root(touch_root)
    touch_module = _load_touch_integrations(touch_root)

    with tempfile.TemporaryDirectory(prefix="xingbao-memory-book-") as directory:
        data_dir = Path(directory)
        memory_manager = MemoryManager(data_dir / "memory.json")
        history_store = ConversationHistoryStore(
            data_dir / "conversation_history.json",
            limit=80,
        )
        summary_manager = ParentSummaryManager(data_dir / "parent_summaries.json")
        memory_manager.save(
            {
                "interests": ["恐龙", "画画"],
                "favorite_games": ["记忆游戏"],
                "recent_topics": ["月亮", "恐龙"],
                "communication_style": {"表达节奏": "喜欢慢慢说"},
                "preferences": {"讲解方式": "先举例再提问"},
                "recent_mood": "happy",
            }
        )
        session = SessionManager(
            memory_manager=memory_manager,
            conversation_history_store=history_store,
            parent_summary_manager=summary_manager,
        )
        for index in range(42):
            session.record_assistant_turn(
                user_text=f"这是第{index}次聊天，我想知道为什么星星会亮？",
                assistant_text=f"这是星宝的第{index}次回答，我们一起慢慢找答案。",
            )

        central_records = history_store.load()
        _require(len(central_records) == 80, "central history did not retain exactly 80")
        _require(
            central_records[0]["content"].startswith("这是第2次聊天"),
            "central history did not evict the oldest four messages",
        )

        touch_history = touch_module.ConversationHistoryBackend(
            data_dir / "conversation_history.json",
            limit=80,
        )
        touch_records = touch_history.load()
        _require(touch_records == central_records, "touch UI did not read central history")
        _require(
            touch_history.recent(1)[0]["role"] == "xingbao",
            "touch UI newest-first history order is incorrect",
        )

        summary_manager.refresh_from_memory(
            memory_manager.load(),
            central_records,
        )
        touch_summaries = touch_module.ParentSummaryBackend(
            data_dir / "parent_summaries.json"
        )
        touch_summaries.refresh(
            memory_manager.load(),
            {
                "total_attempts": 24,
                "total_success": 20,
                "total_games": 6,
                "total_seconds": 420,
                "favorite_game_name": "记忆游戏",
            },
            touch_records,
        )
        summaries = touch_summaries.load()
        categories = {item["category"] for item in summaries}
        _require(
            {
                "interests",
                "chat_habits",
                "answer_performance",
                "play_time",
                "conversation_style",
                "preferences",
            }.issubset(categories),
            "parent summary categories are incomplete",
        )

        deleted = next(
            item for item in summaries if item["category"] == "answer_performance"
        )
        _require(touch_summaries.delete(deleted["id"]), "touch UI deletion failed")
        summary_manager.refresh_from_memory(memory_manager.load(), central_records)
        _require(
            deleted["content"] not in summary_manager.prompt_context(limit=40),
            "deleted summary returned to central prompt context",
        )

        prompt = PromptBuilder(
            role_config_path=PROJECT_ROOT / "config" / "role_config.json",
            child_profile_path=PROJECT_ROOT / "config" / "child_profile.json",
            memory_manager=memory_manager,
            conversation_history_store=history_store,
            parent_summary_manager=summary_manager,
            knowledge_base=KnowledgeBase(
                PROJECT_ROOT / "config" / "knowledge_base.json",
                PROJECT_ROOT / "config" / "daily_context.json",
            ),
        ).build_system_prompt("今天继续聊恐龙")
        _require("家长可控的陪伴总结" in prompt, "prompt has no parent summary section")
        _require("兴趣爱好" in prompt, "active parent summaries did not enter prompt")
        _require(
            deleted["content"] not in prompt,
            "deleted parent summary still influences conversation",
        )

        return {
            "ok": True,
            "history_count": len(touch_records),
            "summary_count": len(touch_summaries.load()),
            "categories": sorted(categories),
            "deleted_summary_absent_from_prompt": True,
            "touch_root": str(touch_root),
        }


def _load_touch_integrations(touch_root: Path) -> ModuleType:
    path = touch_root / "src" / "desktop_integrations.py"
    if not path.exists():
        raise FileNotFoundError(f"Touch integration source not found: {path}")
    spec = importlib.util.spec_from_file_location(
        "xingbao_touch_desktop_integrations_verify",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load touch integration source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_touch_root(touch_root: Path | str | None) -> Path:
    if touch_root is not None:
        return Path(touch_root).expanduser().resolve()
    configured = str(os.environ.get("XINGBAO_TOUCH_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if DEFAULT_TOUCH_ROOT.exists():
        return DEFAULT_TOUCH_ROOT.resolve()
    board_root = Path(
        "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge"
    )
    if board_root.exists():
        return board_root.resolve()
    return DEFAULT_TOUCH_ROOT.resolve()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Xingbao memory-book shared-data flow."
    )
    parser.add_argument(
        "--touch-root",
        type=Path,
        default=None,
        help="Touch UI source root containing src/desktop_integrations.py.",
    )
    return parser.parse_args()


def main() -> int:
    result = run_verification(parse_args().touch_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
