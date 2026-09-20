"""Stable voice-to-game command adapter for Xingbao touch games."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FIXED_GAME_IDS = (
    "color_game",
    "shape_game",
    "memory_game",
    "counting_game",
    "english_game",
    "skill_game",
)

FIXED_GAME_INTENTS = (
    "get_rule",
    "get_goal",
    "get_hint",
    "get_score",
    "get_stars",
    "get_progress",
    "get_remaining",
    "get_round",
    "get_current_game",
    "get_status",
    "get_level",
    "get_energy",
    "get_correct",
    "get_errors",
    "get_attempts",
    "repeat_prompt",
    "restart_round",
    "next_round",
    "pause_game",
    "exit_game",
)

SCREEN_EXPRESSIONS = {
    "neutral",
    "smile",
    "thinking",
    "curious",
    "sad",
    "surprised",
    "sleepy",
    "caring",
    "encouraging",
    "happy",
}

LED_MODES = {
    "off",
    "blue_breath",
    "warm_breath",
    "yellow_blink",
    "rainbow",
    "red_flash",
}

HIGH_LEVEL_ACTIONS = {
    "stay_still",
    "wave_hand",
    "nod",
    "shake_head",
    "point_left",
    "point_right",
    "small_dance",
    "bow",
}


class GameCommandAdapter:
    """Validate fixed game commands and return structured game responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Handle one voice-side game command on the UI/game main thread."""
        normalized = _normalize_command(command)
        error = _command_error(normalized)
        if error is not None:
            return error

        delegated = self._delegate(normalized)
        if delegated is None:
            delegated = _fallback_response(normalized)
        return normalize_game_response(delegated, command=normalized)

    def _delegate(self, command: dict[str, Any]) -> dict[str, Any] | None:
        """Call the real game object when the UI has already attached one."""
        candidates = [
            getattr(self.app, "handle_game_command", None),
            getattr(getattr(self.app, "game", None), "handle_command", None),
            getattr(getattr(self.app, "game_api", None), "handle_command", None),
        ]
        for handler in candidates:
            if not callable(handler):
                continue
            response = handler(deepcopy(command))
            if isinstance(response, dict):
                return response
        return None


def normalize_game_response(
    response: dict[str, Any],
    *,
    command: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a complete game_response with sanitized feedback."""
    command = command or {}
    game_id = str(response.get("game_id") or command.get("game_id") or "").strip()
    intent = str(response.get("intent") or command.get("intent") or "").strip()
    ok = bool(response.get("ok", True))
    message = str(response.get("message", "")).strip()
    if not message:
        message = _message_for_intent(intent, ok=ok)

    state = response.get("state", {})
    if not isinstance(state, dict):
        state = {}

    result: dict[str, Any] = {
        "type": "game_response",
        "ok": ok,
        "game_id": game_id,
        "intent": intent,
        "message": message,
        "state": deepcopy(state),
        "feedback": sanitize_feedback(response.get("feedback", {}), ok=ok),
    }
    error = response.get("error")
    if isinstance(error, dict):
        result["error"] = deepcopy(error)
    elif not ok:
        result["error"] = {"code": "not_available", "detail": message}
    return result


def sanitize_feedback(raw_feedback: Any, *, ok: bool = True) -> dict[str, str]:
    """Keep only high-level whitelisted feedback names."""
    if not isinstance(raw_feedback, dict):
        raw_feedback = {}
    expression = str(
        raw_feedback.get("screen_expression")
        or raw_feedback.get("expression")
        or ("smile" if ok else "thinking")
    ).strip()
    led_mode = str(raw_feedback.get("led_mode") or raw_feedback.get("light") or "").strip()
    action = str(
        raw_feedback.get("action")
        or raw_feedback.get("arm_action")
        or raw_feedback.get("body_action")
        or "stay_still"
    ).strip()

    feedback: dict[str, str] = {}
    if expression in SCREEN_EXPRESSIONS:
        feedback["screen_expression"] = expression
    if led_mode in LED_MODES:
        feedback["led_mode"] = led_mode
    if action in HIGH_LEVEL_ACTIONS:
        feedback["action"] = action
        feedback["arm_action"] = action
    return feedback


