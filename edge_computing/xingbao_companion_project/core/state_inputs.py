"""Reserved state-input normalization for mini games and vision modules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


MINI_GAME_STATE_TYPE = "mini_game_state"
VISION_STATE_TYPE = "vision_state"
GAME_RESPONSE_TYPE = "game_response"


def normalize_state_input(raw_event: dict[str, Any]) -> dict[str, Any]:
    """Convert reserved state-input envelopes into expression protocol events."""
    event_type = str(raw_event.get("type", "")).strip()
    if event_type == MINI_GAME_STATE_TYPE:
        return _normalize_mini_game_state(raw_event)
    if event_type == VISION_STATE_TYPE:
        return _normalize_vision_state(raw_event)
    if event_type == GAME_RESPONSE_TYPE:
        return _normalize_game_response(raw_event)
    if event_type == "game_event" and "payload" not in raw_event:
        return _normalize_top_level_game_event(raw_event)
    return raw_event


def is_state_input(raw_event: dict[str, Any]) -> bool:
    """Return whether the event is one of the reserved state-input envelopes."""
    return str(raw_event.get("type", "")).strip() in {
        MINI_GAME_STATE_TYPE,
        VISION_STATE_TYPE,
        GAME_RESPONSE_TYPE,
    }


def _normalize_mini_game_state(raw_event: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(raw_event)
    state = _state(payload)
    feedback = payload.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {}

    text = str(payload.get("message", "")).strip()
    if text:
        return _expression_request(
            raw_event,
            intent=_mini_game_intent(state),
            text=text,
            screen_text=str(payload.get("screen_text") or text[:24]).strip(),
            emotion=str(
                feedback.get("expression")
                or feedback.get("emotion")
                or _mini_game_emotion(state)
            ),
            tts=bool(feedback.get("tts", True)),
            source="mini_game",
            extra_payload=_mini_game_context(payload, state),
        )

    mapped_event = _MINI_GAME_EVENT_MAP.get(state)
    if mapped_event is not None:
        normalized_payload = _mini_game_context(payload, state)
        normalized_payload["event"] = mapped_event
        return _protocol_event(
            raw_event,
            event_type="game_event",
            source="mini_game",
            payload=normalized_payload,
        )

    return _expression_request(
        raw_event,
        intent=_mini_game_intent(state),
        text=_MINI_GAME_SPEECH.get(
            state,
            "\u6211\u6536\u5230\u5c0f\u6e38\u620f\u7684\u65b0\u72b6\u6001\u4e86\uff0c\u6211\u4eec\u6162\u6162\u7ee7\u7eed\u3002",
        ),
        screen_text=_MINI_GAME_SCREEN.get(state, "\u7ee7\u7eed"),
        emotion=_mini_game_emotion(state),
        tts=True,
        source="mini_game",
        extra_payload=_mini_game_context(payload, state),
    )


def _normalize_vision_state(raw_event: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(raw_event)
    state = _state(payload)

    if state == "child_emotion_detected":
        detected_emotion = str(payload.get("emotion", "")).strip().lower()
        template = _VISION_EMOTION_RESPONSE.get(
            detected_emotion,
            _VISION_EMOTION_RESPONSE["neutral"],
        )
        context = _vision_context(payload, state)
        context["feedback"] = {
            "screen_expression": str(template["screen_expression"]),
            "led_mode": str(template["led_mode"]),
            "arm_action": str(template["arm_action"]),
        }
        return _expression_request(
            raw_event,
            intent="observe_child_emotion",
            text=str(template["text"]),
            screen_text=str(template["screen_text"]),
            emotion=str(template["expression"]),
            tts=bool(template["tts"]),
            priority=max(
                _priority(raw_event.get("priority")),
                int(template["priority"]),
            ),
            source="vision",
            extra_payload=context,
        )

    mapped_event = _VISION_EVENT_MAP.get(state, state)
    if state in _VISION_SILENT_EXPRESSION:
        template = _VISION_SILENT_EXPRESSION[state]
        return _expression_request(
            raw_event,
            intent=str(template["intent"]),
            text=str(template.get("text", "")),
            screen_text=str(template.get("screen_text", "")),
            emotion=str(template.get("emotion", "calm")),
            tts=bool(template.get("tts", False)),
            priority=int(template.get("priority", raw_event.get("priority", 1))),
            source="vision",
            extra_payload=_vision_context(payload, state),
        )

    normalized_payload = _vision_context(payload, state)
    normalized_payload["event"] = mapped_event
    return _protocol_event(
        raw_event,
        event_type="vision_event",
        source="vision",
        payload=normalized_payload,
    )


def _normalize_game_response(raw_event: dict[str, Any]) -> dict[str, Any]:
    feedback = raw_event.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {}
    text = str(raw_event.get("message", "")).strip()
    intent = str(raw_event.get("intent") or "game_response").strip()
    expression = str(
        feedback.get("screen_expression")
        or feedback.get("expression")
        or ("smile" if raw_event.get("ok", True) else "thinking")
    ).strip()
    return _expression_request(
        raw_event,
        intent=intent,
        text=text,
        screen_text=text[:24] if text else "\u5c0f\u6e38\u620f",
        emotion=_safe_expression(expression),
        tts=bool(text),
        source="game",
        extra_payload={
            "game_id": str(raw_event.get("game_id", "")).strip(),
            "game_intent": intent,
            "game_ok": bool(raw_event.get("ok", True)),
            "game_state": raw_event.get("state", {})
            if isinstance(raw_event.get("state"), dict)
            else {},
            "feedback": _sanitize_feedback(feedback),
        },
    )


def _normalize_top_level_game_event(raw_event: dict[str, Any]) -> dict[str, Any]:
    event_name = str(raw_event.get("event", "")).strip()
    message = str(raw_event.get("message", "")).strip()
    feedback = raw_event.get("feedback", {})
    if not isinstance(feedback, dict):
        feedback = {}
    if message:
        return _expression_request(
            raw_event,
            intent=_TOP_LEVEL_GAME_EVENT_INTENTS.get(event_name, event_name or "game_event"),
            text=message,
            screen_text=message[:24],
            emotion=_safe_expression(
                str(feedback.get("screen_expression") or feedback.get("expression") or "smile")
            ),
            tts=True,
            source="game",
            extra_payload={
                "game_id": str(raw_event.get("game_id", "")).strip(),
                "state": str(raw_event.get("event", "")).strip(),
                "game_state": raw_event.get("state", {})
                if isinstance(raw_event.get("state"), dict)
                else {},
                "feedback": _sanitize_feedback(feedback),
            },
        )

    mapped_payload = {
        "event": _TOP_LEVEL_GAME_EVENT_MAP.get(event_name, event_name),
        "game_id": str(raw_event.get("game_id", "")).strip() or "new_mini_game",
        "state": event_name,
        "data": raw_event.get("state", {}) if isinstance(raw_event.get("state"), dict) else {},
        "feedback": _sanitize_feedback(feedback),
    }
    return _protocol_event(
        raw_event,
        event_type="game_event",
        source="game",
        payload=mapped_payload,
    )


def _protocol_event(
    raw_event: dict[str, Any],
    *,
    event_type: str,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    result = _base_event(raw_event, event_type=event_type, source=source)
    result["payload"] = payload
    return result


def _expression_request(
    raw_event: dict[str, Any],
    *,
    intent: str,
    text: str,
    screen_text: str,
    emotion: str,
    source: str,
    tts: bool,
    extra_payload: dict[str, Any],
    priority: int | None = None,
) -> dict[str, Any]:
    result = _base_event(
        raw_event,
        event_type="xingbao_expression_request",
        source=source,
        priority=priority,
    )
    payload = {
        "intent": intent,
        "text": text,
        "screen_text": screen_text,
        "emotion": emotion,
        "tts": tts,
        "interrupt_policy": "queue",
    }
    payload.update(extra_payload)
    result["payload"] = payload
    return result


def _base_event(
    raw_event: dict[str, Any],
    *,
    event_type: str,
    source: str,
    priority: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": event_type,
        "source": str(raw_event.get("source") or source).strip() or source,
        "priority": _priority(priority if priority is not None else raw_event.get("priority")),
    }
    for key in ("event_id", "timestamp"):
        value = raw_event.get(key)
        if value:
            result[key] = value
    return result


def _payload(raw_event: dict[str, Any]) -> dict[str, Any]:
    payload = raw_event.get("payload", {})
    return deepcopy(payload) if isinstance(payload, dict) else {}


def _state(payload: dict[str, Any]) -> str:
    return str(payload.get("state") or payload.get("event") or "").strip()


def _priority(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(0, min(3, value))


def _mini_game_context(payload: dict[str, Any], state: str) -> dict[str, Any]:
    return {
        "game_id": str(payload.get("game_id", "")).strip() or "new_mini_game",
        "state": state,
        "confidence": payload.get("confidence", 1.0),
        "progress": payload.get("progress", {}),
        "data": payload.get("data", {}),
    }


def _vision_context(payload: dict[str, Any], state: str) -> dict[str, Any]:
    result = {
        "state": state,
        "confidence": payload.get("confidence", 1.0),
        "duration_seconds": payload.get("duration_seconds", 0),
        "zone": payload.get("zone", ""),
        "simulated": bool(payload.get("simulated", False)),
    }
    object_id = payload.get("object_id")
    if object_id:
        result["object_id"] = object_id
    detected_emotion = str(payload.get("emotion", "")).strip().lower()
    if detected_emotion in _VISION_EMOTION_RESPONSE:
        result["detected_emotion"] = detected_emotion
    emotion_code = payload.get("emotion_code")
    if type(emotion_code) is int and 0 <= emotion_code <= 8:
        result["emotion_code"] = emotion_code
    distance_m = payload.get("distance_m")
    if isinstance(distance_m, (int, float)) and not isinstance(distance_m, bool):
        result["distance_m"] = max(0.0, float(distance_m))
    return result


def _sanitize_feedback(feedback: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    expression = _safe_expression(
        str(feedback.get("screen_expression") or feedback.get("expression") or "")
    )
    if expression:
        result["screen_expression"] = expression
    led_mode = str(feedback.get("led_mode") or feedback.get("light") or "").strip()
    if led_mode in _LED_MODES:
        result["led_mode"] = led_mode
    action = str(
        feedback.get("action")
        or feedback.get("arm_action")
        or feedback.get("body_action")
        or ""
    ).strip()
    if action in _HIGH_LEVEL_ACTIONS:
        result["action"] = action
        result["arm_action"] = action
    return result


def _safe_expression(expression: str) -> str:
    return expression if expression and expression in _SCREEN_EXPRESSIONS else "smile"


def _mini_game_intent(state: str) -> str:
    return _MINI_GAME_INTENTS.get(state, "mini_game_state")


def _mini_game_emotion(state: str) -> str:
    return _MINI_GAME_EMOTIONS.get(state, "smile")


_MINI_GAME_EVENT_MAP = {
    "game_started": "game_started",
    "round_started": "game_started",
    "child_made_mistake": "child_made_mistake",
    "game_finished": "game_finished",
}

_MINI_GAME_INTENTS = {
    "child_succeeded": "celebrate_success",
    "child_answered": "acknowledge_answer",
    "hint_requested": "hint",
    "idle_timeout": "gentle_prompt",
}

_MINI_GAME_EMOTIONS = {
    "child_succeeded": "happy",
    "child_answered": "smile",
    "hint_requested": "thinking",
    "idle_timeout": "calm",
}

_MINI_GAME_SPEECH = {
    "child_succeeded": "\u505a\u5f97\u597d\uff0c\u661f\u5b9d\u770b\u5230\u4f60\u8bd5\u51fa\u6765\u4e86\u3002",
    "child_answered": "\u6211\u770b\u5230\u4f60\u7684\u7b54\u6848\u4e86\uff0c\u6211\u4eec\u7ee7\u7eed\u770b\u4e0b\u4e00\u6b65\u3002",
    "hint_requested": "\u661f\u5b9d\u7ed9\u4f60\u4e00\u4e2a\u5c0f\u63d0\u793a\uff0c\u5148\u627e\u6700\u50cf\u7684\u90a3\u4e00\u4e2a\u3002",
    "idle_timeout": "\u6ca1\u5173\u7cfb\uff0c\u6211\u4eec\u4e0d\u7740\u6025\uff0c\u4f60\u53ef\u4ee5\u5148\u70b9\u4e00\u4e0b\u60f3\u8bd5\u7684\u5730\u65b9\u3002",
}

_MINI_GAME_SCREEN = {
    "child_succeeded": "\u505a\u5f97\u597d",
    "child_answered": "\u7ee7\u7eed",
    "hint_requested": "\u5c0f\u63d0\u793a",
    "idle_timeout": "\u6162\u6162\u6765",
}

_VISION_EVENT_MAP = {
    "child_returned": "child_returned",
    "face_too_close": "face_too_close",
    "sitting_too_long": "sitting_too_long",
    "drink_water_reminder_due": "drink_water_reminder_due",
    "camera_blocked": "camera_blocked",
    "posture_too_low": "face_too_close",
}

_VISION_SILENT_EXPRESSION = {
    "child_present": {
        "intent": "child_present",
        "screen_text": "\u770b\u5230\u4f60\u5566",
        "emotion": "smile",
        "tts": False,
    },
    "child_left_seat": {
        "intent": "wait_for_child",
        "screen_text": "\u661f\u5b9d\u7b49\u4f60\u56de\u6765",
        "emotion": "calm",
        "tts": False,
    },
    "object_detected": {
        "intent": "tabletop_object_seen",
        "screen_text": "\u770b\u5230\u684c\u9762\u7269\u4f53",
        "emotion": "curious",
        "tts": False,
    },
}

_VISION_EMOTION_RESPONSE = {
    "happiness": {
        "text": "\u770b\u5230\u4f60\u5f00\u5fc3\uff0c\u661f\u5b9d\u4e5f\u5f88\u5f00\u5fc3\u3002",
        "screen_text": "\u661f\u5b9d\u4e5f\u5f00\u5fc3",
        "expression": "happy",
        "screen_expression": "smile",
        "led_mode": "warm_breath",
        "arm_action": "stay_still",
        "tts": True,
        "priority": 1,
    },
    "sadness": {
        "text": "\u5982\u679c\u4f60\u73b0\u5728\u6709\u70b9\u96be\u8fc7\uff0c\u661f\u5b9d\u5728\u8fd9\u91cc\u966a\u4f60\u3002",
        "screen_text": "\u661f\u5b9d\u966a\u7740\u4f60",
        "expression": "caring",
        "screen_expression": "smile",
        "led_mode": "blue_breath",
        "arm_action": "shake_head",
        "tts": True,
        "priority": 2,
    },
    "anger": {
        "text": "\u5982\u679c\u4f60\u73b0\u5728\u6709\u70b9\u751f\u6c14\uff0c\u6211\u4eec\u53ef\u4ee5\u5148\u6162\u6162\u547c\u5438\u3002",
        "screen_text": "\u6162\u6162\u547c\u5438",
        "expression": "caring",
        "screen_expression": "neutral",
        "led_mode": "blue_breath",
        "arm_action": "stay_still",
        "tts": True,
        "priority": 2,
    },
    "surprise": {
        "text": "\u54c7\uff0c\u662f\u4e0d\u662f\u53d1\u73b0\u4e86\u65b0\u4e1c\u897f\uff1f",
        "screen_text": "\u53d1\u73b0\u65b0\u4e1c\u897f\u5566",
        "expression": "surprised",
        "screen_expression": "surprised",
        "led_mode": "warm_breath",
        "arm_action": "stay_still",
        "tts": True,
        "priority": 1,
    },
    "fear": {
        "text": "\u5982\u679c\u4f60\u6709\u70b9\u5bb3\u6015\uff0c\u661f\u5b9d\u5728\u8fd9\u91cc\uff0c\u6211\u4eec\u6162\u6162\u6765\u3002",
        "screen_text": "\u661f\u5b9d\u5728\u8fd9\u91cc",
        "expression": "caring",
        "screen_expression": "smile",
        "led_mode": "blue_breath",
        "arm_action": "shake_head",
        "tts": True,
        "priority": 2,
    },
    "disgust": {
        "text": "",
        "screen_text": "\u6211\u4eec\u53ef\u4ee5\u6362\u4e00\u4e2a",
        "expression": "neutral",
        "screen_expression": "neutral",
        "led_mode": "blue_breath",
        "arm_action": "stay_still",
        "tts": False,
        "priority": 1,
    },
    "contempt": {
        "text": "",
        "screen_text": "\u661f\u5b9d\u5728\u8ba4\u771f\u542c",
        "expression": "neutral",
        "screen_expression": "neutral",
        "led_mode": "off",
        "arm_action": "stay_still",
        "tts": False,
        "priority": 1,
    },
    "neutral": {
        "text": "",
        "screen_text": "\u661f\u5b9d\u5728\u966a\u7740\u4f60",
        "expression": "smile",
        "screen_expression": "smile",
        "led_mode": "off",
        "arm_action": "stay_still",
        "tts": False,
        "priority": 1,
    },
}

_TOP_LEVEL_GAME_EVENT_MAP = {
    "game_started": "game_started",
    "round_started": "game_started",
    "answer_correct": "game_finished",
    "answer_wrong": "child_made_mistake",
    "hint_used": "game_started",
    "round_completed": "game_finished",
    "game_completed": "game_finished",
    "idle_timeout": "idle_timeout",
    "game_paused": "game_started",
    "game_exited": "game_finished",
}

_TOP_LEVEL_GAME_EVENT_INTENTS = {
    "answer_correct": "celebrate_success",
    "answer_wrong": "encourage_retry",
    "hint_used": "hint",
    "idle_timeout": "gentle_prompt",
    "game_paused": "pause_game",
    "game_exited": "exit_game",
}

_SCREEN_EXPRESSIONS = {
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

_LED_MODES = {
    "off",
    "blue_breath",
    "warm_breath",
    "yellow_blink",
    "rainbow",
    "red_flash",
}

_HIGH_LEVEL_ACTIONS = {
    "stay_still",
    "wave_hand",
    "nod",
    "shake_head",
    "point_left",
    "point_right",
    "small_dance",
    "bow",
}
