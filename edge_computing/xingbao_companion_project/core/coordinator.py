"""Computer-side interaction coordinator for Xingbao."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.expression import ExpressionDispatcher, ExpressionOutput
from core.intent_router import IntentResult, IntentRouter
from core.state_inputs import is_state_input, normalize_state_input
from core.tool_registry import ToolLaunchRequest, ToolRegistry


@dataclass(frozen=True)
class CoordinationPlan:
    """A complete high-level plan for one child input."""

    user_text: str
    intent: IntentResult
    expression_output: ExpressionOutput
    tool_request: ToolLaunchRequest | None = None
    events: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "user_text": self.user_text,
            "intent": self.intent.as_dict(),
            "expression_output": self.expression_output.as_dict(),
            "events": list(self.events),
        }
        if self.tool_request is not None:
            result["tool_request"] = self.tool_request.as_dict()
        return result


class XingbaoCoordinator:
    """Turns child input into speech, expression, and tool launch requests."""

    def __init__(
        self,
        *,
        intent_router: IntentRouter | None = None,
        tool_registry: ToolRegistry | None = None,
        expression_dispatcher: ExpressionDispatcher | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouter()
        self.tool_registry = tool_registry or ToolRegistry()
        self.expression_dispatcher = expression_dispatcher or ExpressionDispatcher()

    def plan_text(self, user_text: str) -> CoordinationPlan:
        text = (user_text or "").strip()
        intent = self.intent_router.route(text)

        if intent.intent == "open_tool":
            tool_request = self.tool_registry.build_launch_request(intent.target)
            expression_event = _tool_expression_event(intent, tool_request)
            output = self.expression_dispatcher.handle(expression_event)
            return CoordinationPlan(
                user_text=text,
                intent=intent,
                expression_output=output,
                tool_request=tool_request,
                events=(expression_event,),
            )

        expression_event = _general_expression_event(intent)
        output = self.expression_dispatcher.handle(expression_event)
        return CoordinationPlan(
            user_text=text,
            intent=intent,
            expression_output=output,
            events=(expression_event,),
        )

    def plan_event(self, raw_event: dict[str, Any]) -> CoordinationPlan:
        """Plan one structured module event through the same output pipeline."""
        event_type = str(raw_event.get("type", "")).strip() or "module_event"
        payload = raw_event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        expression_event = normalize_state_input(raw_event)
        expression_payload = expression_event.get("payload", {})
        if not isinstance(expression_payload, dict):
            expression_payload = {}
        output = self.expression_dispatcher.handle(expression_event)
        source_text = str(
            payload.get("event")
            or payload.get("state")
            or payload.get("intent")
            or payload.get("text")
            or expression_payload.get("event")
            or expression_payload.get("state")
            or expression_payload.get("intent")
            or event_type
        )
        intent = IntentResult(
            intent=event_type,
            confidence=1.0 if output.handled else 0.3,
            source_text=source_text,
            reason=(
                f"state_input:{expression_event.get('type', '')}"
                if is_state_input(raw_event)
                else "module_event"
            ),
        )
        events = (raw_event,) if expression_event == raw_event else (raw_event, expression_event)
        return CoordinationPlan(
            user_text="",
            intent=intent,
            expression_output=output,
            events=events,
        )


def _tool_expression_event(
    intent: IntentResult,
    tool_request: ToolLaunchRequest,
) -> dict[str, Any]:
    if tool_request.status == "ready":
        emotion = "happy"
        screen_text = tool_request.display_name
        speak_text = _ready_speech_for_tool(tool_request.target)
    elif tool_request.status == "unavailable":
        emotion = "thinking"
        screen_text = "工具准备中"
        speak_text = "这个功能还在准备中，我们先看看别的。"
    else:
        emotion = "calm"
        screen_text = "回到主界面"
        speak_text = "好呀，我们先回到主界面。"

    return {
        "type": "xingbao_expression_request",
        "source": "coordinator",
        "priority": 1,
        "payload": {
            "intent": intent.intent,
            "text": speak_text,
            "screen_text": screen_text,
            "emotion": emotion,
            "tts": bool(speak_text),
            "interrupt_policy": "queue",
            "feedback": {
                "screen_expression": "smile",
                "arm_action": "wave_hand" if tool_request.target == "mini_game_hub" else "stay_still",
            },
        },
    }


def _general_expression_event(intent: IntentResult) -> dict[str, Any]:
    feedback: dict[str, str] = {"arm_action": "stay_still"}
    if intent.intent == "greeting":
        emotion = "happy"
        screen_text = "你好呀"
        feedback["screen_expression"] = "smile"
    elif intent.intent == "ask_help":
        emotion = "encouraging"
        screen_text = "一步一步来"
        feedback["screen_expression"] = "smile"
    elif intent.intent == "exit_activity":
        emotion = "calm"
        screen_text = "已回到主界面"
        feedback["screen_expression"] = "neutral"
    elif intent.intent == "unknown":
        emotion = "thinking"
        screen_text = "再说一遍"
        feedback["screen_expression"] = "thinking"
    else:
        emotion = "listening"
        screen_text = ""
        feedback["screen_expression"] = "curious"

    return {
        "type": "xingbao_expression_request",
        "source": "coordinator",
        "priority": 1,
        "payload": {
            "intent": intent.intent,
            "text": "",
            "screen_text": screen_text,
            "emotion": emotion,
            "tts": False,
            "interrupt_policy": "queue",
            "feedback": feedback,
        },
    }


def _ready_speech_for_tool(target: str) -> str:
    if target == "mini_game_hub":
        return "进入游戏啦，请先选择一个游戏。选好以后，再选一个难度。"
    if target == "color_block_game":
        return "好呀，我们一起来玩颜色小游戏。"
    if target == "kids_visual_tools":
        return "好呀，星宝帮你打开白宝箱小工具。"
    if target.startswith("kids_visual_tools:"):
        return "好呀，星宝帮你打开这个小工具。"
    if target == "story_time":
        return "好呀，我们进入故事时间。"
    return "好呀，星宝帮你打开这个功能。"
