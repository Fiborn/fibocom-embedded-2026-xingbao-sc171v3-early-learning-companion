"""Rule-based intent routing for computer-side Xingbao coordination."""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.game_status_query import resolve_game_status_query
from core.kids_visual_tools_bridge import visual_tool_target


@dataclass(frozen=True)
class IntentResult:
    """A normalized intent detected from child voice or touch text."""

    intent: str
    target: str = ""
    confidence: float = 0.0
    source_text: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "intent": self.intent,
            "confidence": self.confidence,
            "source_text": self.source_text,
        }
        if self.target:
            result["target"] = self.target
        if self.reason:
            result["reason"] = self.reason
        return result


class IntentRouter:
    """Maps child-friendly utterances to high-level coordination intents."""

    def route(self, text: str) -> IntentResult:
        source_text = (text or "").strip()
        compact = _compact(source_text)
        if not compact:
            return IntentResult(
                intent="unknown",
                confidence=0.0,
                source_text=source_text,
                reason="empty_text",
            )

        status_query = resolve_game_status_query(source_text)
        if status_query is not None:
            return IntentResult(
                intent="game_status_query",
                target=status_query.intent,
                confidence=status_query.confidence,
                source_text=source_text,
                reason=status_query.reason,
            )
        if _looks_like_greeting(compact):
            return IntentResult(
                intent="greeting",
                confidence=0.9,
                source_text=source_text,
                reason="greeting_keyword",
            )
        visual_target = _visual_tool_launch_target(compact)
        if visual_target:
            return IntentResult(
                intent="open_tool",
                target=visual_target,
                confidence=0.9,
                source_text=source_text,
                reason="visual_tool_keyword",
            )
        if _looks_like_game_launch_request(compact):
            return IntentResult(
                intent="open_tool",
                target="mini_game_hub",
                confidence=0.92,
                source_text=source_text,
                reason="game_keyword",
            )
        if _looks_like_story_launch_request(compact):
            return IntentResult(
                intent="open_tool",
                target="story_time",
                confidence=0.86,
                source_text=source_text,
                reason="story_keyword",
            )
        if _contains_any(compact, HELP_KEYWORDS):
            return IntentResult(
                intent="ask_help",
                confidence=0.78,
                source_text=source_text,
                reason="help_keyword",
            )
        if _contains_unnegated_keyword(compact, EXIT_KEYWORDS):
            return IntentResult(
                intent="exit_activity",
                confidence=0.82,
                source_text=source_text,
                reason="exit_keyword",
            )
        return IntentResult(
            intent="chat",
            confidence=0.45,
            source_text=source_text,
            reason="fallback_chat",
        )


GAME_DIRECT_REQUESTS = (
    "我要玩游戏",
    "我想玩游戏",
    "想玩游戏",
    "一起玩游戏",
    "来玩游戏",
    "打开游戏",
    "开始游戏",
    "进入游戏",
    "切到游戏",
    "去玩游戏",
    "玩个游戏",
    "玩一下游戏",
    "我要玩小游戏",
    "我想玩小游戏",
    "打开小游戏",
    "开始小游戏",
    "进入小游戏",
    "我要闯关",
    "我想闯关",
)
GAME_SUBJECT_KEYWORDS = (
    "小游戏",
    "闯关",
    "色块",
    "方块",
    "牌阵",
    "找颜色",
    "颜色",
    "色彩",
    "认形状",
    "形状",
    "图形",
    "记忆",
    "数数",
    "数字",
    "英语",
    "英文",
    "挑战",
)
STORY_KEYWORDS = ("故事", "绘本")
LAUNCH_VERBS = ("我要", "我想", "想玩", "打开", "开始", "进入", "切到", "去玩", "来玩", "一起玩")
GAME_LAUNCH_VERBS = (
    "想玩",
    "要玩",
    "打开",
    "开始",
    "进入",
    "切到",
    "去玩",
    "来玩",
    "一起玩",
)
HELP_KEYWORDS = ("帮帮我", "帮助我", "不会", "不懂", "提示")
EXIT_KEYWORDS = ("退出", "不玩了", "结束", "回家", "停一停")
GREETING_KEYWORDS = ("你好", "星宝你好", "星宝好", "嗨星宝", "哈喽星宝", "你好星宝")
VISUAL_TOOLBOX_KEYWORDS = ("百宝箱", "白宝箱", "工具箱", "小工具箱", "可视化工具", "早教工具")
VISUAL_TOOL_KEYWORDS = (
    ("喝水", "water"),
    ("喝奶", "milk_tracker"),
    ("呼吸", "breath"),
    ("放松", "breath"),
    ("心情", "mood"),
    ("情绪安抚", "calm"),
    ("安抚卡", "calm"),
    ("颜色认知", "colors"),
    ("形状认知", "shapes"),
    ("数字认知", "numbers"),
    ("字母", "letters"),
    ("拼音", "letters"),
    ("动物认知", "animals"),
    ("水果蔬菜", "foods"),
    ("食物认知", "foods"),
    ("交通工具", "transport"),
    ("职业认知", "careers"),
    ("绘本翻页", "storybook"),
    ("涂色", "coloring"),
    ("贴纸", "stickers"),
    ("拼图", "puzzle"),
    ("找不同", "spot"),
    ("配对", "matching"),
    ("翻牌", "memory"),
    ("排序", "sorting"),
    ("分类", "classify"),
    ("抽签", "lottery"),
    ("奖励转盘", "wheel"),
    ("转盘", "wheel"),
    ("安全提示", "safety"),
    ("出门准备", "go_out_ready"),
    ("睡前流程", "bedtime_cards"),
    ("早晨流程", "morning_cards"),
    ("星星墙", "stars"),
    ("小星星", "stars"),
)


def _compact(text: str) -> str:
    return re.sub(r"[\s，。！？,.!?\"'（）()]+", "", text)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _visual_tool_launch_target(text: str) -> str:
    if _contains_any(text, VISUAL_TOOLBOX_KEYWORDS):
        return visual_tool_target()
    if not _contains_any(text, LAUNCH_VERBS):
        return ""
    for keyword, slug in VISUAL_TOOL_KEYWORDS:
        if keyword in text:
            try:
                return visual_tool_target(slug)
            except ValueError:
                return ""
    return ""


def _looks_like_game_launch_request(text: str) -> bool:
    if any(phrase in text for phrase in GAME_DIRECT_REQUESTS):
        return True
    return _contains_any(text, GAME_LAUNCH_VERBS) and _contains_any(
        text,
        GAME_SUBJECT_KEYWORDS,
    )


def _looks_like_story_launch_request(text: str) -> bool:
    return _contains_any(text, LAUNCH_VERBS) and _contains_any(text, STORY_KEYWORDS)


def _looks_like_greeting(text: str) -> bool:
    return _contains_any(text, GREETING_KEYWORDS)


def _contains_unnegated_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    negation_prefixes = ("不要", "不想", "不是", "不能", "没有", "还没", "别", "没")
    for keyword in keywords:
        start = 0
        while True:
            index = text.find(keyword, start)
            if index < 0:
                break
            prefix = text[max(0, index - 3) : index]
            if not any(prefix.endswith(item) for item in negation_prefixes):
                return True
            start = index + len(keyword)
    return False
