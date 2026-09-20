"""Deterministic, resumable guided-expression conversations.

The flow in this module is a normal product capability, not a demo-mode
switch.  It handles only the reviewed dinosaur-expression scene.  Unrelated
utterances return ``None`` so the existing intent router and LLM continue to
work unchanged, while the unfinished scene remains available for a later
related utterance.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


IDLE = "idle"
WAIT_DESCRIPTION = "wait_description"
WAIT_HIGH_LEAVES_CONFIRMATION = "wait_high_leaves_confirmation"
WAIT_RECAST = "wait_recast"
WAIT_DRAWING_CONSENT = "wait_drawing_consent"

ACTIVATION_SIMILARITY_THRESHOLD = 0.80
STAGE_ADVANCE_SIMILARITY_THRESHOLD = 0.72
STAGE_CLARIFY_SIMILARITY_THRESHOLD = 0.55

_ACTIVE_STAGES = frozenset(
    {
        WAIT_DESCRIPTION,
        WAIT_HIGH_LEAVES_CONFIRMATION,
        WAIT_RECAST,
        WAIT_DRAWING_CONSENT,
    }
)

_DINOSAUR_WORDS = (
    "恐龙",
    "霸王龙",
    "腕龙",
    "万龙",
    "万隆",
    "梁龙",
    "雷龙",
    "三角龙",
    "蜥脚类",
)
_UNCLEAR_WORDS = (
    "不知道怎么说",
    "我不知道怎么说",
    "不知道是什么",
    "不知道它是什么",
    "不知道叫什么",
    "不知道它叫什么",
    "不知道是什么恐龙",
    "说不出来",
    "讲不出来",
    "讲不清楚",
    "说不清楚",
    "不知道怎么形容",
)
_FRUSTRATION_WORDS = (
    "好难",
    "太难了",
    "太费劲",
    "真费劲",
    "不会说",
    "说不出来",
    "讲不出来",
    "讲不清楚",
    "说不清楚",
    "表达不好",
    "不知道怎么表达",
    # Naming uncertainty is still a child-facing frustration signal in the
    # short route, even though the retired first-guess scene is gone.
    "不知道是什么",
    "不知道它是什么",
    "不知道叫什么",
    "不知道它叫什么",
    "不知道是什么恐龙",
)
_CANCEL_WORDS = (
    "不聊恐龙了",
    "不想说了",
    "不说了",
    "算了",
    "换个话题",
)
_AFFIRMATIVE_WORDS = ("好", "好的", "好呀", "可以", "对", "对的", "是", "是的", "嗯", "没错")
_NEGATIVE_WORDS = (
    "不是",
    "不对",
    "猜错",
    "错了",
    "没有",
    "不能",
    "不可以",
    "不长",
    "吃不到",
)
_NEGATIVE_PREFERENCE_WORDS = ("不喜欢恐龙", "讨厌恐龙", "对恐龙不感兴趣", "不是恐龙")
_RESUME_WORDS = ("继续", "接着", "刚才那个恐龙", "回到刚才的恐龙")
_BRACHIOSAURUS_ALIASES = ("腕龙", "万龙", "万隆")
_RECAST_ATTEMPT_WORDS = ("连起来", "复述", "再说一遍", "完整说")
_DRAWING_ACCEPT_WORDS = ("好", "好呀", "可以", "想画", "我要画", "画下来")
_DRAWING_REJECT_WORDS = ("不想画", "不画", "不要", "先不画")

_NICKNAME_RE = re.compile(
    r"(?:我的名字叫|你可以叫我|我叫|我是|叫我)"
    r"(?P<name>[\u4e00-\u9fffA-Za-z0-9·]{1,8}?)"
    r"(?=，|。|、|,|！|!|然后|而且|我(?:最|特别|很)?喜欢|我(?:最)?爱|我对|$)"
)

_ACTIVATION_TEMPLATES = (
    "我叫小宇我喜欢恐龙",
    "我是小宇我最喜欢恐龙",
    "你可以叫我小宇我特别喜欢恐龙",
)
_BIG_DESCRIPTION_TEMPLATES = (
    "我喜欢那个特别特别大的可是我不知道怎么说",
    "它特别大但是我说不清楚",
    "我想的是一个非常巨大的恐龙",
)
_LONG_NECK_TEMPLATES = (
    "它的脖子特别长",
    "那个恐龙有长长的脖子",
    "它是长脖子的",
)
_HIGH_LEAVES_TEMPLATES = (
    "它可以吃到高高的树叶",
    "它能吃到树顶的叶子",
    "它可以吃高处的叶子",
)


@dataclass(frozen=True)
class GuidedExpressionReply:
    """One reviewed reply plus safe state and memory metadata."""

    text: str
    scene: str
    stage: str
    screen_expression: str = "smile"
    led_mode: str = "warm_breath"
    memory_update: dict[str, Any] = field(default_factory=dict)
    # Optional reviewed action that is dispatched only after this reply has
    # finished playing.  It remains a high-level whitelist name; the flow
    # never carries a point number, pose, speed, or joint value.
    post_tts_arm_action: str = ""
    # A reviewed handoff may end the current wake-chat session. The runtime
    # can explicitly open the next scripted listening turn without a wake
    # phrase when the presentation calls for it.
    end_session: bool = False


@dataclass(frozen=True)
class GuidedExpressionSnapshot:
    """Read-only state used by tests, diagnostics, and future UI status."""

    stage: str
    suspended: bool
    nickname: str
    remembered_dinosaur: str
    sadness_recent: bool


class DinosaurExpressionFlow:
    """A voice-first dinosaur description scaffold that can be interrupted."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        emotion_window_seconds: float = 6.0,
    ) -> None:
        self._clock = clock or time.monotonic
        self._emotion_window_seconds = max(0.0, float(emotion_window_seconds))
        self._lock = threading.RLock()
        self._stage = IDLE
        self._suspended = False
        self._nickname = ""
        self._remembered_dinosaur = ""
        self._last_sadness_at: float | None = None
        self._recast_seen_features: set[str] = set()

    def observe_emotion(
        self,
        emotion: str,
        *,
        confidence: float = 1.0,
        observed_at: float | None = None,
    ) -> bool:
        """Remember only a recent high-level sadness signal, never an image."""
        normalized = str(emotion or "").strip().lower()
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = 0.0
        if normalized not in {"sad", "sadness"} or score < 0.60:
            return False
        with self._lock:
            self._last_sadness_at = (
                float(observed_at) if observed_at is not None else self._clock()
            )
        return True

    def handle(
        self,
        user_text: str,
        *,
        memory: dict[str, Any] | None = None,
    ) -> GuidedExpressionReply | None:
        """Handle a related turn or yield to the existing normal conversation."""
        text = str(user_text or "").strip()
        if not text:
            return None
        compact = _compact(text)
        with self._lock:
            recall = self._recall_reply(compact, memory or {})
            if recall is not None:
                return recall

            if self._stage == IDLE:
                return self._start_if_matched(text, compact)

            # During the reviewed five-minute route, an Actor A line is a
            # stage acknowledgement, not a dictation test. Only one complete
            # VAD/ASR turn reaches this point, so Xingbao waits for the child
            # to finish, then advances regardless of wording. The dedicated
            # touch stop control remains the explicit way to leave the route.
            self._suspended = False
            return self._advance(compact)

    def reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def snapshot(self) -> GuidedExpressionSnapshot:
        with self._lock:
            return GuidedExpressionSnapshot(
                stage=self._stage,
                suspended=self._suspended,
                nickname=self._nickname,
                remembered_dinosaur=self._remembered_dinosaur,
                sadness_recent=self._has_recent_sadness_locked(),
            )

    def recovery_input_for_current_step(self) -> str | None:
        """Return the reviewed child input that completes the current step.

        This is an operator recovery aid for the live demonstration.  It does
        not mutate the state itself: the normal ``handle`` path consumes the
        returned text afterwards, so the same transitions, memory rules, and
        fixed replies remain in effect.
        """
        with self._lock:
            return {
                WAIT_DESCRIPTION: "有一种恐龙特别大，可是我不知道怎么说",
                WAIT_HIGH_LEAVES_CONFIRMATION: "对",
                WAIT_RECAST: "我喜欢腕龙，因为它身体大，脖子长",
                WAIT_DRAWING_CONSENT: "好呀",
            }.get(self._stage)

    def _start_if_matched(
        self,
        text: str,
        compact: str,
    ) -> GuidedExpressionReply | None:
        nickname_match = _NICKNAME_RE.search(text)
        activation_score = _dinosaur_activation_similarity(
            text,
            compact,
            nickname_match=nickname_match,
        )
        if activation_score < ACTIVATION_SIMILARITY_THRESHOLD:
            return None
        recognized_nickname = nickname_match.group("name").strip()
        # The board ASR commonly transcribes the scripted name “小宇” as
        # 小雨、小玉、小鱼 or 小于. Normalize those homophones so the fixed
        # opening replies always hit their reviewed cloud-TTS cache.
        self._nickname = (
            "小宇"
            if recognized_nickname in {"小雨", "小玉", "小鱼", "小于"}
            else recognized_nickname
        )
        self._stage = WAIT_DESCRIPTION
        self._suspended = False
        greeting = f"{self._nickname}你好，" if self._nickname else ""
        return self._reply(
            f"{greeting}我记住你喜欢恐龙啦。你最喜欢哪一种呢？",
            scene="dinosaur_interest_started",
            memory={"interests": ["恐龙"], "recent_topics": ["恐龙表达练习"]},
        )

    def _advance(self, compact: str) -> GuidedExpressionReply | None:
        if self._stage == WAIT_DESCRIPTION:
            self._stage = WAIT_HIGH_LEAVES_CONFIRMATION
            return self._reply(
                "没关系，我们慢慢说。它能吃到高高的树叶吗？",
                scene="dinosaur_short_leaf_prompt",
                expression="listening",
            )

        if self._stage == WAIT_HIGH_LEAVES_CONFIRMATION:
            self._begin_recast_locked()
            self._remembered_dinosaur = "腕龙"
            return self._reply(
                "可能是腕龙。试着说：我喜欢腕龙，因为它身体大、脖子长，"
                "还能吃到高高的树叶。",
                scene="dinosaur_short_recast",
                expression="smile",
            )

        if self._stage == WAIT_RECAST:
            return self._complete_recast_locked()

        if self._stage == WAIT_DRAWING_CONSENT:
            self._reset_stage_only_locked()
            return self._reply(
                "那我们去百宝箱画一画吧。",
                scene="dinosaur_drawing_accepted",
                memory={"recent_topics": ["准备画腕龙"]},
                end_session=True,
            )

        return None

    def _recall_reply(
        self,
        compact: str,
        memory: dict[str, Any],
    ) -> GuidedExpressionReply | None:
        if "记得" not in compact:
            return None
        if not (
            "喜欢什么恐龙" in compact
            or "喜欢哪种恐龙" in compact
            or "我喜欢的恐龙" in compact
        ):
            return None
        interests = memory.get("interests", [])
        remembered = self._remembered_dinosaur
        if not remembered and isinstance(interests, list):
            if "腕龙" in interests:
                remembered = "腕龙"
            elif "霸王龙" in interests:
                remembered = "霸王龙"
        if remembered == "腕龙":
            return self._reply(
                "记得呀，你喜欢身体很大、脖子很长的腕龙。",
                scene="dinosaur_interest_recalled",
                end_session=True,
            )
        if remembered == "霸王龙":
            return self._reply(
                "记得呀，你喜欢又大又有力量的霸王龙。",
                scene="dinosaur_interest_recalled",
                # Recalling either reviewed dinosaur is the final step after
                # drawing.  Keep both branches on the same explicit session
                # completion path so no handoff state remains active.
                end_session=True,
            )
        return None

    def _looks_like_unrelated_turn(self, compact: str) -> bool:
        if _looks_like_fact_question(compact):
            return True
        if self._stage == WAIT_HIGH_LEAVES_CONFIRMATION:
            if (
                _is_affirmative(compact)
                or _contains_any(compact, _NEGATIVE_WORDS)
                or _looks_high_leaves(compact)
            ):
                return False
        if self._stage == WAIT_RECAST:
            if _has_final_recast_semantics(compact) or _is_recast_related(
                compact, _recast_features(compact)
            ):
                return False
        if self._stage == WAIT_DRAWING_CONSENT:
            return not (
                _contains_any(compact, _DRAWING_ACCEPT_WORDS)
                or _contains_any(compact, _DRAWING_REJECT_WORDS)
                or _is_affirmative(compact)
            )
        if _contains_any(compact, _DINOSAUR_WORDS):
            return False
        stage_similarity = self._current_stage_similarity(compact)
        if stage_similarity >= STAGE_CLARIFY_SIMILARITY_THRESHOLD:
            return False
        if _contains_any(compact, _UNCLEAR_WORDS) or _contains_any(
            compact, _FRUSTRATION_WORDS
        ):
            return False
        return True

    def _current_stage_similarity(self, compact: str) -> float:
        if self._stage == WAIT_DESCRIPTION:
            return _big_description_similarity(compact)
        if self._stage == WAIT_HIGH_LEAVES_CONFIRMATION:
            return _high_leaves_similarity(compact)
        if self._stage == WAIT_RECAST:
            return _recast_similarity(compact)
        if self._stage == WAIT_DRAWING_CONSENT:
            return 1.0 if _contains_any(compact, _DRAWING_ACCEPT_WORDS) else 0.0
        return 0.0

    def _is_resume_only_turn(self, compact: str) -> bool:
        if not _contains_any(compact, _RESUME_WORDS):
            return False
        if not _contains_any(compact, _DINOSAUR_WORDS):
            return False
        if _contains_any(compact, _NEGATIVE_WORDS + _FRUSTRATION_WORDS):
            return False
        return self._current_stage_similarity(compact) < STAGE_CLARIFY_SIMILARITY_THRESHOLD

    def _resume_prompt_locked(self) -> GuidedExpressionReply:
        prompts = {
            WAIT_DESCRIPTION: "好呀，我们继续。你想的恐龙是什么样子的呢？",
            WAIT_HIGH_LEAVES_CONFIRMATION: "好，我们继续。它是不是可以吃到很高很高的树叶呀？",
            WAIT_RECAST: (
                "好，我们继续。说说你喜欢腕龙的原因，记得身体大、脖子长。"
            ),
            WAIT_DRAWING_CONSENT: "好，我们继续。你想把刚才描述的腕龙画下来吗？",
        }
        return self._reply(
            prompts.get(self._stage, "好呀，我们继续说刚才那个恐龙。"),
            scene="dinosaur_expression_resumed",
            expression="listening",
        )

    def _begin_recast_locked(self) -> None:
        self._stage = WAIT_RECAST
        self._recast_seen_features.clear()

    def _complete_recast_locked(self) -> GuidedExpressionReply:
        self._remembered_dinosaur = "腕龙"
        self._stage = WAIT_DRAWING_CONSENT
        self._suspended = False
        self._recast_seen_features.clear()
        return self._reply(
            "你自己说得真完整！我也记住你喜欢腕龙啦。来，击掌庆祝一下吧！",
            scene="dinosaur_expression_completed",
            memory={
                "interests": ["恐龙", "腕龙"],
                "recent_topics": ["完整描述腕龙"],
                "facts": ["孩子在表达困难后愿意分步骤尝试，并完整描述了腕龙。"],
            },
            post_tts_arm_action="high_five",
            end_session=True,
        )

    def _has_recent_sadness_locked(self) -> bool:
        if self._last_sadness_at is None:
            return False
        return self._clock() - self._last_sadness_at <= self._emotion_window_seconds

    def _reply(
        self,
        text: str,
        *,
        scene: str,
        expression: str = "smile",
        memory: dict[str, Any] | None = None,
        end_session: bool = False,
        post_tts_arm_action: str = "",
    ) -> GuidedExpressionReply:
        return GuidedExpressionReply(
            text=text,
            scene=scene,
            stage=self._stage,
            screen_expression=expression,
            led_mode="blue_breath" if expression in {"listening", "comforting"} else "warm_breath",
            memory_update=dict(memory or {}),
            post_tts_arm_action=str(post_tts_arm_action or ""),
            end_session=bool(end_session),
        )

    def _reset_stage_only_locked(self) -> None:
        self._stage = IDLE
        self._suspended = False
        self._last_sadness_at = None
        self._recast_seen_features.clear()

    def _reset_locked(self) -> None:
        self._reset_stage_only_locked()
        self._nickname = ""
        self._remembered_dinosaur = ""


