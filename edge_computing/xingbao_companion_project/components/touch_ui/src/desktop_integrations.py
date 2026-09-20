"""队友模块的稳定对接层。

OpenCV只需持续写两个0/1值；UI不依赖模型、摄像头或OpenCV本身。
百宝箱工作页面通过配置启动。记忆后台只接收经过整理的非敏感摘要。
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
import webbrowser
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


DEFAULT_CONFIG = {
    "vision_status_file": "saves/vision_status.json",
    "memory_file": "saves/xingbao_memory.json",
    "conversation_history_file": "saves/conversation_history.json",
    "parent_summary_file": "saves/parent_summaries.json",
    "companion_memory_file": "saves/companion_memory.json",
    "audio_preferences_file": "saves/audio_preferences.json",
    "agent_preferences_file": "saves/agent_preferences.json",
}


class IntegrationConfig:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "config" / "desktop_integration.json"
        self.data = dict(DEFAULT_CONFIG)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self.data.update(payload)
        except (OSError, ValueError, TypeError):
            pass

    def resolve(self, key):
        shared_dir = os.environ.get("XINGBAO_COMPANION_DATA_DIR", "").strip()
        shared_names = {
            "conversation_history_file": "conversation_history.json",
            "parent_summary_file": "parent_summaries.json",
            "companion_memory_file": "memory.json",
            "audio_preferences_file": "audio_preferences.json",
            "agent_preferences_file": "agent_preferences.json",
        }
        if shared_dir and key in shared_names:
            return Path(shared_dir) / shared_names[key]
        if (
            key in shared_names
            and os.environ.get("XINGBAO_DISABLE_COMPANION_DATA_DISCOVERY", "0") != "1"
        ):
            discovered = self._discover_companion_data_dir()
            if discovered is not None:
                return discovered / shared_names[key]
        value = str(self.data.get(key, "") or "")
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def preferred_shared_path(self, key):
        """Prefer the companion data path even when its data directory is created later."""
        candidates = self.candidate_paths(key)
        for candidate in candidates:
            companion_root = candidate.parent.parent
            if (
                candidate.parent.is_dir()
                or (companion_root / "core" / "session.py").is_file()
            ):
                return candidate
        return self.resolve(key)

    def candidate_paths(self, key):
        shared_names = {
            "conversation_history_file": "conversation_history.json",
            "parent_summary_file": "parent_summaries.json",
            "companion_memory_file": "memory.json",
            "audio_preferences_file": "audio_preferences.json",
            "agent_preferences_file": "agent_preferences.json",
        }
        filename = shared_names.get(key)
        candidates = []
        shared_dir = os.environ.get("XINGBAO_COMPANION_DATA_DIR", "").strip()
        if filename and shared_dir:
            # An explicitly configured companion data directory is the
            # authoritative production source. Do not merge stale records from
            # legacy touch-game saves into the child's current history.
            return [Path(shared_dir) / filename]
        if (
            filename
            and os.environ.get("XINGBAO_DISABLE_COMPANION_DATA_DISCOVERY", "0")
            != "1"
        ):
            candidates.extend(
                data_dir / filename
                for data_dir in self._companion_data_candidates()
            )
        value = str(self.data.get(key, "") or "")
        if value:
            configured = Path(value)
            candidates.append(
                configured if configured.is_absolute() else self.root / configured
            )
        unique = []
        seen = set()
        for candidate in candidates:
            marker = str(candidate.resolve(strict=False))
            if marker not in seen:
                seen.add(marker)
                unique.append(candidate)
        return unique

    def _discover_companion_data_dir(self):
        candidates = self._companion_data_candidates()
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    def _companion_data_candidates(self):
        candidates = [self.root.parent / "xingbao_companion" / "data"]
        for ancestor in self.root.parents:
            if (ancestor / "core" / "session.py").exists():
                candidates.append(ancestor / "data")
        candidates.append(Path(
            "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion/data"
        ))
        return candidates


class VisionStateAdapter:
    """读取队友视觉模块的两个标志位：距离过近、需要喝水。"""

    def __init__(self, status_file):
        self.status_file = Path(status_file)
        self.last_state = {"distance_too_close": 0, "needs_water": 0, "available": False}

    @staticmethod
    def normalize(payload):
        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
            first, second = payload[0], payload[1]
        elif isinstance(payload, dict):
            first = payload.get("distance_too_close", payload.get("too_close", payload.get("flag1", 0)))
            second = payload.get("needs_water", payload.get("water", payload.get("flag2", 0)))
        else:
            first, second = 0, 0
        return {
            "distance_too_close": 1 if int(first or 0) == 1 else 0,
            "needs_water": 1 if int(second or 0) == 1 else 0,
            "available": True,
        }

    def read(self):
        try:
            payload = json.loads(self.status_file.read_text(encoding="utf-8"))
            self.last_state = self.normalize(payload)
        except (OSError, ValueError, TypeError):
            self.last_state = {"distance_too_close": 0, "needs_water": 0, "available": False}
        return dict(self.last_state)

    def write(self, distance_too_close, needs_water):
        """供独立视觉进程原子写入两个0/1结果，避免UI读到半个JSON。"""
        state = self.normalize([distance_too_close, needs_water])
        payload = {
            "distance_too_close": state["distance_too_close"],
            "needs_water": state["needs_water"],
        }
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_suffix(self.status_file.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.status_file)
        self.last_state = dict(state)
        return payload


class ToolboxLauncher:
    def __init__(self, root, target=""):
        self.root = Path(root)
        self.target = str(target or "")

    def launch(self):
        target = self.target.strip()
        if not target:
            return False, "尚未配置队友工作页面"
        if target.startswith(("http://", "https://", "file://")):
            webbrowser.open(target)
            return True, "视觉工作页面已打开"
        path = Path(target)
        if not path.is_absolute():
            path = self.root / path
        if not path.exists():
            return False, "工作页面不存在：{}".format(path)
        try:
            if path.suffix.lower() == ".py":
                subprocess.Popen([sys.executable, str(path)], cwd=str(path.parent))
            elif path.suffix.lower() in (".html", ".htm"):
                webbrowser.open(path.resolve().as_uri())
            else:
                subprocess.Popen([str(path)], cwd=str(path.parent))
            return True, "视觉工作页面已打开"
        except OSError as exc:
            return False, "启动失败：{}".format(exc)


class MemoryBackend:
    """星宝记忆后台的本地交换格式，只保存非敏感摘要。"""

    ALLOWED_TYPES = {"learning", "story", "game", "artwork", "health", "companion"}

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def recent(self, limit=5):
        entries = self._load()
        # Do not rely on file append order: imported or repaired histories can
        # be out of order.  The memory book always presents newest first.
        entries.sort(key=lambda entry: str(entry.get("timestamp") or ""), reverse=True)
        return entries[:max(0, int(limit))]

    def add(self, memory_type, title, summary, source="desktop", media_path=None):
        memory_type = str(memory_type)
        if memory_type not in self.ALLOWED_TYPES:
            raise ValueError("unsupported memory type")
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": memory_type,
            "title": str(title)[:60],
            "summary": str(summary)[:200],
            "source": str(source)[:30],
        }
        if media_path:
            entry["media_path"] = str(media_path)[:500]
        data = self._load()
        data.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data[-200:], ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return entry


class ConversationHistoryBackend:
    """读取完整的安全聊天记录，供儿童端回忆本浏览和点读。"""

    SENSITIVE_MARKERS = (
        "住址", "地址", "电话", "手机号", "学校", "班级", "精确位置", "定位",
        "parent contact", "phone", "address", "school", "class", "location",
    )

    def __init__(self, path, limit=0, fallback_paths=None):
        self.path = Path(path)
        # Zero means unlimited, matching the central conversation store.
        self.limit = max(0, int(limit))
        self.fallback_paths = [
            Path(item) for item in (fallback_paths or [])
            if Path(item) != self.path
        ]

    @classmethod
    def _safe_entry(cls, item):
        if not isinstance(item, dict):
            return None
        role = str(item.get("role", "")).strip()
        content = " ".join(str(item.get("content", "")).split())[:500]
        lowered = content.lower()
        if role not in ("child", "xingbao") or not content:
            return None
        if any(marker in lowered for marker in cls.SENSITIVE_MARKERS):
            return None
        return {
            "id": str(item.get("id", ""))[:64],
            "timestamp": str(item.get("timestamp", ""))[:40],
            "role": role,
            "content": content,
        }

    def load(self):
        entries = []
        seen = set()
        paths = [self.path] if self.path.is_file() else self.fallback_paths
        for path in paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(raw, list):
                continue
            for item in raw:
                cleaned = self._safe_entry(item)
                if cleaned is None:
                    continue
                marker = (
                    cleaned.get("id")
                    or "{}|{}|{}".format(
                        cleaned["timestamp"], cleaned["role"], cleaned["content"]
                    )
                )
                if marker in seen:
                    continue
                seen.add(marker)
                entries.append(cleaned)
        entries.sort(key=lambda item: item.get("timestamp", ""))
        return entries if self.limit == 0 else entries[-self.limit:]

    def recent(self, limit=None):
        # Keep the conversation in chronological order: the oldest message is
        # rendered first and the newest one remains at the bottom, like a chat
        # application.
        entries = self.load()
        if limit is None:
            return entries
        limit = max(0, int(limit))
        return entries[-limit:] if limit else []


class AgentPreferencesBackend:
    """Persist the parent-selected city used by Xingbao's weather tool."""

    def __init__(self, path):
        self.path = Path(path)

    def load_city(self, default="北京"):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            payload = {}
        city = str(payload.get("weather_city", "")).strip() if isinstance(payload, dict) else ""
        return city or str(default)

    def save_city(self, city):
        cleaned = " ".join(str(city or "").split())[:40]
        if not cleaned:
            raise ValueError("weather city must not be empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"weather_city": cleaned}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return cleaned


class AudioPreferencesBackend:
    """Share the UI volume with every central WAV playback."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self, default=100):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return self._bounded(default)
        if not isinstance(payload, dict):
            return self._bounded(default)
        return self._bounded(payload.get("volume"), default=default)

    def save(self, volume):
        bounded = self._bounded(volume)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            ".{}.{}.tmp".format(self.path.name, uuid.uuid4().hex)
        )
        temporary.write_text(
            json.dumps({"volume": bounded}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return bounded

    @staticmethod
    def _bounded(value, default=100):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = int(default)
        return max(0, min(100, parsed))


class ParentSummaryBackend:
    """与中枢共用家长总结文件，并保留手动删除记录。"""

    ALLOWED_CATEGORIES = {
        "memories", "interests", "chat_habits", "answer_performance", "play_time",
        "conversation_style", "recent_change", "preferences",
    }
    PROFILE_FILLER_WORDS = {
        "好", "好的", "好啊", "好呀", "好吧", "好他", "嗯", "嗯嗯",
        "哦", "哦哦", "可以", "是的", "不是", "你好", "再见", "谢谢",
    }

    def __init__(self, path):
        self.path = Path(path)

    def _payload(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        dismissed = [
            str(item)[:64] for item in raw.get("dismissed_fingerprints", [])
            if isinstance(item, str) and item.strip()
        ]
        dismissed = list(dict.fromkeys(dismissed))[-100:]
        summaries = [
            item for item in raw.get("summaries", [])
            if isinstance(item, dict)
            and str(item.get("category", "")) in self.ALLOWED_CATEGORIES
            and str(item.get("id", "")).strip()
            and str(item.get("content", "")).strip()
            and str(item.get("fingerprint", "")).strip() not in dismissed
        ]
        return {
            "summaries": summaries[-40:],
            "dismissed_fingerprints": dismissed,
        }

    def _save(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            "{}.{}.{}.tmp".format(self.path.name, os.getpid(), uuid.uuid4().hex)
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

    @staticmethod
    def _candidate(category, title, content, source_key):
        category = str(category).strip()
        title = " ".join(str(title).split())[:30]
        content = " ".join(str(content).split())[:240]
        source_key = str(source_key).strip()[:80]
        lowered = "{} {}".format(title, content).lower()
        if category not in ParentSummaryBackend.ALLOWED_CATEGORIES:
            return None
        if not title or not content or not source_key:
            return None
        if any(marker in lowered for marker in ConversationHistoryBackend.SENSITIVE_MARKERS):
            return None
        fingerprint = hashlib.sha256(
            "{}\0{}".format(source_key, content).encode("utf-8")
        ).hexdigest()[:32]
        return {
            "category": category,
            "title": title,
            "content": content,
            "source_key": source_key,
            "fingerprint": fingerprint,
        }

    def _upsert_candidate(self, payload, candidate):
        if candidate is None:
            return
        if candidate["fingerprint"] in payload["dismissed_fingerprints"]:
            return
        old = next(
            (
                item for item in payload["summaries"]
                if item.get("fingerprint") == candidate["fingerprint"]
            ),
            None,
        )
        payload["summaries"] = [
            item for item in payload["summaries"]
            if item.get("source_key") != candidate["source_key"]
        ]
        payload["summaries"].append(old or {
            "id": uuid.uuid4().hex,
            **candidate,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })

    def refresh(self, memory, game_summary, history_entries):
        with _exclusive_path_lock(self.path):
            payload = self._payload()
            # Rebuild derived memory/chat rows from the current safe source so
            # removed or test-only observations do not linger in the report.
            payload["summaries"] = [
                item
                for item in payload["summaries"]
                if not str(item.get("source_key", "")).startswith(
                    ("memory.", "conversation.")
                )
            ]
            facts = [
                str(item).strip() for item in memory.get("facts", [])
                if self._profile_item(item)
            ] if isinstance(memory, dict) else []
            interests = [
                str(item).strip() for item in memory.get("interests", [])
                if self._profile_item(item)
            ] if isinstance(memory, dict) else []
            favorite_games = [
                str(item).strip() for item in memory.get("favorite_games", [])
                if self._profile_item(item)
            ] if isinstance(memory, dict) else []
            if facts:
                self._upsert_candidate(payload, self._candidate(
                    "memories",
                    "留下的记忆",
                    "星宝记得：" + "；".join(facts[-8:]),
                    "memory.facts",
                ))
            if interests:
                self._upsert_candidate(payload, self._candidate(
                    "interests",
                    "兴趣爱好",
                    "最近表现出对" + "、".join(interests[-6:]) + "的兴趣",
                    "memory.interests",
                ))
            if favorite_games:
                self._upsert_candidate(payload, self._candidate(
                    "interests",
                    "游戏偏好",
                    "常玩的游戏有" + "、".join(favorite_games[-4:]),
                    "memory.favorite_games",
                ))
            recent_topics = [
                str(item).strip() for item in memory.get("recent_topics", [])
                if self._profile_item(item)
            ] if isinstance(memory, dict) else []
            if recent_topics:
                self._upsert_candidate(payload, self._candidate(
                    "chat_habits",
                    "最近常聊",
                    "近期经常聊到" + "、".join(recent_topics[-6:]),
                    "memory.recent_topics",
                ))
            communication_style = memory.get("communication_style", {}) if isinstance(memory, dict) else {}
            if isinstance(communication_style, dict) and communication_style:
                style_text = "；".join(
                    "{}：{}".format(key, value)
                    for key, value in list(communication_style.items())[:8]
                    if str(key).strip() and str(value).strip()
                )
                self._upsert_candidate(payload, self._candidate(
                    "conversation_style", "对话风格", style_text,
                    "memory.communication_style"))
            preferences = memory.get("preferences", {}) if isinstance(memory, dict) else {}
            if isinstance(preferences, dict) and preferences:
                preference_text = "；".join(
                    "{}：{}".format(key, value)
                    for key, value in list(preferences.items())[:8]
                    if str(key).strip() and str(value).strip()
                )
                self._upsert_candidate(payload, self._candidate(
                    "preferences", "互动偏好", preference_text,
                    "memory.preferences"))
            memory_summary = str(memory.get("summary", "")).strip() if isinstance(memory, dict) else ""
            if memory_summary:
                self._upsert_candidate(payload, self._candidate(
                    "recent_change", "陪伴观察", memory_summary, "memory.summary"))
            recent_mood = str(memory.get("recent_mood", "")).strip() if isinstance(memory, dict) else ""
            if recent_mood and recent_mood.lower() not in ("neutral", "unknown", "none"):
                self._upsert_candidate(payload, self._candidate(
                    "recent_change",
                    "近期状态",
                    "最近表达出的心情倾向是{}".format(recent_mood),
                    "memory.recent_mood",
                ))

            attempts = max(0, int(game_summary.get("total_attempts", 0) or 0))
            success = max(0, int(game_summary.get("total_success", 0) or 0))
            if attempts:
                rate = int(round(success * 100.0 / attempts))
                self._upsert_candidate(payload, self._candidate(
                    "answer_performance",
                    "作答情况",
                    "累计尝试{}次，完成{}次，完成率约{}%；只用于观察节奏，不作为能力定论".format(
                        attempts, success, rate),
                    "game.answer_performance",
                ))
            total_games = max(0, int(game_summary.get("total_games", 0) or 0))
            total_seconds = max(0, int(game_summary.get("total_seconds", 0) or 0))
            if total_games or total_seconds:
                minutes, seconds = divmod(total_seconds, 60)
                duration = "{}分{}秒".format(minutes, seconds) if minutes else "{}秒".format(seconds)
                self._upsert_candidate(payload, self._candidate(
                    "play_time",
                    "游玩时间",
                    "累计完成{}局，记录到的游玩时间约{}".format(total_games, duration),
                    "game.play_time",
                ))
            favorite_game = str(game_summary.get("favorite_game_name", "")).strip()
            if favorite_game:
                self._upsert_candidate(payload, self._candidate(
                    "interests",
                    "游戏喜好",
                    "目前玩得较多的是{}".format(favorite_game),
                    "game.favorite",
                ))

            child_messages = [
                str(item.get("content", "")).strip()
                for item in history_entries
                if isinstance(item, dict) and item.get("role") == "child"
                and str(item.get("content", "")).strip()
            ]
            if child_messages:
                average = sum(len(text) for text in child_messages) / len(child_messages)
                questions = sum(
                    1 for text in child_messages
                    if any(mark in text for mark in ("?", "？", "为什么", "怎么", "什么"))
                )
                style = "更常用简短表达" if average <= 12 else "更常用完整句子表达"
                if questions / len(child_messages) >= 0.3:
                    style += "，也喜欢通过提问探索"
                self._upsert_candidate(payload, self._candidate(
                    "conversation_style",
                    "聊天习惯",
                    "根据最近{}次表达，孩子{}".format(len(child_messages), style),
                    "conversation.statistics",
                ))
            payload["summaries"] = payload["summaries"][-40:]
            self._save(payload)
            return list(payload["summaries"])

    @classmethod
    def _profile_item(cls, item):
        if not isinstance(item, str):
            return False
        text = item.strip()
        return len(text) >= 2 and text not in cls.PROFILE_FILLER_WORDS

    def load(self):
        return list(self._payload()["summaries"])

    def recent(self, limit=40):
        return list(reversed(self.load()))[:max(0, int(limit))]

    def delete(self, summary_id):
        target = str(summary_id).strip()
        with _exclusive_path_lock(self.path):
            payload = self._payload()
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
            if fingerprint and fingerprint not in payload["dismissed_fingerprints"]:
                payload["dismissed_fingerprints"].append(fingerprint)
            payload["dismissed_fingerprints"] = payload["dismissed_fingerprints"][-100:]
            self._save(payload)
            return True


def load_json_object(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


@contextmanager
def _exclusive_path_lock(path, timeout_seconds=3.0, stale_seconds=30.0):
    """Serialize summary transactions shared with the voice companion."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    descriptor = None
    while descriptor is None:
        try:
            descriptor = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(descriptor, "{}\n".format(os.getpid()).encode("ascii"))
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > stale_seconds:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise OSError("Timed out waiting for summary lock: {}".format(lock_path))
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
