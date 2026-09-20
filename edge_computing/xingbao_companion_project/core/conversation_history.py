"""Persistent, privacy-safe conversation history for the memory book."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.memory import is_sensitive_text


DEFAULT_CONVERSATION_HISTORY_PATH = Path("data/conversation_history.json")
# Zero means unlimited.  The memory book can browse the full safe transcript.
DEFAULT_HISTORY_LIMIT = 0
ALLOWED_ROLES = {"child", "xingbao"}


class ConversationHistoryStore:
    """Keep the latest child/Xingbao messages for local visual playback."""

    def __init__(
        self,
        path: Path | str = DEFAULT_CONVERSATION_HISTORY_PATH,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self.path = Path(path)
        self.limit = max(0, int(limit))
        self._lock = threading.RLock()

    def load(self) -> list[dict[str, str]]:
        """Return validated entries in chronological order."""
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError):
                return []
            if not isinstance(raw, list):
                return []
            entries = [
                cleaned
                for item in raw
                if isinstance(item, dict)
                for cleaned in [_sanitize_entry(item)]
                if cleaned is not None
            ]
            return entries if self.limit == 0 else entries[-self.limit :]

    def recent(self, limit: int | None = None) -> list[dict[str, str]]:
        """Return newest entries first, suitable for the memory-book UI."""
        entries = self.load()
        count = self.limit if limit is None else max(0, int(limit))
        if count == 0 and limit is None:
            return list(reversed(entries))
        return list(reversed(entries[-count:]))

    def append(self, role: str, content: str) -> dict[str, str] | None:
        """Append one safe message; sensitive or empty messages are not stored."""
        with self._lock:
            entry = _new_entry(role, content)
            if entry is None:
                return None
            entries = self.load()
            entries.append(entry)
            self._save(entries)
            return entry

    def append_turn(
        self,
        *,
        child_text: str,
        xingbao_text: str,
    ) -> list[dict[str, str]]:
        """Atomically append both sides of a completed conversation turn."""
        with self._lock:
            child_entry = _new_entry("child", child_text)
            xingbao_entry = _new_entry("xingbao", xingbao_text)
            # Keep the transcript coherent and avoid retaining the other side of
            # a turn when either message contains disallowed child information.
            if child_entry is None or xingbao_entry is None:
                return []
            additions = [child_entry, xingbao_entry]
            entries = self.load()
            entries.extend(additions)
            self._save(entries)
            return additions

    def _save(self, entries: list[dict[str, Any]]) -> None:
        sanitized = [
            cleaned
            for item in entries
            for cleaned in [_sanitize_entry(item)]
            if cleaned is not None
        ]
        if self.limit > 0:
            sanitized = sanitized[-self.limit :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _new_entry(role: str, content: str) -> dict[str, str] | None:
    return _sanitize_entry(
        {
            "id": uuid.uuid4().hex,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "role": role,
            "content": content,
        }
    )


def _sanitize_entry(raw: dict[str, Any]) -> dict[str, str] | None:
    role = str(raw.get("role", "")).strip()
    content = " ".join(str(raw.get("content", "")).split())[:500]
    if role not in ALLOWED_ROLES or not content or is_sensitive_text(content):
        return None
    entry_id = str(raw.get("id", "")).strip()[:64] or uuid.uuid4().hex
    timestamp = str(raw.get("timestamp", "")).strip()[:40]
    if not timestamp:
        timestamp = datetime.now().isoformat(timespec="seconds")
    return {
        "id": entry_id,
        "timestamp": timestamp,
        "role": role,
        "content": content,
    }
