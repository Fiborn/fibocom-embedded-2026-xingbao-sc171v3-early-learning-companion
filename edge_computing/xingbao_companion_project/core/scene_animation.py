"""Validated scene-selection helpers shared by voice and touch UI paths."""

from __future__ import annotations

import re
from datetime import datetime, timedelta


SCENE_CATALOG = {
    1: "打招呼",
    2: "开心跳跃",
    3: "比心",
    4: "得意墨镜",
    5: "思考疑问",
    6: "生气",
    7: "大哭",
    8: "睡觉",
    9: "电脑工作",
    10: "学习看书",
    11: "听音乐",
    12: "吃面条",
    13: "喝奶茶",
    14: "打篮球",
    15: "跑步",
    16: "举重健身",
    17: "冲浪",
    18: "沙滩度假",
    19: "雨天撑伞",
    20: "堆雪人",
    21: "游泳戏水",
    22: "晚安睡觉",
    23: "加油打气",
    24: "太空宇航员",
    25: "机械臂互动",
    26: "爱心互动",
    27: "认真倾听",
}

_SCENE_MARKER = re.compile(r"\[\[(?:XINGBAO_SCENE:)?(\d{1,2})\]\]")
_STREAM_MARKER_BUFFER_CHARS = len("[[XINGBAO_SCENE:27]]")


def is_valid_scene_id(value: object, *, allow_default: bool = True) -> bool:
    """Return whether ``value`` is a protocol-safe scene identifier."""
    if type(value) is not int:
        return False
    return value in SCENE_CATALOG or (allow_default and value == 0)


def extract_scene_marker(text: str) -> tuple[str, int]:
    """Remove one valid final scene marker and return its constrained ID."""
    raw = str(text or "")
    matches = list(_SCENE_MARKER.finditer(raw))
    clean = _SCENE_MARKER.sub("", raw).strip()
    if len(matches) != 1:
        return clean, 0
    scene_id = int(matches[0].group(1))
    return clean, scene_id if is_valid_scene_id(scene_id, allow_default=False) else 0


class SceneMarkerStreamFilter:
    """Hold the response prefix until its hidden scene marker is available."""

    def __init__(self) -> None:
        self._prefix = ""
        self._finished = False
        self.scene_id = 0
        self.scene_decided = False

    def feed(self, text: str) -> str:
        if self._finished:
            return ""
        if self.scene_decided:
            return str(text or "")
        self._prefix += str(text or "")
        match = _SCENE_MARKER.match(self._prefix)
        if match is not None:
            candidate = int(match.group(1))
            self.scene_id = candidate if is_valid_scene_id(candidate, allow_default=False) else 0
            self.scene_decided = True
            return self._prefix[match.end():]
        if len(self._prefix) <= _STREAM_MARKER_BUFFER_CHARS:
            return ""
        self.scene_decided = True
        return self._prefix

    def finish(self) -> tuple[str, int]:
        if self._finished:
            return "", 0
        self._finished = True
        if self.scene_decided:
            return "", self.scene_id
        self.scene_decided = True
        return self._prefix, 0


class SceneTurnSelector:
    """Preserve a scene for repeated child input during one conversation."""

    def __init__(self) -> None:
        self._last_user_text = ""
        self._last_scene_id = 0

    def select(self, user_text: str, response_text: str) -> tuple[str, int]:
        clean_text, scene_id = extract_scene_marker(response_text)
        normalized_user_text = " ".join(str(user_text or "").split())
        if normalized_user_text and normalized_user_text == self._last_user_text:
            scene_id = self._last_scene_id
        self._last_user_text = normalized_user_text
        if scene_id:
            self._last_scene_id = scene_id
        return clean_text, scene_id


class ScenePriorityController:
    """Track wake and late-night idle transitions without UI dependencies."""

    def __init__(self, *, night_hour: int = 23, night_idle_minutes: int = 10) -> None:
        self.night_hour = int(night_hour)
        self.night_idle_delay = timedelta(minutes=max(1, int(night_idle_minutes)))
        self._last_wake_at: datetime | None = None
        self._session_end_at: datetime | None = None

    def on_wake(self, when: datetime) -> int:
        self._last_wake_at = when
        self._session_end_at = None
        return 1

    def on_session_end(self, when: datetime) -> int:
        self._session_end_at = when
        return 0

    def poll_idle(self, when: datetime) -> int:
        if when.hour < self.night_hour or self._session_end_at is None:
            return 0
        if when - self._session_end_at < self.night_idle_delay:
            return 0
        if self._last_wake_at is not None and self._last_wake_at > self._session_end_at:
            return 0
        return 22


def scene_catalog_prompt() -> str:
    """Return the strict child-safe scene-selection instruction for the LLM."""
    options = "；".join("{}={}".format(scene_id, name) for scene_id, name in SCENE_CATALOG.items())
    return (
        "触控界面场景选择：每轮回答开头必须先单独输出一个标记"
        "[[XINGBAO_SCENE:n]]，n 只能是0到27。0表示没有合适场景。"
        "积极按本轮语义选择：{}。天气查询规则：已取得天气结果时不得选5；"
        "雨或雷阵雨选19，下雪选20；晴、阴、云或其他已知天气选0或更贴切的非5场景。"
        "仅查询失败、超出预报范围或结果不确定时才可选5。"
        "当用户难过或生气时必须选3（比心）来安慰，不得选6或7；"
        "6和7仅用于星宝自身的夸张表演、故事角色，或用户明确要求观看该表情。"
        "25是机械臂互动：当本轮要握手、握握手、击掌或击击掌时必须选25；"
        "26是爱心互动，适合表达关爱、喜欢或温暖互动；27是认真倾听，适合专心听用户"
        "说话、安静陪伴或认真了解用户想法的语境。"
        "标记只供系统读取，不能向孩子解释或提及。".format(options)
    )
