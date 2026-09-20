"""Rule-based mapping from child speech to fixed game status commands."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GameStatusQuery:
    """A fixed game command resolved from a child utterance."""

    intent: str
    reason: str
    confidence: float = 0.9

    def as_command(self, user_text: str, *, game_id: str = "current_game") -> dict[str, object]:
        return {
            "type": "game_command",
            "game_id": game_id,
            "intent": self.intent,
            "user_text": user_text,
            "context": {"source": "voice"},
        }


def resolve_game_status_query(text: str) -> GameStatusQuery | None:
    """Resolve common Chinese game-status questions to fixed game_command intents."""
    compact = _compact(text)
    if not compact:
        return None

    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("get_stars", STAR_KEYWORDS),
        ("get_score", SCORE_KEYWORDS),
        ("get_progress", PROGRESS_KEYWORDS),
        ("get_remaining", REMAINING_KEYWORDS),
        ("get_round", ROUND_KEYWORDS),
        ("get_goal", GOAL_KEYWORDS),
        ("get_rule", RULE_KEYWORDS),
        ("get_hint", HINT_KEYWORDS),
        ("repeat_prompt", REPEAT_KEYWORDS),
        ("get_current_game", CURRENT_GAME_KEYWORDS),
        ("get_status", STATUS_KEYWORDS),
        ("get_level", LEVEL_KEYWORDS),
        ("get_energy", ENERGY_KEYWORDS),
        ("get_correct", CORRECT_KEYWORDS),
        ("get_errors", ERROR_KEYWORDS),
        ("get_attempts", ATTEMPT_KEYWORDS),
    )
    for intent, keywords in checks:
        if any(keyword in compact for keyword in keywords):
            return GameStatusQuery(intent=intent, reason=f"keyword:{intent}")
    return None


def _compact(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;“”\"'（）()]+", "", text or "")


STAR_KEYWORDS = (
    "几颗星",
    "多少颗星",
    "几个星",
    "多少星",
    "我有几颗星",
    "我有多少星",
    "有几颗星",
    "现在有几颗",
    "现在有多少颗",
    "拿了几颗",
    "拿到几颗",
    "星星多少",
    "星星有多少",
    "我的星星",
    "目前几星",
    "当前几星",
    "得了几颗",
    "获得几颗",
)
SCORE_KEYWORDS = (
    "多少分",
    "几分",
    "分数",
    "得分",
    "当前分",
    "现在分",
    "现在多少分",
    "我得了多少分",
    "我有多少分",
    "拿了多少分",
    "成绩",
)
PROGRESS_KEYWORDS = (
    "进度",
    "做到哪里",
    "玩到哪里",
    "进行到哪里",
    "现在到哪",
    "做了多少",
    "完成多少",
    "玩了多少",
    "过了几关",
)
REMAINING_KEYWORDS = (
    "还剩几题",
    "还剩多少题",
    "剩几题",
    "剩多少题",
    "还有几题",
    "还有多少题",
    "还剩几轮",
    "还剩多少轮",
    "剩几轮",
    "剩多少轮",
    "还有几轮",
    "还有多少轮",
    "剩下几题",
    "剩下多少题",
    "还要做几",
    "还要做多少",
    "还差几",
    "还差多少",
)
ROUND_KEYWORDS = (
    "第几轮",
    "第几关",
    "第几题",
    "第几局",
    "第几步",
    "现在几轮",
    "现在几关",
    "现在第几",
    "当前轮",
    "当前关",
    "当前第几",
)
GOAL_KEYWORDS = (
    "目标是什么",
    "要做什么",
    "现在做什么",
    "下一步做什么",
    "任务是什么",
    "该干嘛",
    "现在该干嘛",
    "接下来干嘛",
    "找什么",
    "选什么",
    "应该选什么",
    "点什么",
    "应该点哪个",
    "这题是什么",
)
RULE_KEYWORDS = (
    "怎么玩",
    "规则",
    "玩法",
    "怎么操作",
    "怎么赢",
    "怎么才算赢",
    "要怎么玩",
)
HINT_KEYWORDS = (
    "提示",
    "帮帮我",
    "帮助我",
    "我不会",
    "不会做",
    "不知道选",
    "不知道点哪个",
    "不知道怎么办",
    "给点线索",
    "线索",
)
REPEAT_KEYWORDS = (
    "再说一遍",
    "重复一遍",
    "刚才说什么",
    "没听清",
    "再讲一次",
    "再读一次",
    "再来一遍",
)
CURRENT_GAME_KEYWORDS = (
    "现在什么游戏",
    "当前什么游戏",
    "玩的什么",
    "玩的是啥",
    "正在玩什么",
    "当前游戏",
    "现在游戏",
    "这是什么游戏",
    "游戏名字",
)
STATUS_KEYWORDS = (
    "现在怎么样",
    "当前状态",
    "游戏状态",
    "我现在怎么样",
    "状态怎么样",
    "情况怎么样",
    "现在情况",
    "我玩得怎么样",
)
LEVEL_KEYWORDS = (
    "几级",
    "等级",
    "级别",
    "星宝等级",
    "现在几级",
    "当前等级",
)
ENERGY_KEYWORDS = (
    "能量",
    "体力",
    "还有多少能量",
    "还有多少体力",
    "现在多少能量",
    "能量多少",
)
CORRECT_KEYWORDS = (
    "答对几个",
    "对了几个",
    "答对几题",
    "做对几题",
    "成功几次",
    "做对几个",
)
ERROR_KEYWORDS = (
    "错了几个",
    "错几次",
    "错误几次",
    "答错几个",
    "答错几题",
    "做错几题",
    "失败几次",
)
ATTEMPT_KEYWORDS = (
    "试了几次",
    "尝试几次",
    "一共点了几次",
    "点了几次",
    "一共试了几次",
    "已经试了几次",
)
