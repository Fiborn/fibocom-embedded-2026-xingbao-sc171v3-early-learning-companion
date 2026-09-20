"""Expression orchestration for Xingbao's companion responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.memory import is_sensitive_text, sanitize_memory_updates


DEFAULT_SOURCE = "unknown"
DEFAULT_PRIORITY = 1


@dataclass(frozen=True)
class ExpressionEvent:
    """A normalized event submitted by dialogue, touch, game, or vision modules."""

    type: str
    source: str = DEFAULT_SOURCE
    priority: int = DEFAULT_PRIORITY
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    timestamp: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "ExpressionEvent":
        """Create an event from the protocol JSON envelope."""
        payload = raw.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            type=str(raw.get("type", "")).strip(),
            source=str(raw.get("source", DEFAULT_SOURCE)).strip() or DEFAULT_SOURCE,
            priority=_safe_priority(raw.get("priority", payload.get("priority"))),
            payload=payload,
            event_id=_optional_str(raw.get("event_id")),
            timestamp=_optional_str(raw.get("timestamp")),
        )


@dataclass(frozen=True)
class ExpressionOutput:
    """A unified Xingbao expression package for output modules."""

    intent: str
    speak_text: str = ""
    screen_text: str = ""
    expression: str = "neutral"
    tts: bool = False
    priority: int = DEFAULT_PRIORITY
    memory_request: dict[str, Any] | None = None
    state: str = "idle"
    interrupt_policy: str = "queue"
    source: str = DEFAULT_SOURCE
    handled: bool = True
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable output package."""
        result: dict[str, Any] = {
            "intent": self.intent,
            "speak_text": self.speak_text,
            "screen_text": self.screen_text,
            "expression": self.expression,
            "tts": self.tts,
            "priority": self.priority,
            "state": self.state,
            "interrupt_policy": self.interrupt_policy,
            "source": self.source,
            "handled": self.handled,
        }
        if self.memory_request is not None:
            result["memory_request"] = self.memory_request
        if self.reason:
            result["reason"] = self.reason
        return result


class ExpressionDispatcher:
    """Converts protocol events into Xingbao speech/screen/memory decisions."""

    def handle(self, raw_event: ExpressionEvent | dict[str, Any]) -> ExpressionOutput:
        """Handle one event and return a unified expression output."""
        event = (
            raw_event
            if isinstance(raw_event, ExpressionEvent)
            else ExpressionEvent.from_mapping(raw_event)
        )

        if event.type == "xingbao_expression_request":
            return self._handle_expression_request(event)
        if event.type == "touch_event":
            return self._handle_named_event(event, TOUCH_RESPONSES)
        if event.type == "game_event":
            return self._handle_named_event(event, GAME_RESPONSES)
        if event.type == "vision_event":
            return self._handle_named_event(event, VISION_RESPONSES)
        if event.type == "memory_write_request":
            return self._handle_memory_write_request(event)
        if event.type == "growth_record_request":
            return self._handle_growth_record_request(event)
        if event.type == "module_error":
            return self._handle_module_error(event)
        if event.type in DIALOGUE_RESPONSES:
            return self._build_output(event, DIALOGUE_RESPONSES[event.type])

        return ExpressionOutput(
            intent="fallback",
            speak_text="星宝刚刚有一点没跟上，我们可以点屏幕继续，也可以再说一遍。",
            screen_text="可以点屏幕继续",
            expression="calm",
            tts=True,
            priority=max(event.priority, 1),
            state="fallback",
            source=event.source,
            handled=False,
            reason=f"unsupported_event_type:{event.type}",
        )

    def _handle_expression_request(self, event: ExpressionEvent) -> ExpressionOutput:
        payload = event.payload
        text = str(payload.get("text", "")).strip()
        if is_sensitive_text(text):
            # Do not read back a sensitive request through the legacy direct
            # expression route.  The normal dialogue path handles it with
            # contextual privacy guidance.
            text = ""
        return ExpressionOutput(
            intent=str(payload.get("intent", "respond")).strip() or "respond",
            speak_text=text,
            screen_text=str(payload.get("screen_text") or text[:24]).strip() if text else "",
            expression=str(payload.get("emotion") or payload.get("screen_state") or "smile"),
            tts=bool(payload.get("tts", True)) and bool(text),
            priority=event.priority,
            state=_state_for_intent(str(payload.get("intent", ""))),
            interrupt_policy=str(payload.get("interrupt_policy", "queue")),
            source=event.source,
        )

    def _handle_named_event(
        self,
        event: ExpressionEvent,
        table: dict[str, dict[str, Any]],
    ) -> ExpressionOutput:
        name = str(event.payload.get("event", "")).strip()
        template = table.get(name)
        if template is None:
            return ExpressionOutput(
                intent="fallback",
                speak_text="星宝收到这个变化了，我们先慢慢继续。",
                screen_text="继续",
                expression="calm",
                tts=True,
                priority=max(event.priority, 1),
                state="fallback",
                source=event.source,
                handled=False,
                reason=f"unsupported_payload_event:{name}",
            )
        return self._build_output(event, template)

    def _handle_memory_write_request(self, event: ExpressionEvent) -> ExpressionOutput:
        memory_request = _memory_update_from_payload(event.payload)
        if memory_request is None:
            return ExpressionOutput(
                intent="reject_memory",
                screen_text="这条记忆没有写入",
                expression="neutral",
                tts=False,
                priority=event.priority,
                state="idle",
                source=event.source,
                handled=False,
                reason="memory_rejected_or_empty",
            )
        return ExpressionOutput(
            intent="acknowledge_memory",
            speak_text="星宝记住啦。",
            screen_text="星宝记住啦",
            expression="smile",
            tts=True,
            priority=event.priority,
            memory_request=memory_request,
            state="speaking",
            source=event.source,
        )

    def _handle_growth_record_request(self, event: ExpressionEvent) -> ExpressionOutput:
        hint = str(event.payload.get("summary_hint", "")).strip()
        text = hint or "今天你愿意表达，也愿意继续尝试。星宝帮你记成一颗成长星。"
        if is_sensitive_text(text):
            text = "今天你愿意表达和尝试，星宝帮你记成一颗成长星。"
        return ExpressionOutput(
            intent="share_growth",
            speak_text=text,
            screen_text="今日成长星星",
            expression="happy",
            tts=True,
            priority=max(event.priority, 2),
            memory_request={"growth_note": [text]},
            state="summarizing",
            source=event.source,
        )

    def _handle_module_error(self, event: ExpressionEvent) -> ExpressionOutput:
        code = str(event.payload.get("error_code", "")).strip()
        template = ERROR_RESPONSES.get(code, ERROR_RESPONSES["default"])
        return self._build_output(event, template)

    def _build_output(
        self,
        event: ExpressionEvent,
        template: dict[str, Any],
    ) -> ExpressionOutput:
        priority = max(event.priority, int(template.get("priority", DEFAULT_PRIORITY)))
        memory_request = template.get("memory_request")
        if callable(memory_request):
            memory_request = memory_request(event)
        return ExpressionOutput(
            intent=str(template["intent"]),
            speak_text=str(template.get("speak_text", "")),
            screen_text=str(template.get("screen_text", "")),
            expression=str(template.get("expression", "neutral")),
            tts=bool(template.get("tts", False)),
            priority=priority,
            memory_request=memory_request,
            state=str(template.get("state", "idle")),
            interrupt_policy=str(template.get("interrupt_policy", "queue")),
            source=event.source,
        )