def _normalize_command(command: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(command, dict):
        return {"type": "", "game_id": "", "intent": "", "user_text": "", "context": {}}
    context = command.get("context", {})
    if not isinstance(context, dict):
        context = {}
    return {
        "type": str(command.get("type", "")).strip(),
        "game_id": str(command.get("game_id", "")).strip(),
        "intent": str(command.get("intent", "")).strip(),
        "user_text": str(command.get("user_text", "")).strip(),
        "context": deepcopy(context),
    }


def _command_error(command: dict[str, Any]) -> dict[str, Any] | None:
    if command["type"] != "game_command":
        return _error_response(command, "invalid_type", "这个游戏指令格式不对，我们先停一下。")
    if command["game_id"] not in FIXED_GAME_IDS:
        return _error_response(command, "unknown_game", "这个小游戏还没有准备好，我们先换一个玩法。")
    if command["intent"] not in FIXED_GAME_INTENTS:
        return _error_response(command, "unknown_intent", "星宝还没听懂，可以再说一次吗？")
    return None


def _error_response(command: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "type": "game_response",
        "ok": False,
        "game_id": command.get("game_id", ""),
        "intent": command.get("intent", ""),
        "message": message,
        "state": {},
        "feedback": sanitize_feedback({}, ok=False),
        "error": {"code": code, "detail": message},
    }


def _fallback_response(command: dict[str, Any]) -> dict[str, Any]:
    intent = command["intent"]
    state = _default_state(command["game_id"])
    if intent == "restart_round":
        state["round"] = 1
    elif intent == "next_round":
        state["round"] = int(state.get("round", 1)) + 1
    elif intent == "pause_game":
        state["paused"] = True
    elif intent == "exit_game":
        state["exited"] = True

    return {
        "type": "game_response",
        "ok": True,
        "game_id": command["game_id"],
        "intent": intent,
        "message": _message_for_intent(intent, ok=True),
        "state": state,
        "feedback": _feedback_for_intent(intent),
    }


def _default_state(game_id: str) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "level": 1,
        "round": 1,
        "score": 0,
        "stars": 0,
        "total_stars": 0,
        "remaining_rounds": 0,
        "success_count": 0,
        "error_count": 0,
        "attempt_count": 0,
        "level": 1,
        "energy": 0,
        "energy_max": 100,
        "name": _name_for_game(game_id),
        "current_goal": _goal_for_game(game_id),
        "last_result": None,
    }


def _name_for_game(game_id: str) -> str:
    names = {
        "color_game": "找颜色",
        "shape_game": "认形状",
        "memory_game": "记忆小路",
        "counting_game": "数数游戏",
        "english_game": "英语游戏",
        "skill_game": "本领挑战",
    }
    return names.get(game_id, "当前小游戏")


def _goal_for_game(game_id: str) -> str:
    goals = {
        "color_game": "找一找屏幕里的颜色朋友",
        "shape_game": "找一找像目标一样的形状",
        "memory_game": "记住刚才翻开的卡片",
        "counting_game": "数一数有几个",
        "english_game": "听一听这个英文词",
        "skill_game": "跟着提示完成小任务",
    }
    return goals.get(game_id, "完成当前小任务")


def _message_for_intent(intent: str, *, ok: bool) -> str:
    if not ok:
        return "我们先慢慢来，可以再试一次。"
    return {
        "get_rule": "玩法很简单，先看目标，再点你觉得对的地方。",
        "get_goal": "现在先完成屏幕上的这个小目标。",
        "get_hint": "没关系，我们先找最像目标的那个线索。",
        "get_score": "你现在有0分。",
        "get_stars": "你现在有0颗星。",
        "get_progress": "我们正在第一关第一轮，慢慢来就好。",
        "get_remaining": "现在还剩0轮。",
        "get_round": "现在是第1轮。",
        "get_current_game": "我们正在玩当前小游戏。",
        "get_status": "游戏正在进行中，我们慢慢来。",
        "get_level": "星宝现在是1级。",
        "get_energy": "星宝现在有0点能量。",
        "get_correct": "你现在答对了0次。",
        "get_errors": "你现在答错了0次。",
        "get_attempts": "你已经尝试了0次。",
        "repeat_prompt": "我再说一遍，先看目标，再选择最像的那个。",
        "restart_round": "好，我们重新来这一轮。",
        "next_round": "好，准备进入下一轮。",
        "pause_game": "好的，游戏先暂停一下。",
        "exit_game": "好的，我们先退出小游戏。",
    }.get(intent, "我们继续慢慢试。")


def _feedback_for_intent(intent: str) -> dict[str, str]:
    if intent in {
        "get_hint",
        "repeat_prompt",
        "get_goal",
        "get_rule",
        "get_progress",
        "get_remaining",
        "get_round",
        "get_current_game",
        "get_status",
        "get_level",
        "get_energy",
        "get_correct",
        "get_errors",
        "get_attempts",
    }:
        return {
            "screen_expression": "thinking",
            "led_mode": "blue_breath",
            "action": "stay_still",
            "arm_action": "stay_still",
        }
    if intent in {"restart_round", "next_round"}:
        return {
            "screen_expression": "smile",
            "led_mode": "warm_breath",
            "action": "stay_still",
            "arm_action": "stay_still",
        }
    if intent in {"pause_game", "exit_game"}:
        return {
            "screen_expression": "neutral",
            "led_mode": "off",
            "action": "stay_still",
            "arm_action": "stay_still",
        }
    return {
        "screen_expression": "smile",
        "led_mode": "warm_breath",
        "action": "stay_still",
        "arm_action": "stay_still",
    }
