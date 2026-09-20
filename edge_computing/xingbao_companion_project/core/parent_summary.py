"""Parent-visible, deletable summaries that may softly guide conversation."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.memory import is_sensitive_text


DEFAULT_PARENT_SUMMARY_PATH = Path("data/parent_summaries.json")
ALLOWED_CATEGORIES = {
    "memories",
    "interests",
    "chat_habits",
    "answer_performance",
    "play_time",
    "conversation_style",
    "recent_change",
    "preferences",
}

PROFILE_FILLER_WORDS = {
    "好",
    "好的",
    "好啊",
    "好呀",
    "好吧",
    "好他",
    "嗯",
    "嗯嗯",
    "哦",
    "哦哦",
    "可以",
    "是的",
    "不是",
    "你好",
    "再见",
    "谢谢",
}


class ParentSummaryManager:
    """Maintain local, non-sensitive insights with deletion tombstones."""

    def __init__(self, path: Path | str = DEFAULT_PARENT_SUMMARY_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> list[dict[str, str]]:
        with self._lock:
            payload = self._load_payload()
            return list(payload["summaries"])

    def refresh_from_memory(
        self,
        memory: dict[str, Any],
        conversation_entries: Iterable[dict[str, Any]] = (),
    ) -> list[dict[str, str]]:
        """Refresh generated memory/chat summaries without restoring deletions."""
        candidates = _memory_candidates(memory)
        candidates.extend(_conversation_candidates(conversation_entries))
        with self._lock:
            with _exclusive_path_lock(self.path):
                payload = self._load_payload()
                summaries = _merge_generated(
                    payload["summaries"],
                    candidates,
                    set(payload["dismissed_fingerprints"]),
                )
                payload["summaries"] = summaries
                self._save_payload(payload)
                return list(summaries)

    def upsert(
        self,
        *,
        category: str,
        title: str,
        content: str,
        source_key: str,
    ) -> dict[str, str] | None:
        """Add or update a safe summary, used by the game/desktop integration."""
        candidate = _candidate(category, title, content, source_key)
        if candidate is None:
            return None
        with self._lock:
            with _exclusive_path_lock(self.path):
                payload = self._load_payload()
                if candidate["fingerprint"] in payload["dismissed_fingerprints"]:
                    return None
                summaries = [
                    item
                    for item in payload["summaries"]
                    if item.get("source_key") != candidate["source_key"]
                ]
                summaries.append(_materialize(candidate))
                payload["summaries"] = summaries[-40:]
                self._save_payload(payload)
                return payload["summaries"][-1]

    def delete(self, summary_id: str) -> bool:
        """Delete one summary and prevent the identical summary from reappearing."""
        target = str(summary_id).strip()
        if not target:
            return False
        with self._lock:
            with _exclusive_path_lock(self.path):
                payload = self._load_payload()
                removed = next(
                    (item for item in payload["summaries"] if item.get("id") == target),
                    None,
                )
                if removed is None:
                    return False
                payload["summaries"] = [
                    item for item in payload["summaries"] if item.get("id") != target
                ]
                fingerprint = str(removed.get("fingerprint", "")).strip()
                dismissed = list(payload["dismissed_fingerprints"])
                if fingerprint and fingerprint not in dismissed:
                    dismissed.append(fingerprint)
                payload["dismissed_fingerprints"] = dismissed[-100:]
                self._save_payload(payload)
                return True

    def prompt_context(self, limit: int | None = None) -> str:
        """Return all parent-controlled, non-sensitive context for the LLM."""
        lines = []
        summaries = self.load()
        if limit is not None:
            summaries = summaries[-max(0, int(limit)) :]
        for item in summaries:
            title = item.get("title", "").strip()
            content = item.get("content", "").strip()
            if title and content:
                lines.append(f"- {title}：{content}")
        return "\n".join(lines) if lines else "- 暂无"

    def _load_payload(self) -> dict[str, list[Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        dismissed = [
            str(item)[:64]
            for item in raw.get("dismissed_fingerprints", [])
            if isinstance(item, str) and item.strip()
        ]
        dismissed = list(dict.fromkeys(dismissed))[-100:]
        summaries = [
            cleaned
            for item in raw.get("summaries", [])
            if isinstance(item, dict)
            for cleaned in [_sanitize_summary(item)]
            if cleaned is not None
            and cleaned.get("fingerprint") not in dismissed
        ]
        return {
            "summaries": summaries[-40:],
            "dismissed_fingerprints": dismissed,
        }

    def _save_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _memory_candidates(memory: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    facts = _profile_strings(memory.get("facts"))
    interests = _profile_strings(memory.get("interests"))
    favorite_games = _profile_strings(memory.get("favorite_games"))
    recent_topics = _profile_strings(memory.get("recent_topics"))
    communication_style = _safe_mapping_text(memory.get("communication_style"))
    preferences = _safe_mapping_text(memory.get("preferences"))
    summary = _safe_text(memory.get("summary"))
    recent_mood = _safe_text(memory.get("recent_mood"))

    if facts:
        _append_candidate(
            candidates,
            "memories",
            "留下的记忆",
            "星宝记得：" + "；".join(facts[-8:]),
            "memory.facts",
        )
    if interests:
        _append_candidate(
            candidates,
            "interests",
            "兴趣爱好",
            "最近表现出对" + "、".join(interests[-6:]) + "的兴趣",
            "memory.interests",
        )
    if favorite_games:
        _append_candidate(
            candidates,
            "interests",
            "游戏偏好",
            "常玩的游戏有" + "、".join(favorite_games[-4:]),
            "memory.favorite_games",
        )
    if recent_topics:
        _append_candidate(
            candidates,
            "chat_habits",
            "最近常聊",
            "近期经常聊到" + "、".join(recent_topics[-6:]),
            "memory.recent_topics",
        )
    if communication_style:
        _append_candidate(
            candidates,
            "conversation_style",
            "对话风格",
            communication_style,
            "memory.communication_style",
        )
    if preferences:
        _append_candidate(
            candidates,
            "preferences",
            "互动偏好",
            preferences,
            "memory.preferences",
        )
    if summary:
        _append_candidate(
            candidates,
            "recent_change",
            "陪伴观察",
            summary,
            "memory.summary",
        )
    if recent_mood and recent_mood.lower() not in {"neutral", "unknown", "none"}:
        _append_candidate(
            candidates,
            "recent_change",
            "近期状态",
            f"最近表达出的心情倾向是{recent_mood}",
            "memory.recent_mood",
        )
    return candidates


def _conversation_candidates(
    entries: Iterable[dict[str, Any]],
) -> list[dict[str, str]]:
    child_messages = [
        " ".join(str(item.get("content", "")).split())
        for item in entries
        if isinstance(item, dict) and item.get("role") == "child"
    ]
    child_messages = [
        text for text in child_messages if text and not is_sensitive_text(text)
    ]
    if not child_messages:
        return []
    average_length = sum(len(text) for text in child_messages) / len(child_messages)
    question_count = sum(
        1
        for text in child_messages
        if any(mark in text for mark in ("?", "？", "为什么", "怎么", "什么"))
    )
    style = "更常用简短表达" if average_length <= 12 else "更常用完整句子表达"
    if question_count / len(child_messages) >= 0.3:
        style += "，也喜欢通过提问探索"
    candidate = _candidate(
        "conversation_style",
        "聊天习惯",
        f"根据最近{len(child_messages)}次表达，孩子{style}",
        "conversation.statistics",
    )
    return [candidate] if candidate is not None else []


def _merge_generated(
    existing: list[dict[str, str]],
    candidates: list[dict[str, str]],
    dismissed: set[str],
) -> list[dict[str, str]]:
    generated_keys = {item["source_key"] for item in candidates}
    merged = [
        item
        for item in existing
        if item.get("source_key") not in generated_keys
        and not str(item.get("source_key", "")).startswith(("memory.", "conversation."))
        and item.get("fingerprint") not in dismissed
    ]
    existing_by_fingerprint = {
        item.get("fingerprint"): item for item in existing if item.get("fingerprint")
    }
    for candidate in candidates:
        if candidate["fingerprint"] in dismissed:
            continue
        old = existing_by_fingerprint.get(candidate["fingerprint"])
        merged.append(old if old is not None else _materialize(candidate))
    return merged[-40:]


def _append_candidate(
    output: list[dict[str, str]],
    category: str,
    title: str,
    content: str,
    source_key: str,
) -> None:
    candidate = _candidate(category, title, content, source_key)
    if candidate is not None:
        output.append(candidate)


def _candidate(
    category: str,
    title: str,
    content: str,
    source_key: str,
) -> dict[str, str] | None:
    category = str(category).strip()
    title = _safe_text(title)[:30]
    content = _safe_text(content)[:240]
    source_key = str(source_key).strip()[:80]
    if (
        category not in ALLOWED_CATEGORIES
        or not title
        or not content
        or not source_key
    ):
        return None
    fingerprint = hashlib.sha256(
        f"{source_key}\0{content}".encode("utf-8")
    ).hexdigest()[:32]
    return {
        "category": category,
        "title": title,
        "content": content,
        "source_key": source_key,
        "fingerprint": fingerprint,
    }


def _materialize(candidate: dict[str, str]) -> dict[str, str]:
    return {
        "id": uuid.uuid4().hex,
        "category": candidate["category"],
        "title": candidate["title"],
        "content": candidate["content"],
        "source_key": candidate["source_key"],
        "fingerprint": candidate["fingerprint"],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _sanitize_summary(raw: dict[str, Any]) -> dict[str, str] | None:
    candidate = _candidate(
        str(raw.get("category", "")),
        str(raw.get("title", "")),
        str(raw.get("content", "")),
        str(raw.get("source_key", "")),
    )
    if candidate is None:
        return None
    return {
        "id": str(raw.get("id", "")).strip()[:64] or uuid.uuid4().hex,
        **candidate,
        "updated_at": str(raw.get("updated_at", "")).strip()[:40]
        or datetime.now().isoformat(timespec="seconds"),
    }


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        for text in [_safe_text(item)]
        if text
    ]


def _profile_strings(value: Any) -> list[str]:
    """Remove acknowledgement noise before presenting memory as a profile."""
    return [
        text
        for text in _strings(value)
        if len(text) >= 2 and text not in PROFILE_FILLER_WORDS
    ]


def _safe_mapping_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key, item in list(value.items())[:8]:
        safe_key = _safe_text(key)
        safe_value = _safe_text(item)
        if safe_key and safe_value:
            parts.append(f"{safe_key}：{safe_value}")
    return "；".join(parts)


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return "" if not text or is_sensitive_text(text) else text


@contextmanager
def _exclusive_path_lock(
    path: Path,
    *,
    timeout_seconds: float = 3.0,
    stale_seconds: float = 30.0,
):
    """Serialize cross-process summary read/modify/write transactions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > stale_seconds:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise OSError(f"Timed out waiting for summary lock: {lock_path}")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