DIALOGUE_RESPONSES: dict[str, dict[str, Any]] = {
    "child_unclear_text": {
        "intent": "guide_expression",
        # Do not turn an incomplete child utterance into a guessed, fixed
        # dialogue.  The live dialogue route lets the LLM ask naturally with
        # the surrounding conversation instead.
        "speak_text": "",
        "screen_text": "",
        "expression": "listening",
        "tts": False,
        "priority": 2,
        "state": "guiding_expression",
    },
    "child_expressed_mood": {
        "intent": "comfort",
        # Mood support must follow the actual dialogue context rather than a
        # one-size-fits-all consolation line.
        "speak_text": "",
        "screen_text": "",
        "expression": "comforting",
        "tts": False,
        "priority": 2,
        "state": "comforting",
    },
}

SILENT_TOOLBOX_RESPONSE: dict[str, Any] = {
    "intent": "acknowledge_toolbox_state",
    "speak_text": "",
    "screen_text": "",
    "expression": "neutral",
    "tts": False,
    "priority": 1,
    "state": "idle",
}


TOUCH_RESPONSES: dict[str, dict[str, Any]] = {
    # The touch desktop already shows and, where useful, reads the selected
    # toolbox item.  These semantic events exist for coordination and arm
    # feedback; speaking a generic fallback for each one creates a noisy loop.
    "toolbox_opened": SILENT_TOOLBOX_RESPONSE,
    "toolbox_activity_started": SILENT_TOOLBOX_RESPONSE,
    "toolbox_result_saved": SILENT_TOOLBOX_RESPONSE,
    "drawing_started": SILENT_TOOLBOX_RESPONSE,
    "drawing_completed": SILENT_TOOLBOX_RESPONSE,
    "child_touched_xingbao": {
        "intent": "greet",
        "speak_text": "我在呢，要一起玩一会儿吗？",
        "screen_text": "我在呢",
        "expression": "smile",
        "tts": True,
        "priority": 1,
        "state": "speaking",
    },
    "child_requested_hint": {
        "intent": "hint",
        "speak_text": "星宝给你一个小提示：先看看颜色。",
        "screen_text": "先看看颜色",
        "expression": "thinking",
        "tts": True,
        "priority": 1,
        "state": "speaking",
    },
    "child_cancelled_choice": {
        "intent": "support_retry",
        "speak_text": "没关系，我们可以重新选。",
        "screen_text": "重新选",
        "expression": "calm",
        "tts": True,
        "priority": 1,
        "state": "speaking",
    },
}