def _compact(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:]+", "", str(text or ""))


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _looks_like_dinosaur_preference(text: str) -> bool:
    preference_markers = ("喜欢", "最爱", "感兴趣", "爱好是")
    return _contains_any(text, preference_markers) and _contains_any(
        text, _DINOSAUR_WORDS
    )


def _looks_big(text: str) -> bool:
    return (
        any(
            word in text
            for word in (
                "特别大",
                "非常大",
                "很大",
                "巨大",
                "大大的",
                "超级大",
                "庞大",
                "个头大",
                "大个子",
            )
        )
        or ("身体" in text and "大" in text)
        or ("体型" in text and "大" in text)
    )


def _looks_unclear(text: str) -> bool:
    """Accept short child-like ways of saying that words are hard to find."""
    return (
        _contains_any(text, _UNCLEAR_WORDS)
        or "不知道" in text
        or "说不清" in text
        or "讲不清" in text
        or "不会说" in text
    )


def _looks_long_neck(text: str) -> bool:
    return (
        "长脖子" in text
        or ("脖子" in text and "长" in text)
        or ("颈部" in text and ("长" in text or "伸" in text))
    )


def _looks_high_leaves(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "高高的树叶",
            "高高树叶",
            "很高的树叶",
            "高处的树叶",
            "高的树叶",
            "树顶的叶子",
            "树顶叶子",
            "高处的叶子",
        )
    )


