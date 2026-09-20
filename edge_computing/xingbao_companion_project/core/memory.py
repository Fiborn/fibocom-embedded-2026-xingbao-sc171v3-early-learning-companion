"""Safe local memory handling for Xingbao Companion."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_MEMORY_PATH = Path("data/memory.json")

DEFAULT_MEMORY: dict[str, Any] = {
    "facts": [],
    "recent_topics": [],
    "summary": "",
    "interests": [],
    "favorite_games": [],
    "communication_style": {},
    "recent_mood": "neutral",
    "preferences": {},
}

ALLOWED_MEMORY_KEYS = set(DEFAULT_MEMORY)

SENSITIVE_MARKERS = (
    "住址",
    "地址",
    "家庭地址",
    "电话",
    "手机号",
    "手机号码",
    "学校",
    "班级",
    "精确位置",
    "定位",
    "父母电话",
    "家长电话",
    "parent contact",
    "phone",
    "address",
    "school",
    "class",
    "location",
)


class MemoryManager:
    """Loads, sanitizes, and saves non-sensitive companion memory."""

    def __init__(self, path: Path | str = DEFAULT_MEMORY_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        """Load memory from disk and remove unsupported or sensitive fields."""
        if not self.path.exists():
            return deepcopy(DEFAULT_MEMORY)

        raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            return deepcopy(DEFAULT_MEMORY)
        return sanitize_memory(raw)

    def save(self, memory: dict[str, Any]) -> dict[str, Any]:
        """Sanitize memory and write it to disk."""
        sanitized = sanitize_memory(memory)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return sanitized

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge safe updates into the current memory."""
        memory = self.load()
        for key, value in sanitize_memory_updates(updates).items():
            if isinstance(memory.get(key), list) and isinstance(value, list):
                memory[key] = _merge_unique_strings(memory[key], value)
            elif isinstance(memory.get(key), dict) and isinstance(value, dict):
                memory[key] = {**memory[key], **value}
            else:
                memory[key] = value
        return self.save(memory)


def sanitize_memory(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a memory object containing only allowed non-sensitive content."""
    memory = deepcopy(DEFAULT_MEMORY)
    for key, value in raw.items():
        if key not in ALLOWED_MEMORY_KEYS:
            continue
        memory[key] = _sanitize_value(value)
    return memory


def sanitize_memory_updates(raw: dict[str, Any]) -> dict[str, Any]:
    """Return only explicitly supplied allowed fields after sanitization."""
    updates: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in ALLOWED_MEMORY_KEYS:
            continue
        cleaned = _sanitize_value(value)
        if cleaned not in ("", [], {}):
            updates[key] = cleaned
    return updates


def is_sensitive_text(text: str) -> bool:
    """Return whether text appears to contain disallowed child information."""
    return _looks_sensitive(text)


def _merge_unique_strings(existing: list[Any], incoming: list[Any]) -> list[str]:
    merged: list[str] = []
    seen = set()
    for item in existing + incoming:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return "" if _looks_sensitive(value) else value.strip()

    if isinstance(value, list):
        sanitized_items = []
        for item in value:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned and not _looks_sensitive(cleaned):
                    sanitized_items.append(cleaned)
        return sanitized_items

    if isinstance(value, dict):
        sanitized_dict = {}
        for key, item in value.items():
            if _looks_sensitive(str(key)):
                continue
            cleaned = _sanitize_value(item)
            if cleaned not in ("", [], {}):
                sanitized_dict[str(key)] = cleaned
        return sanitized_dict

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return ""


def _looks_sensitive(text: str) -> bool:
    normalized = text.lower()
    return any(marker in normalized for marker in SENSITIVE_MARKERS)
