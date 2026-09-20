"""Growth guidance planning for Xingbao's companion behavior."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.expression import ExpressionEvent
from core.knowledge_base import KnowledgeBase
from core.memory import is_sensitive_text


DEFAULT_SOURCE = "growth_guidance"
DEFAULT_TOPIC_COOLDOWN_SECONDS = 900.0


@dataclass(frozen=True)
class GrowthContext:
    """Runtime context used to decide whether Xingbao should guide or wait."""

    state: str = "idle"
    child_memory: dict[str, Any] = field(default_factory=dict)
    current_game: dict[str, Any] | None = None
    recent_topics: tuple[str, ...] = ()
    rejected_topics: tuple[str, ...] = ()
    topic_last_spoken_at: dict[str, float] = field(default_factory=dict)
    child_is_speaking: bool = False
    no_high_priority_event: bool = True
    now: float = 0.0


@dataclass(frozen=True)
class GrowthGuidancePlan:
    """A normalized plan that can later be converted to speech, screen, and memory."""

    scene: str
    priority: int
    speak_text: str = ""
    screen_text: str = ""
    screen_options: tuple[str, ...] = ()
    expression: str = "neutral"
    led_mode: str = "off"
    memory_request: dict[str, Any] | None = None
    next_state: str = "idle"
    source: str = DEFAULT_SOURCE
    handled: bool = True
    reason: str = ""
    topic_id: str = ""
    interrupt_policy: str = "queue"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "scene": self.scene,
            "priority": self.priority,
            "speak_text": self.speak_text,
            "screen_text": self.screen_text,
            "screen_options": list(self.screen_options),
            "expression": self.expression,
            "led_mode": self.led_mode,
            "next_state": self.next_state,
            "source": self.source,
            "handled": self.handled,
            "interrupt_policy": self.interrupt_policy,
        }
        if self.memory_request is not None:
            result["memory_request"] = self.memory_request
        if self.reason:
            result["reason"] = self.reason
        if self.topic_id:
            result["topic_id"] = self.topic_id
        return result


class GrowthGuidanceEngine:
    """Turns dialogue, game, touch, and vision events into growth guidance plans."""

    def __init__(
        self,
        *,
        knowledge_base: KnowledgeBase | None = None,
        topic_cooldown_seconds: float = DEFAULT_TOPIC_COOLDOWN_SECONDS,
        clock: Any | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base or KnowledgeBase()
        self.topic_cooldown_seconds = max(0.0, topic_cooldown_seconds)
        self.clock = clock or time.monotonic

    def plan(
        self,
        raw_event: ExpressionEvent | dict[str, Any],
        context: GrowthContext | None = None,
    ) -> GrowthGuidancePlan:
        event = (
            raw_event
            if isinstance(raw_event, ExpressionEvent)
            else ExpressionEvent.from_mapping(raw_event)
        )
        context = _normalize_context(context, self.clock())

        safety_plan = self._maybe_safety_plan(event)
        if safety_plan is not None:
            return safety_plan

        if event.type in {"child_unclear_text", "dialogue_event"}:
            return self._plan_dialogue(event)
        if event.type == "touch_event":
            return self._plan_touch(event, context)
        if event.type == "game_event":
            return self._plan_game(event, context)
        if event.type == "vision_event":
            return self._plan_vision(event)
        if event.type == "growth_record_request":
            return self._plan_growth_record(event)
        if event.type == "proactive_opportunity":
            return self._plan_proactive_topic(event, context)

        return GrowthGuidancePlan(
            scene="no_guidance",
            priority=max(event.priority, 0),
            next_state=context.state,
            handled=False,
            reason=f"unsupported_event_type:{event.type}",
        )

    def _plan_dialogue(self, event: ExpressionEvent) -> GrowthGuidancePlan:
        text = str(event.payload.get("text", "")).strip()
        compact = _compact_text(text)
        if _looks_like_unclear_expression(compact):
            return GrowthGuidancePlan(
                scene="expression_scaffold",
                priority=max(event.priority, 2),
                # This scene is guidance for the LLM, not a scripted reply:
                # do not assume the child is describing exclusion from play.
                speak_text="",
                screen_text="",
                screen_options=("他不让我玩", "我想再说说", "不是这个"),
                expression="listening",
                led_mode="blue_breath",
                next_state="expression_scaffold",
                reason="unclear_child_expression",
            )
        if _looks_like_emotion_expression(compact):
            return GrowthGuidancePlan(
                scene="emotion_naming",
                priority=max(event.priority, 2),
                speak_text="你的感受很重要。你现在更像是生气，还是有点难过？",
                screen_text="你现在是什么感觉？",
                screen_options=("生气", "难过", "有点委屈"),
                expression="comforting",
                led_mode="blue_breath",
                next_state="expression_scaffold",
                reason="child_emotion_signal",
            )
        if _looks_like_opinion_expression(compact):
            return GrowthGuidancePlan(
                scene="opinion_encouragement",
                priority=max(event.priority, 2),
                speak_text="你的想法很重要。可以告诉我，你为什么这样觉得吗？",
                screen_text="星宝想听你的想法",
                screen_options=("我不喜欢", "我觉得可以", "我想换一个"),
                expression="listening",
                led_mode="blue_breath",
                next_state="listening",
                reason="child_opinion_signal",
            )
        return GrowthGuidancePlan(
            scene="listening_support",
            priority=max(event.priority, 1),
            speak_text="星宝听见啦。你可以继续说，我会慢慢听。",
            screen_text="继续说",
            expression="listening",
            led_mode="blue_breath",
            next_state="listening",
            reason="general_dialogue_support",
        )

    def _plan_touch(
        self,
        event: ExpressionEvent,
        context: GrowthContext,
    ) -> GrowthGuidancePlan:
        name = str(event.payload.get("event", "")).strip()
        if name in {"child_selected_option", "child_confirmed_choice"}:
            label = str(event.payload.get("label") or event.payload.get("target") or "").strip()
            if label:
                return GrowthGuidancePlan(
                    scene="expression_choice_confirmed",
                    priority=max(event.priority, 2),
                    speak_text=f"星宝听懂了一点。我们可以这样说：我现在觉得{label}。",
                    screen_text=f"我现在觉得{label}",
                    expression="smile",
                    led_mode="warm_breath",
                    memory_request={"recent_topics": [f"孩子练习表达：{label}"]},
                    next_state="listening",
                    reason="child_selected_expression_option",
                )
        if name == "child_cancelled_choice":
            return GrowthGuidancePlan(
                scene="respect_refusal",
                priority=max(event.priority, 1),
                speak_text="好的，我们先不聊这个。你想换一个话题吗？",
                screen_text="可以换一个话题",
                screen_options=("聊别的", "玩小任务", "休息一下"),
                expression="calm",
                led_mode="blue_breath",
                next_state="listening",
                reason="child_cancelled_choice",
            )
        return self._plan_proactive_topic(event, context)

    def _plan_game(
        self,
        event: ExpressionEvent,
        context: GrowthContext,
    ) -> GrowthGuidancePlan:
        name = str(event.payload.get("event", "")).strip()
        if name == "child_made_mistake":
            return GrowthGuidancePlan(
                scene="game_encouragement",
                priority=max(event.priority, 1),
                speak_text="这一点有点难，没关系。我们换个线索再试一次。",
                screen_text="换个线索再试一次",
                expression="encouraging",
                led_mode="warm_breath",
                next_state="playing_game",
                reason="child_made_mistake",
            )
        if name == "game_finished":
            proactive = self._plan_proactive_topic(event, context, opportunity="after_game_finished")
            if proactive.handled:
                return proactive
            return GrowthGuidancePlan(
                scene="game_growth_summary",
                priority=max(event.priority, 2),
                speak_text="你刚才愿意继续尝试，星宝帮你记成一颗成长星。",
                screen_text="获得一颗尝试星",
                expression="happy",
                led_mode="warm_breath",
                memory_request={"growth_note": ["孩子在小游戏里愿意继续尝试。"]},
                next_state="summarizing",
                reason="game_finished_without_topic",
            )
        return GrowthGuidancePlan(
            scene="game_support",
            priority=max(event.priority, 1),
            speak_text="星宝陪你一起玩，我们一步一步来。",
            screen_text="一步一步来",
            expression="smile",
            led_mode="warm_breath",
            next_state="playing_game",
            reason=f"game_event:{name}",
        )

    def _plan_vision(self, event: ExpressionEvent) -> GrowthGuidancePlan:
        name = str(event.payload.get("event", "")).strip()
        if name == "sitting_too_long":
            return GrowthGuidancePlan(
                scene="health_reminder",
                priority=3,
                speak_text="我们坐了一会儿啦，要不要站起来伸个懒腰？",
                screen_text="伸个懒腰",
                screen_options=("站起来动一动", "再等一下"),
                expression="caring",
                led_mode="blue_breath",
                next_state="health_reminding",
                reason="sitting_too_long",
            )
        if name == "drink_water_reminder_due":
            return GrowthGuidancePlan(
                scene="health_reminder",
                priority=max(event.priority, 2),
                speak_text="要不要喝一小口水？喝完星宝陪你继续。",
                screen_text="喝一小口水",
                screen_options=("喝水一下", "继续"),
                expression="caring",
                led_mode="blue_breath",
                next_state="health_reminding",
                reason="drink_water_reminder_due",
            )
        if name == "face_too_close":
            return GrowthGuidancePlan(
                scene="health_reminder",
                priority=3,
                speak_text="小眼睛离屏幕有点近啦，我们往后坐一点。",
                screen_text="往后坐一点",
                expression="caring",
                led_mode="blue_breath",
                next_state="health_reminding",
                reason="face_too_close",
            )
        return GrowthGuidancePlan(
            scene="vision_observation",
            priority=max(event.priority, 1),
            screen_text="星宝看见变化了",
            expression="thinking",
            led_mode="blue_breath",
            next_state="listening",
            reason=f"vision_event:{name}",
        )

    def _plan_growth_record(self, event: ExpressionEvent) -> GrowthGuidancePlan:
        hint = str(event.payload.get("summary_hint", "")).strip()
        text = hint or "今天你愿意表达，也愿意继续尝试。星宝帮你记成一颗成长星。"
        if is_sensitive_text(text):
            text = "今天你愿意表达和尝试，星宝帮你记成一颗成长星。"
        return GrowthGuidancePlan(
            scene="growth_record",
            priority=max(event.priority, 2),
            speak_text=text,
            screen_text="今日成长星星",
            expression="happy",
            led_mode="warm_breath",
            memory_request={"growth_note": [text]},
            next_state="summarizing",
            reason="growth_record_request",
        )

    def _plan_proactive_topic(
        self,
        event: ExpressionEvent,
        context: GrowthContext,
        *,
        opportunity: str | None = None,
    ) -> GrowthGuidancePlan:
        opportunity = opportunity or str(event.payload.get("opportunity", "")).strip()
        if not _can_proactively_talk(context, opportunity):
            return GrowthGuidancePlan(
                scene="proactive_topic_deferred",
                priority=0,
                next_state=context.state,
                handled=False,
                reason="proactive_topic_not_allowed",
            )

        festival_reply = self.knowledge_base.prepared_reply("今天是什么日子")
        if festival_reply is None:
            return GrowthGuidancePlan(
                scene="proactive_topic_deferred",
                priority=0,
                next_state=context.state,
                handled=False,
                reason="no_active_daily_topic",
            )

        topic_id = festival_reply.source
        if topic_id in context.rejected_topics:
            return GrowthGuidancePlan(
                scene="proactive_topic_deferred",
                priority=0,
                next_state=context.state,
                handled=False,
                reason="topic_rejected_by_child",
                topic_id=topic_id,
            )
        if not _topic_cooldown_passed(
            context,
            topic_id,
            self.topic_cooldown_seconds,
        ):
            return GrowthGuidancePlan(
                scene="proactive_topic_deferred",
                priority=0,
                next_state=context.state,
                handled=False,
                reason="topic_cooldown_active",
                topic_id=topic_id,
            )

        text = _proactive_text_for_opportunity(festival_reply.text, opportunity)
        return GrowthGuidancePlan(
            scene="proactive_topic",
            priority=max(0, min(event.priority, 1)),
            speak_text=text,
            screen_text="今天的小话题",
            screen_options=("听一个小故事", "玩一个小任务", "先聊别的"),
            expression="curious",
            led_mode="warm_breath",
            next_state="proactive_topic",
            reason=f"opportunity:{opportunity or 'general'}",
            topic_id=topic_id,
        )

    def _maybe_safety_plan(self, event: ExpressionEvent) -> GrowthGuidancePlan | None:
        text = str(event.payload.get("text", "")).strip()
        if _looks_like_danger_or_discomfort(_compact_text(text)):
            return GrowthGuidancePlan(
                scene="safety_support",
                priority=3,
                # Preserve the safety classification, but let the dialogue
                # model phrase the guidance for this specific situation.
                speak_text="",
                screen_text="",
                expression="caring",
                led_mode="yellow_blink",
                next_state="fallback",
                reason="danger_or_discomfort_signal",
                interrupt_policy="immediate",
            )
        if text and is_sensitive_text(text):
            return GrowthGuidancePlan(
                scene="privacy_boundary",
                priority=3,
                # Never read back sensitive information or a fixed privacy
                # disclaimer.  The LLM receives only the boundary guidance.
                speak_text="",
                screen_text="",
                expression="calm",
                led_mode="blue_breath",
                next_state="listening",
                reason="sensitive_child_information",
            )
        return None


def _normalize_context(context: GrowthContext | None, now: float) -> GrowthContext:
    if context is None:
        return GrowthContext(now=now)
    if context.now > 0:
        return context
    return GrowthContext(
        state=context.state,
        child_memory=context.child_memory,
        current_game=context.current_game,
        recent_topics=context.recent_topics,
        rejected_topics=context.rejected_topics,
        topic_last_spoken_at=context.topic_last_spoken_at,
        child_is_speaking=context.child_is_speaking,
        no_high_priority_event=context.no_high_priority_event,
        now=now,
    )


def _can_proactively_talk(context: GrowthContext, opportunity: str) -> bool:
    if context.child_is_speaking or not context.no_high_priority_event:
        return False
    if context.state in {"expression_scaffold", "comforting", "health_reminding"}:
        return False
    allowed_opportunities = {
        "opening",
        "idle_gap",
        "after_game_finished",
        "after_success",
        "summary_ready",
        "child_asked_what_to_do",
    }
    if opportunity and opportunity not in allowed_opportunities:
        return False
    return context.state in {
        "idle",
        "opening",
        "listening",
        "playing_game",
        "summarizing",
        "proactive_topic",
    }


def _topic_cooldown_passed(
    context: GrowthContext,
    topic_id: str,
    cooldown_seconds: float,
) -> bool:
    last_spoken_at = context.topic_last_spoken_at.get(topic_id)
    if last_spoken_at is None:
        return True
    return context.now - last_spoken_at >= cooldown_seconds


def _proactive_text_for_opportunity(topic_text: str, opportunity: str) -> str:
    topic_text = topic_text.strip()
    if opportunity == "after_game_finished":
        return f"你刚才很认真。{topic_text}要不要把它变成一个小故事？"
    if opportunity == "idle_gap":
        return f"星宝想到一个今天的小话题。{topic_text}"
    if opportunity == "child_asked_what_to_do":
        return f"我们可以聊聊今天的小主题。{topic_text}"
    return topic_text


def _compact_text(text: str) -> str:
    return "".join((text or "").split()).lower()


def _looks_like_unclear_expression(compact: str) -> bool:
    return any(word in compact for word in ("那个", "然后", "不知道怎么说", "说不出来", "不让我"))


def _looks_like_emotion_expression(compact: str) -> bool:
    return any(word in compact for word in ("难过", "生气", "委屈", "害怕", "不开心", "想哭"))


def _looks_like_opinion_expression(compact: str) -> bool:
    return any(word in compact for word in ("我觉得", "我认为", "我想", "我不喜欢", "我喜欢"))


def _looks_like_danger_or_discomfort(compact: str) -> bool:
    return any(word in compact for word in ("受伤", "流血", "肚子疼", "头疼", "危险", "打我", "害怕回家"))