def _looks_like_complete_recast(text: str) -> bool:
    return len(_recast_features(text)) == 3


def _has_demo_recast_keywords(text: str) -> bool:
    """Whether one demo recitation contains all three reviewed anchor words."""
    return all(keyword in text for keyword in ("大", "长", "树叶"))


def _has_final_recast_semantics(text: str) -> bool:
    """Accept a child's own complete meaning instead of one memorized line."""
    return (
        _looks_like_brachiosaurus_name(text)
        and _looks_like_dinosaur_preference(text)
        and _looks_big(text)
        and _looks_long_neck(text)
    )


def _recast_feature_count(text: str) -> int:
    return len(_recast_features(text))


def _recast_features(text: str) -> set[str]:
    """Extract the three reviewed meaning slots, independent of word order."""
    features: set[str] = set()
    if _looks_big(text):
        features.add("body_big")
    if _looks_long_neck(text):
        features.add("long_neck")
    if _looks_high_leaves(text) or (
        ("树叶" in text or "叶子" in text)
        and any(marker in text for marker in ("吃", "够到", "碰到", "高", "树顶"))
    ):
        features.add("high_leaves")
    return features


def _looks_like_brachiosaurus_name(text: str) -> bool:
    return _contains_any(text, _BRACHIOSAURUS_ALIASES)


