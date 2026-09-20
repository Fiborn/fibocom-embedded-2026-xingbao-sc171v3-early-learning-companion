"""Rule-based safe profile extraction from text turns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.memory import is_sensitive_text, sanitize_memory_updates


_CLAUSE_SPLIT_RE = re.compile(r"[，。！？；,.!?;\n]+")
_INTEREST_PATTERNS = (
    re.compile(r"(?:我)?(?:最)?喜欢(?!玩)(?P<value>[^，。！？；,.!?;\n]{1,20})"),
    re.compile(r"(?:我)?(?:很)?爱(?!玩)(?P<value>[^，。！？；,.!?;\n]{1,20})"),
)
_GAME_PATTERNS = (
    re.compile(r"(?:我)?(?:最)?喜欢玩(?P<value>[^，。！？；,.!?;\n]{1,20})"),
    re.compile(r"(?:我)?(?:很)?爱玩(?P<value>[^，。！？；,.!?;\n]{1,20})"),
)
_LEARNING_TOPIC_PATTERNS = (
    re.compile(
        r"(?:我)?(?:想听|想知道|想了解|想认识|讲讲|说说|告诉我)"
        r"(?:一个|一段|关于)?(?P<value>[^，。！？；,.!?;\n]{1,12}?)"
        r"(?:的)?(?:故事|小故事|知识|秘密)"
    ),
    re.compile(r"(?P<value>恐龙|三角龙|霸王龙|翼龙|梁龙|动物|太空|星星|火山|机器人)(?:故事|知识|秘密)"),
)

_MOOD_KEYWORDS = {
    "happy": ("开心", "高兴", "快乐", "兴奋", "happy"),
    "sad": ("难过", "伤心", "不开心", "sad"),
    "angry": ("生气", "烦", "angry"),
    "scared": ("害怕", "怕", "scared"),
    "nervous": ("紧张", "担心", "nervous"),
}


@dataclass
class ProfileExtractionResult:
    """Safe memory updates plus whether sensitive text was ignored."""

    updates: dict[str, Any] = field(default_factory=dict)
    ignored_sensitive: bool = False


class ProfileExtractor:
    """Extracts only allowed non-sensitive profile hints from user text."""

    def extract(self, text: str) -> ProfileExtractionResult:
        raw_text = text.strip()
        if not raw_text:
            return ProfileExtractionResult()

        ignored_sensitive = False
        interests: list[str] = []
        favorite_games: list[str] = []
        recent_topics: list[str] = []

        for clause in _split_clauses(raw_text):
            if is_sensitive_text(clause):
                ignored_sensitive = True
                continue
            interests.extend(_extract_values(clause, _INTEREST_PATTERNS))
            favorite_games.extend(_extract_values(clause, _GAME_PATTERNS))
            learning_topics = _extract_values(clause, _LEARNING_TOPIC_PATTERNS)
            interests.extend(learning_topics)
            recent_topics.extend(learning_topics)

        updates: dict[str, Any] = {}
        if interests:
            updates["interests"] = _dedupe(interests)
        if favorite_games:
            updates["favorite_games"] = _dedupe(favorite_games)
        if recent_topics:
            updates["recent_topics"] = _dedupe(recent_topics)

        mood = _extract_mood(raw_text)
        if mood:
            updates["recent_mood"] = mood

        communication_style = _extract_communication_style(raw_text)
        if communication_style:
            updates["communication_style"] = communication_style

        return ProfileExtractionResult(
            updates=sanitize_memory_updates(updates),
            ignored_sensitive=ignored_sensitive,
        )


def _split_clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(text) if part.strip()]


def _extract_values(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    values = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            value = _clean_value(match.group("value"))
            if value and not is_sensitive_text(value):
                values.append(value)
    return values


def _extract_mood(text: str) -> str:
    if is_sensitive_text(text):
        return ""
    lowered = text.lower()
    for mood, keywords in _MOOD_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return mood
    return ""


def _extract_communication_style(text: str) -> dict[str, bool]:
    if is_sensitive_text(text):
        return {}

    style: dict[str, bool] = {}
    if any(word in text for word in ("短一点", "简单说", "说短点", "别说太长")):
        style["likes_short_answers"] = True
    if any(word in text for word in ("鼓励我", "夸夸我", "给我加油")):
        style["needs_encouragement"] = True
    if any(word in text for word in ("给我选项", "让我选", "选择题")):
        style["prefers_choice_questions"] = True
    return style


def _clean_value(value: str) -> str:
    cleaned = value.strip(" ：，。！？；,.!?;")
    cleaned = re.sub(r"^(是|的|一个|一点|很|特别)", "", cleaned).strip()
    return cleaned


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
