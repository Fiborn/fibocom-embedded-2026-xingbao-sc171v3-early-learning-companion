"""Voice command parsing for Xingbao's color block mini game."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VoiceIntent = Literal["play", "pass", "hint", "unknown"]


@dataclass(frozen=True)
class ColorBlockVoiceCommand:
    """A parsed voice command for the color block game."""

    intent: VoiceIntent
    color_id: str | None = None
    lane_id: str | None = None
    message: str = ""


COLOR_ALIASES = {
    "red": ("红", "红色", "勇气", "红色勇气", "绾㈣壊", "鍕囨皵", "缁俱垼", "red"),
    "blue": ("蓝", "蓝色", "守护", "蓝色守护", "钃濊壊", "瀹堟姢", "blue"),
    "yellow": ("黄", "黄色", "灵感", "黄色灵感", "榛勮壊", "鐏垫劅", "yellow"),
    "green": ("绿", "绿色", "修复", "绿色修复", "缁胯壊", "淇", "green"),
    "purple": ("紫", "紫色", "惊喜", "紫色惊喜", "绱壊", "鎯婂枩", "purple"),
}

LANE_ALIASES = {
    "star_lane": ("星光", "星光线", "左边", "左侧", "左上", "左", "鏄熷厜", "鏄熷厜绾", "槦鍏夌嚎", "閸忓", "鍤"),
    "guard_lane": ("守护", "守护线", "右边", "右侧", "右下", "右", "瀹堟姢", "瀹堟姢绾"),
}

PASS_ALIASES = (
    "停手",
    "不出",
    "结束",
    "收手",
    "跳过",
    "本回合不出",
    "鍋滄墜",
    "仠鎵",
    "涓嶅嚭",
    "缁撴潫",
    "鏀舵墜",
    "璺宠繃",
)
HINT_ALIASES = (
    "提示",
    "帮我",
    "建议",
    "怎么放",
    "放哪",
    "哪边",
    "想一想",
    "鎻愮ず",
    "甯垜",
    "寤鸿",
    "鏀惧摢",
    "鍝竟",
)


def parse_color_block_voice_command(text: str) -> ColorBlockVoiceCommand:
    """Parse a short Chinese voice command into a game action."""
    normalized = text.strip().lower().replace(" ", "")
    if not normalized:
        return ColorBlockVoiceCommand("unknown", message="我还没有听清楚。")

    if any(alias.lower() in normalized for alias in PASS_ALIASES):
        return ColorBlockVoiceCommand("pass", message="收到，本回合停手。")

    if any(alias.lower() in normalized for alias in HINT_ALIASES):
        return ColorBlockVoiceCommand("hint", message="我来帮你看看局势。")

    color_id = _find_alias(normalized, COLOR_ALIASES)
    lane_id = _find_alias(normalized, LANE_ALIASES)
    if color_id and lane_id:
        return ColorBlockVoiceCommand(
            "play",
            color_id=color_id,
            lane_id=lane_id,
            message="听到了，准备放置色块。",
        )
    if color_id:
        return ColorBlockVoiceCommand(
            "unknown",
            color_id=color_id,
            message="我听到了颜色，还需要知道放到星光线还是守护线。鏄熷厜绾",
        )
    if lane_id:
        return ColorBlockVoiceCommand(
            "unknown",
            lane_id=lane_id,
            message="我听到了战线，还需要知道是哪一个颜色。",
        )
    return ColorBlockVoiceCommand("unknown", message="可以说：红色放星光线，或者我想停手。")


def _find_alias(text: str, aliases: dict[str, tuple[str, ...]]) -> str | None:
    for key, options in aliases.items():
        if any(option.lower() in text for option in options):
            return key
    return None