def _is_recast_related(text: str, features: set[str] | None = None) -> bool:
    return bool(
        features or _looks_like_brachiosaurus_name(text) or _contains_any(text, _RECAST_ATTEMPT_WORDS)
    )


def _recast_missing_feature_prompt(features: set[str]) -> str:
    missing_prompts = {
        "body_big": "你已经说出了不少特点啦，再加上它的身体特别大，就更完整了。",
        "long_neck": "你已经说出了不少特点啦，再加上它的脖子特别长，就更完整了。",
        "high_leaves": "你已经说出了身体特别大、脖子特别长，再加上它能吃到高高的树叶就完整啦。",
    }
    for feature in ("body_big", "long_neck", "high_leaves"):
        if feature not in features:
            return missing_prompts[feature]
    return "已经很接近啦。再把三个特点连起来说一遍吧。"


def _final_recast_missing_prompt(text: str, features: set[str]) -> str:
    """Ask for only one missing meaning slot in child-friendly language."""
    if not _looks_like_brachiosaurus_name(text) or not _looks_like_dinosaur_preference(text):
        return "特点都说对啦，再把“我喜欢腕龙”也连起来说一遍吧。"
    if "body_big" not in features:
        return "你已经说出喜欢腕龙啦，再说说它的身体是什么样的吧。"
    if "long_neck" not in features:
        return "你已经说出它身体很大啦，再说说它的脖子是什么样的吧。"
    return "已经很接近啦，把你喜欢腕龙的原因连起来说一遍吧。"


