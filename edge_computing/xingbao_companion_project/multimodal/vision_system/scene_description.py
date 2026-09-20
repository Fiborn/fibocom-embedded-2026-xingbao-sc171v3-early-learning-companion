"""Optional, privacy-scoped multi-frame Kimi scene description.

This is adapted from the 2026-08-15 vision release.  It never blocks local
vision, sends no frames without an explicit ``MOONSHOT_API_KEY``, and returns
only a concise description of visible actions.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np

# Placeholder only; credentials must come from the environment.
DEFAULT_MOONSHOT_API_KEY = "YOUR_MOONSHOT_API_KEY"


@dataclass
class TimedFrame:
    timestamp: float
    frame: np.ndarray


@dataclass
class SceneDescriptionStatus:
    enabled: bool
    state: str = "idle"
    person_present: bool = False
    trigger_source: str = ""
    detection_seconds: float = 0.0
    session_id: int = 0
    pending: bool = False
    description: str = ""
    updated: bool = False
    cooldown_seconds: float = 0.0
    error: str = ""


class KimiSceneClient:
    def __init__(self, api_key: str, *, model: str, base_url: str, timeout: float) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.timeout = max(3.0, float(timeout))

    def describe(self, frames: list[TimedFrame]) -> str:
        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                "这些摄像头画面按时间顺序排列。只描述可观察到的人物动作和直接相关物品，"
                "不要识别身份或推断隐私属性。动作不清楚时明确说明不确定。"
                "只返回 JSON：{\"description\":\"一条简短中文描述\"}。"
            ),
        }]
        for item in frames:
            content.append({"type": "image_url", "image_url": {"url": self._image_url(item.frame)}})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 160,
        }
        if self.model.startswith("kimi-k2"):
            payload["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError("Kimi HTTP {}".format(exc.code)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Kimi network error: {}".format(exc.reason)) from exc
        try:
            content_value = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Kimi response shape is invalid") from exc
        if isinstance(content_value, list):
            content_value = "".join(str(x.get("text", "")) for x in content_value if isinstance(x, dict))
        text = str(content_value).strip().strip("`")
        try:
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
            text = str(parsed.get("description", "")).strip()
        except (ValueError, TypeError):
            pass
        if not text:
            raise RuntimeError("Kimi returned an empty description")
        return text[:500]

    @staticmethod
    def _image_url(frame: np.ndarray) -> str:
        height, width = frame.shape[:2]
        scale = min(1.0, 768.0 / max(height, width))
        if scale < 1.0:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            raise RuntimeError("Could not encode Kimi keyframe")
        return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


class SceneDescriptionController:
    """Collect a short evidence window and make one non-blocking request per presence session."""

    def __init__(self, client: KimiSceneClient, *, confirm_seconds: float = 0.8, cooldown_seconds: float = 60.0) -> None:
        self.client = client
        self.confirm_seconds = max(0.2, float(confirm_seconds))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.frames: deque[TimedFrame] = deque(maxlen=32)
        self.present_since: float | None = None
        self.last_request = 0.0
        self.session_id = 0
        self.requested = False
        self.status = SceneDescriptionStatus(enabled=True)
        self._lock = threading.Lock()

    def set_enabled(self, enabled: bool) -> bool:
        """Enable or disable Kimi requests without stopping local vision."""
        enabled = bool(enabled)
        with self._lock:
            if self.status.enabled == enabled:
                return False
            self.status.enabled = enabled
            self.frames.clear()
            self.present_since = None
            self.requested = False
            # A request already sent to Kimi cannot be cancelled safely, so
            # invalidate its session and discard its eventual result.
            self.session_id += 1
            self.status.session_id = self.session_id
            self.status.pending = False
            self.status.person_present = False
            self.status.detection_seconds = 0.0
            self.status.description = ""
            self.status.updated = False
            self.status.error = ""
            self.status.state = "idle" if enabled else "disabled"
            return True

    def update(self, frame: np.ndarray, *, person_present: bool) -> SceneDescriptionStatus:
        now = time.monotonic()
        with self._lock:
            if not self.status.enabled:
                self.status.state = "disabled"
                return self._snapshot_and_clear_update()
            self.frames.append(TimedFrame(now, frame.copy()))
            self.status.person_present = bool(person_present)
            self.status.cooldown_seconds = max(0.0, self.cooldown_seconds - (now - self.last_request))
            if not person_present:
                self.present_since = None
                self.requested = False
                self.status.state = "idle" if not self.status.pending else "pending"
                return self._snapshot_and_clear_update()
            if self.present_since is None:
                self.present_since = now
                self.session_id += 1
                self.status.description = ""
                self.status.error = ""
            self.status.session_id = self.session_id
            self.status.detection_seconds = now - self.present_since
            if not self.requested and not self.status.pending and self.status.detection_seconds >= self.confirm_seconds and self.status.cooldown_seconds <= 0:
                self.requested = True
                self.status.pending = True
                self.status.state = "pending"
                keyframes = self._keyframes()
                threading.Thread(target=self._request, args=(keyframes, self.session_id), daemon=True, name="kimi-scene-request").start()
            elif not self.status.pending:
                self.status.state = "candidate"
            return self._snapshot_and_clear_update()

    def _snapshot_and_clear_update(self) -> SceneDescriptionStatus:
        """Return a one-frame update flag so consumers can log each result once."""
        snapshot = SceneDescriptionStatus(**asdict(self.status))
        self.status.updated = False
        return snapshot

    def _keyframes(self) -> list[TimedFrame]:
        entries = list(self.frames)
        if len(entries) <= 4:
            return entries
        return [entries[round(index * (len(entries) - 1) / 3)] for index in range(4)]

    def _request(self, frames: list[TimedFrame], session_id: int) -> None:
        try:
            description = self.client.describe(frames)
        except Exception as exc:  # network errors must never stop local vision
            with self._lock:
                if self.status.enabled and self.status.session_id == session_id:
                    self.status.pending = False
                    self.status.state = "error"
                    self.status.error = str(exc)[:200]
            return
        with self._lock:
            if self.status.enabled and self.status.session_id == session_id:
                self.last_request = time.monotonic()
                self.status.pending = False
                self.status.description = description
                self.status.updated = True
                self.status.state = "ready"
