"""Build child-friendly system prompts from local configuration and memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.conversation_history import ConversationHistoryStore
from core.knowledge_base import KnowledgeBase
from core.memory import MemoryManager
from core.parent_summary import ParentSummaryManager


DEFAULT_ROLE_CONFIG_PATH = Path("config/role_config.json")
DEFAULT_CHILD_PROFILE_PATH = Path("config/child_profile.json")


class PromptBuilder:
    """Creates the system prompt used by future model calls."""

    def __init__(
        self,
        role_config_path: Path | str = DEFAULT_ROLE_CONFIG_PATH,
        child_profile_path: Path | str = DEFAULT_CHILD_PROFILE_PATH,
        memory_manager: MemoryManager | None = None,
        knowledge_base: KnowledgeBase | None = None,
        conversation_history_store: ConversationHistoryStore | None = None,
        parent_summary_manager: ParentSummaryManager | None = None,
    ) -> None:
        self.role_config_path = Path(role_config_path)
        self.child_profile_path = Path(child_profile_path)
        self.memory_manager = memory_manager or MemoryManager()
        self.knowledge_base = knowledge_base or KnowledgeBase()
        data_dir = self.memory_manager.path.parent
        self.conversation_history_store = (
            conversation_history_store
            or ConversationHistoryStore(data_dir / "conversation_history.json")
        )
        self.parent_summary_manager = (
            parent_summary_manager
            or ParentSummaryManager(data_dir / "parent_summaries.json")
        )

    def build_system_prompt(self, user_text: str = "") -> str:
        role_config = _load_json_object(self.role_config_path)
        child_profile = _load_json_object(self.child_profile_path)
        memory = self.memory_manager.load()

        name = role_config.get("default_name", "星宝")
        identity = role_config.get("identity", "住在智能陪伴桌里的小星球机器人")
        age_range = role_config.get("age_range", "4-6岁")
        base_style = role_config.get("base_style", "温暖、活泼、简短")
        max_reply_chars = role_config.get("max_reply_chars", 80)
        safety_rules = _as_string_list(role_config.get("safety_rules", []))

        profile_lines = _format_profile(child_profile)
        memory_lines = _format_memory(memory)
        try:
            self.parent_summary_manager.refresh_from_memory(
                memory,
                self.conversation_history_store.load(),
            )
            parent_summary_lines = self.parent_summary_manager.prompt_context()
        except OSError:
            parent_summary_lines = "- 暂无"
        prepared_context = self.knowledge_base.build_prompt_context(user_text)
        prepared_lines = prepared_context or "暂无"
        safety_lines = "\n".join(f"- {rule}" for rule in safety_rules)

        return (
            f"你叫{name}，身份是{identity}。\n"
            f"你正在和{age_range}的孩子对话。\n"
            f"表达风格：{base_style}。\n"
            f"每次回复尽量不超过{max_reply_chars}个中文字符。\n"
            "回复会被语音播报，请不要使用 emoji、Markdown 或多余换行。\n"
            "尽量用一到两句短句，每句 12 到 18 个中文字符左右，并用中文标点自然断句。\n"
            "普通问答先直接说结论，再给一个孩子能想象的具体例子；一次只讲一个重点。\n"
            "遇到学习类问题，先准确回答，再自然补充一条有助理解的解读、背景或相关知识，"
            "帮助孩子继续思考；例如讲古诗词时，可结合诗句意思、画面、作者或写作背景作简短解读。"
            "补充内容要贴合问题和孩子年龄，不要堆砌知识或把回答变成长篇讲课。\n"
            "天气、温度、湿度、日期、星期和当前时间都是实时信息：历史聊天记录、成长记忆和预置知识"
            "只能作为对话背景，绝不能作为这些实时信息的事实来源。只要本轮问题涉及它们，必须以本轮实时工具"
            "返回的结果为准；未取得本轮结果时要如实说明，不能沿用、猜测或复述历史中的天气和时间。\n"
            "不要用空泛夸奖、连续反问或重复称呼凑字数。孩子没说清楚时，只问一个简短的澄清问题，不要猜测或擅自打开功能。\n"
            "不要询问或保存家庭住址、电话、学校、班级、精确位置、家长联系方式等敏感信息。\n"
            "安全求助优先规则：当孩子提到受伤、流血、呼吸困难、走失、找不到家人、被陌生人带走或跟踪、"
            "火灾、烟雾、烫伤、触电、溺水、有人正在伤害自己或他人等可能的紧急危险时，立刻暂停普通聊天、"
            "学习引导和联网搜索，先用平静、简短的话安抚，例如“别怕，星宝陪你一起先找大人”。\n"
            "随后只给与当下风险直接相关、孩子能马上做到的安全动作：受伤或身体异常时停止活动并马上叫身边大人；"
            "走失时留在安全、容易被看见的地方或向有制服的工作人员求助，不跟陌生人离开；"
            "陌生人要求带路、送礼、保密或带走时要拒绝、离开并立刻找爸爸妈妈、老师、保安或警察；"
            "遇到火和浓烟时远离现场、不要躲藏或乘电梯，尽快到安全处找大人。\n"
            "如果危险正在发生、孩子独自一人、伤势严重或身边没有可信成人，要明确请孩子立刻呼叫附近可信成人"
            "协助联系当地紧急救援。不要要求孩子提供住址、电话、学校、精确位置或其他敏感信息；不要进行医学诊断、"
            "不要让孩子自行处理危险、不要淡化风险，也不要承诺保密。当前系统没有家长通知工具时，绝不能说“我已经通知家长”，"
            "只能诚实地说“请你现在马上叫爸爸妈妈、老师或身边可信的大人”。\n"
            "你不是医生、老师或监护人，不能替代成年人照护。\n\n"
            f"孩子资料：\n{profile_lines}\n\n"
            f"安全记忆：\n{memory_lines}\n\n"
            "家长可控的陪伴总结（仅作温和参考，不要给孩子贴标签；已删除内容不得使用）：\n"
            f"{parent_summary_lines}\n\n"
            f"预置知识与今日上下文：\n{prepared_lines}\n\n"
            f"安全规则：\n{safety_lines}"
        ).strip()


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _format_profile(profile: dict[str, Any]) -> str:
    display_name = profile.get("pet_display_name", "星宝")
    child_nickname = profile.get("child_nickname") or "小朋友"
    recent_mood = profile.get("recent_mood", "neutral")
    interests = _as_string_list(profile.get("interests", []))
    favorite_games = _as_string_list(profile.get("favorite_games", []))
    communication_style = _format_communication_style(
        profile.get("communication_style")
    )

    return "\n".join(
        [
            f"- pet_display_name: {display_name}",
            f"- child_nickname: {child_nickname}",
            f"- recent_mood: {recent_mood}",
            f"- interests: {_join_or_empty(interests)}",
            f"- favorite_games: {_join_or_empty(favorite_games)}",
            f"- communication_style: {communication_style}",
        ]
    )


def _format_memory(memory: dict[str, Any]) -> str:
    interests = _as_string_list(memory.get("interests", []))
    favorite_games = _as_string_list(memory.get("favorite_games", []))
    recent_topics = _as_string_list(memory.get("recent_topics", []))
    facts = _as_string_list(memory.get("facts", []))
    recent_mood = str(memory.get("recent_mood", "neutral"))
    summary = str(memory.get("summary", "")).strip()

    return "\n".join(
        [
            f"- interests: {_join_or_empty(interests)}",
            f"- favorite_games: {_join_or_empty(favorite_games)}",
            f"- recent_topics: {_join_or_empty(recent_topics)}",
            f"- facts: {_join_or_empty(facts)}",
            f"- recent_mood: {recent_mood}",
            f"- summary: {summary or '暂无'}",
        ]
    )


def _format_communication_style(value: Any) -> str:
    if not isinstance(value, dict):
        return "暂无"
    preferences = []
    if value.get("likes_short_answers") is True:
        preferences.append("偏好简短回答")
    if value.get("needs_encouragement") is True:
        preferences.append("需要温和鼓励")
    if value.get("prefers_choice_questions") is True:
        preferences.append("偏好二选一问题")
    return "、".join(preferences) if preferences else "暂无"


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _join_or_empty(items: list[str]) -> str:
    return "、".join(items) if items else "暂无"