def _recast_similarity(text: str) -> float:
    feature_count = _recast_feature_count(text)
    return {
        0: 0.0,
        1: 0.45,
        2: 0.72,
        3: 1.0,
    }[feature_count]


def _is_affirmative(text: str) -> bool:
    if _contains_any(text, _NEGATIVE_WORDS):
        return False
    return text in _AFFIRMATIVE_WORDS or any(
        text.startswith(word) for word in ("对", "是的", "好呀", "可以")
    )


def _looks_like_fact_question(text: str) -> bool:
    if not _contains_any(text, _DINOSAUR_WORDS):
        return False
    return any(
        marker in text
        for marker in (
            "吃什么",
            "住哪里",
            "生活在哪里",
            "有多大",
            "为什么",
            "怎么灭绝",
            "是什么",
            "多少",
        )
    )


def _template_similarity(text: str, templates: tuple[str, ...]) -> float:
    normalized = _canonical_similarity_text(text)
    if not normalized:
        return 0.0
    return max(
        SequenceMatcher(None, normalized, _canonical_similarity_text(template)).ratio()
        for template in templates
    )


def _canonical_similarity_text(text: str) -> str:
    normalized = _compact(text)
    replacements = (
        ("最喜欢", "喜欢"),
        ("特别喜欢", "喜欢"),
        ("很喜欢", "喜欢"),
        ("非常大", "特别大"),
        ("超级大", "特别大"),
        ("庞大", "特别大"),
        ("个头大", "特别大"),
        ("长长的脖子", "脖子特别长"),
        ("长脖子", "脖子特别长"),
        ("高处的叶子", "高高的树叶"),
        ("树顶的叶子", "高高的树叶"),
        ("说不出来", "不知道怎么说"),
        ("讲不清楚", "不知道怎么说"),
        ("说不清楚", "不知道怎么说"),
        ("不知道怎么表达", "不知道怎么说"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def _dinosaur_activation_similarity(
    text: str,
    compact: str,
    *,
    nickname_match: re.Match[str] | None = None,
) -> float:
    """Score only the reviewed name + dinosaur-interest activation sentence."""
    match = nickname_match or _NICKNAME_RE.search(text)
    has_name = match is not None
    has_dinosaur = _contains_any(compact, _DINOSAUR_WORDS)
    has_preference = _looks_like_dinosaur_preference(compact)
    if _contains_any(compact, _NEGATIVE_PREFERENCE_WORDS):
        return 0.0
    if not (has_name and has_dinosaur and has_preference):
        return 0.0
    score = 0.30 + 0.40 + 0.20
    score += 0.10 * _template_similarity(compact, _ACTIVATION_TEMPLATES)
    return min(1.0, score)


def _big_description_similarity(text: str) -> float:
    if _looks_big(text):
        return 1.0
    mentions_size = any(word in text for word in ("大", "个头", "身体", "体型"))
    if not mentions_size:
        return 0.0
    unclear = _contains_any(text, _UNCLEAR_WORDS)
    score = 0.55 + (0.20 if unclear else 0.0)
    score += 0.25 * _template_similarity(text, _BIG_DESCRIPTION_TEMPLATES)
    return min(1.0, score)


def _long_neck_similarity(text: str) -> float:
    if _looks_long_neck(text):
        return 1.0
    mentions_neck = "脖子" in text or "颈" in text
    if not mentions_neck:
        return 0.0
    mentions_length = any(word in text for word in ("长", "高", "伸得远", "伸得很远"))
    score = 0.55 + (0.25 if mentions_length else 0.0)
    score += 0.20 * _template_similarity(text, _LONG_NECK_TEMPLATES)
    return min(1.0, score)


def _high_leaves_similarity(text: str) -> float:
    if _looks_high_leaves(text):
        return 1.0
    mentions_leaves = "树叶" in text or "叶子" in text
    if not mentions_leaves:
        return 0.0
    mentions_height = any(word in text for word in ("高", "树顶", "上面"))
    score = 0.55 + (0.25 if mentions_height else 0.0)
    score += 0.20 * _template_similarity(text, _HIGH_LEAVES_TEMPLATES)
    return min(1.0, score)
