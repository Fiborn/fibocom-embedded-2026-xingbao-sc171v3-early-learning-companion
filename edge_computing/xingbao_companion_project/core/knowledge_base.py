"""Prepared local knowledge for Xingbao's low-latency replies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_KNOWLEDGE_BASE_PATH = Path("config/knowledge_base.json")
DEFAULT_DAILY_CONTEXT_PATH = Path("config/daily_context.json")


@dataclass(frozen=True)
class PreparedReply:
    """A local answer that can bypass the LLM for common daily questions."""

    text: str
    source: str


class KnowledgeBase:
    """Loads topic cards and daily context prepared before a child talks to Xingbao."""

    def __init__(
        self,
        knowledge_base_path: Path | str = DEFAULT_KNOWLEDGE_BASE_PATH,
        daily_context_path: Path | str = DEFAULT_DAILY_CONTEXT_PATH,
    ) -> None:
        self.knowledge_base_path = Path(knowledge_base_path)
        self.daily_context_path = Path(daily_context_path)

    def build_prompt_context(
        self,
        user_text: str = "",
        *,
        today: date | None = None,
    ) -> str:
        """Return compact context that helps the LLM sound prepared."""
        knowledge = self._load_knowledge()
        daily = self._load_daily_context()
        today = today or date.today()

        lines: list[str] = []

        for festival in self.active_festivals(today=today):
            name = str(festival.get("name", "")).strip()
            child_hook = str(festival.get("child_hook", "")).strip()
            if name and child_hook:
                lines.append(f"- 今日节日: {name}。可自然提醒: {child_hook}")

        matched_topics = self._matched_topics(knowledge, user_text)
        for topic in matched_topics[:3]:
            if _is_live_weather_request(user_text) and str(topic.get("id") or "") == "weather":
                continue
            name = str(topic.get("name", "")).strip()
            facts = _as_string_list(topic.get("facts", []))[:2]
            story_seed = str(topic.get("story_seed", "")).strip()
            if name and facts:
                lines.append(f"- 主题准备: {name}。可用事实: {'；'.join(facts)}")
            if story_seed:
                lines.append(f"- 故事钩子: {story_seed}")

        if not lines:
            return ""
        return "\n".join(lines)

    def prepared_reply(
        self,
        user_text: str,
        *,
        today: date | None = None,
    ) -> PreparedReply | None:
        """Return a direct local reply for weather and date-sensitive questions."""
        text = (user_text or "").strip()
        if not text:
            return None
        compact = _compact_text(text)
        knowledge = self._load_knowledge()
        daily = self._load_daily_context()
        today = today or date.today()

        if _looks_like_today_special_day_question(compact):
            festivals = self._active_festivals(knowledge, daily, today)
            if festivals:
                festival = festivals[0]
                name = str(festival.get("name", "")).strip()
                child_hook = str(festival.get("child_hook", "")).strip()
                fact = _first_string(festival.get("facts", []))
                reply_parts = [f"今天是{name}。" if name else ""]
                if child_hook:
                    reply_parts.append(child_hook)
                if fact:
                    reply_parts.append(f"我还知道，{fact}")
                reply = "".join(reply_parts).strip()
                if reply:
                    return PreparedReply(reply, "festival")

        for festival in self._all_festivals(knowledge, daily):
            keywords = _as_string_list(festival.get("keywords", []))
            if not any(_compact_text(keyword) in compact for keyword in keywords):
                continue
            name = str(festival.get("name", "")).strip()
            child_hook = str(festival.get("child_hook", "")).strip()
            fact = _first_string(festival.get("facts", []))
            reply = f"{name}是一个很有意义的日子。{fact}{child_hook}"
            return PreparedReply(reply.strip(), "festival")

        return None

    def active_festivals(self, *, today: date | None = None) -> list[dict[str, Any]]:
        """Return special days that are active today or explicitly configured."""
        return self._active_festivals(
            self._load_knowledge(),
            self._load_daily_context(),
            today or date.today(),
        )

    def _load_knowledge(self) -> dict[str, Any]:
        return _load_json_object(self.knowledge_base_path)

    def _load_daily_context(self) -> dict[str, Any]:
        return _load_json_object(self.daily_context_path)

    def _matched_topics(self, knowledge: dict[str, Any], user_text: str) -> list[dict[str, Any]]:
        compact = _compact_text(user_text)
        if not compact:
            return []
        topics = knowledge.get("topics", [])
        if not isinstance(topics, list):
            return []
        matched: list[dict[str, Any]] = []
        for topic in topics:
            if not isinstance(topic, dict):
                continue
            keywords = _as_string_list(topic.get("keywords", []))
            if any(_compact_text(keyword) in compact for keyword in keywords):
                matched.append(topic)
        return matched

    def _active_festivals(
        self,
        knowledge: dict[str, Any],
        daily: dict[str, Any],
        today: date,
    ) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        daily_festivals = daily.get("today_special_days", [])
        if isinstance(daily_festivals, list):
            active.extend(item for item in daily_festivals if isinstance(item, dict))

        today_key = today.strftime("%m-%d")
        for festival in self._all_festivals(knowledge, daily):
            if str(festival.get("month_day", "")).strip() == today_key:
                active.append(festival)
        return active

    def _all_festivals(
        self,
        knowledge: dict[str, Any],
        daily: dict[str, Any],
    ) -> list[dict[str, Any]]:
        festivals: list[dict[str, Any]] = []
        for source in (knowledge.get("festivals", []), daily.get("known_special_days", [])):
            if isinstance(source, list):
                festivals.extend(item for item in source if isinstance(item, dict))
        return festivals


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _is_live_weather_request(text: str) -> bool:
    compact = _compact_text(text)
    return any(
        word in compact
        for word in (
            "天气", "温度", "湿度", "几度", "多少度", "下雨", "雨吗",
            "晴吗", "刮风", "风大", "热不热", "冷不冷", "穿什么",
        )
    )


def _looks_like_today_special_day_question(compact: str) -> bool:
    return any(
        word in compact
        for word in (
            "今天什么日子",
            "今天是什么日子",
            "今天节日",
            "今天有什么特别",
            "今天是节日",
        )
    )


def _compact_text(text: str) -> str:
    return "".join((text or "").split()).lower()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _first_string(value: Any) -> str:
    items = _as_string_list(value)
    return items[0] if items else ""