GAME_RESPONSES: dict[str, dict[str, Any]] = {
    # The board touch bridge carries toolbox status over the shared game-event
    # socket.  Keep the same silent semantics as the direct touch-event route.
    "toolbox_opened": SILENT_TOOLBOX_RESPONSE,
    "toolbox_activity_started": SILENT_TOOLBOX_RESPONSE,
    "toolbox_result_saved": SILENT_TOOLBOX_RESPONSE,
    "drawing_started": SILENT_TOOLBOX_RESPONSE,
    "drawing_completed": SILENT_TOOLBOX_RESPONSE,
    "game_started": {
        "intent": "invite_play",
        "speak_text": "我们一起玩一个小任务吧。",
        "screen_text": "开始小任务",
        "expression": "happy",
        "tts": True,
        "priority": 1,
        "state": "playing_game",
    },
    "child_made_mistake": {
        "intent": "encourage_retry",
        "speak_text": "这一步有点难，我们换个办法试试。",
        "screen_text": "换个办法试试",
        "expression": "encouraging",
        "tts": True,
        "priority": 1,
        "state": "playing_game",
    },
    "game_finished": {
        "intent": "summarize_growth",
        "speak_text": "你刚才没有放弃，还愿意再试一次。星宝帮你记成一颗尝试星。",
        "screen_text": "获得尝试星",
        "expression": "happy",
        "tts": True,
        "priority": 2,
        "state": "summarizing",
        "memory_request": {"growth_note": ["孩子在小游戏里愿意继续尝试。"]},
    },
}

VISION_RESPONSES: dict[str, dict[str, Any]] = {
    "child_returned": {
        "intent": "resume",
        "speak_text": "欢迎回来，我们接着刚才的地方。",
        "screen_text": "欢迎回来",
        "expression": "smile",
        "tts": True,
        "priority": 1,
        "state": "speaking",
    },
    "sitting_too_long": {
        "intent": "break_reminder",
        "speak_text": "我们坐了一会儿啦，要不要站起来伸个懒腰？",
        "screen_text": "休息一下",
        "expression": "caring",
        "tts": True,
        "priority": 3,
        "state": "health_reminding",
    },
    "drink_water_reminder_due": {
        "intent": "drink_reminder",
        "speak_text": "要不要喝一小口水？喝完我们继续。",
        "screen_text": "喝一小口水",
        "expression": "caring",
        "tts": True,
        "priority": 2,
        "state": "health_reminding",
    },
    "face_too_close": {
        "intent": "eye_distance",
        "speak_text": "小眼睛离屏幕有点近啦，我们往后坐一点。",
        "screen_text": "往后坐一点",
        "expression": "caring",
        "tts": True,
        "priority": 3,
        "state": "health_reminding",
    },
    "camera_blocked": {
        "intent": "camera_fallback",
        # Camera availability is an implementation detail; do not inject a
        # fixed spoken fallback into a conversation.
        "speak_text": "",
        "screen_text": "",
        "expression": "calm",
        "tts": False,
        "priority": 2,
        "state": "fallback",
    },
}

ERROR_RESPONSES: dict[str, dict[str, Any]] = {
    "asr_failed": {
        "intent": "ask_repeat_or_touch",
        "speak_text": "星宝刚刚没听清，可以再说一遍，也可以点屏幕。",
        "screen_text": "再说一遍 / 点屏幕",
        "expression": "confused",
        "tts": True,
        "priority": 1,
        "state": "fallback",
    },
    "tts_failed": {
        "intent": "screen_fallback",
        "screen_text": "星宝先把话显示在屏幕上",
        "expression": "calm",
        "tts": False,
        "priority": 2,
        "state": "fallback",
    },
    "default": {
        "intent": "recover",
        # Generic failures must not interrupt the child with a fixed line.
        # The caller can log/retry or render a contextual recovery state.
        "speak_text": "",
        "screen_text": "",
        "expression": "calm",
        "tts": False,
        "priority": 2,
        "state": "fallback",
    },
}


def _memory_update_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(payload.get("memory_kind", "")).strip()
    content = str(payload.get("content", "")).strip()
    if not kind or not content or is_sensitive_text(content):
        return None

    if kind == "interest":
        update = {"interests": [content]}
    elif kind == "game_preference":
        update = {"favorite_games": [content]}
    elif kind == "recent_mood":
        update = {"recent_mood": content}
    elif kind in {"communication_style", "learning_preference"}:
        update = {"communication_style": {kind: content}}
    elif kind == "growth_note":
        update = {"recent_topics": [content]}
    else:
        return None

    sanitized = sanitize_memory_updates(update)
    return sanitized or None


def _state_for_intent(intent: str) -> str:
    if intent in {"comfort", "encourage"}:
        return "comforting"
    if intent in {"hint", "respond"}:
        return "speaking"
    if intent in {"health_reminder", "break_reminder"}:
        return "health_reminding"
    return "speaking"


def _safe_priority(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY
    return max(0, min(3, value))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
