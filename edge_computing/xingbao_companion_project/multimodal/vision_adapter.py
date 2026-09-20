"""Translate raw vision inference JSON into Xingbao's high-level event protocol.

This adapter deliberately exposes observations only. It never produces servo
angles, GPIO/PWM values, or other low-level hardware commands.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


EMOTION_CODE_TO_LABEL = {
    1: "happiness",
    2: "sadness",
    3: "anger",
    4: "surprise",
    5: "fear",
    6: "disgust",
    7: "contempt",
    8: "neutral",
}


def vision_json_to_flags(payload: dict[str, Any] | None) -> tuple[int, int]:
    """Return the two legacy UI flags without changing their old semantics."""
    safe_payload = payload if isinstance(payload, dict) else {}
    return (
        1 if _integer_code(safe_payload.get("return_code")) == 1 else 0,
        1 if _integer_code(safe_payload.get("drink_return_code")) == 1 else 0,
    )


def vision_json_to_state_events(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Convert one raw frame result to additive, high-level ``vision_state`` events.

    More than one event may be returned because eye distance, continuous use,
    hydration, and emotion are independent signals.
    """
    if not isinstance(payload, dict):
        return []

    events: list[dict[str, Any]] = []
    return_code = _integer_code(payload.get("return_code"))
    if return_code == 1:
        events.append(
            _state_event(
                "face_too_close",
                priority=3,
                confidence=_distance_confidence(payload),
                extra=_distance_context(payload),
            )
        )
    elif return_code == 2:
        events.append(
            _state_event(
                "sitting_too_long",
                priority=3,
                confidence=_face_presence_confidence(payload),
            )
        )

    if _integer_code(payload.get("drink_return_code")) == 1:
        events.append(
            _state_event(
                "drink_water_reminder_due",
                priority=2,
                confidence=1.0,
            )
        )

    emotion_code = _integer_code(payload.get("emotion_return_code"))
    emotion_label = EMOTION_CODE_TO_LABEL.get(emotion_code)
    if emotion_label is not None:
        events.append(
            _state_event(
                "child_emotion_detected",
                priority=1,
                confidence=_emotion_confidence(payload, emotion_code),
                extra={
                    "emotion": emotion_label,
                    "emotion_code": emotion_code,
                },
            )
        )
    return events


@dataclass
class VisionEventAdapter:
    """Debounce frame-level results before sending them to the rest of Xingbao.

    Health reminders are edge-triggered. Emotion must remain unchanged for
    ``emotion_stable_frames`` frames, and the same confirmed emotion is emitted
    only once until the classifier becomes uncertain or changes.
    """

    emotion_stable_frames: int = 3
    emotion_min_interval_seconds: float = 15.0
    emotion_repeat_cooldown_seconds: float = 90.0
    clock: Callable[[], float] = time.monotonic
    _active_health_states: set[str] = field(default_factory=set, init=False)
    _emotion_candidate: int = field(default=0, init=False)
    _emotion_candidate_frames: int = field(default=0, init=False)
    _emitted_emotion: int = field(default=0, init=False)
    _last_emotion_time: float = field(default=float("-inf"), init=False)
    _last_emotion_time_by_code: dict[int, float] = field(
        default_factory=dict,
        init=False,
    )
    _drink_overlap_active: bool = field(default=False, init=False)

    def update(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        raw_events = vision_json_to_state_events(payload)
        health_events = [
            event
            for event in raw_events
            if event["payload"]["state"] != "child_emotion_detected"
        ]
        current_health_states = {
            str(event["payload"]["state"]) for event in health_events
        }
        emitted = [
            event
            for event in health_events
            if event["payload"]["state"] not in self._active_health_states
        ]
        self._active_health_states = current_health_states

        safe_payload = payload if isinstance(payload, dict) else {}
        drink_reminder = safe_payload.get("drink_reminder")
        if not isinstance(drink_reminder, dict):
            drink_reminder = {}
        drink_overlap_now = bool(drink_reminder.get("overlap_now", False))
        if drink_overlap_now and not self._drink_overlap_active:
            emitted.append(
                _state_event(
                    "drink_reminder_reset",
                    priority=0,
                    confidence=1.0,
                )
            )
        self._drink_overlap_active = drink_overlap_now

        emotion_code = _integer_code(safe_payload.get("emotion_return_code"))
        if emotion_code not in EMOTION_CODE_TO_LABEL:
            self._emotion_candidate = 0
            self._emotion_candidate_frames = 0
            self._emitted_emotion = 0
            return emitted

        if emotion_code == self._emotion_candidate:
            self._emotion_candidate_frames += 1
        else:
            self._emotion_candidate = emotion_code
            self._emotion_candidate_frames = 1

        stable_frames = max(1, int(self.emotion_stable_frames))
        now = self.clock()
        same_code_elapsed = now - self._last_emotion_time_by_code.get(
            emotion_code,
            float("-inf"),
        )
        any_emotion_elapsed = now - self._last_emotion_time
        if (
            self._emotion_candidate_frames >= stable_frames
            and self._emitted_emotion != emotion_code
            and same_code_elapsed
            >= max(0.0, float(self.emotion_repeat_cooldown_seconds))
            and any_emotion_elapsed
            >= max(0.0, float(self.emotion_min_interval_seconds))
        ):
            emitted.extend(
                event
                for event in raw_events
                if event["payload"]["state"] == "child_emotion_detected"
            )
            self._emitted_emotion = emotion_code
            self._last_emotion_time = now
            self._last_emotion_time_by_code[emotion_code] = now
        return emitted


def _state_event(
    state: str,
    *,
    priority: int,
    confidence: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "state": state,
        "confidence": _bounded_confidence(confidence),
        "simulated": False,
    }
    if extra:
        payload.update(extra)
    return {
        "type": "vision_state",
        "source": "vision",
        "priority": priority,
        "payload": payload,
    }


def _integer_code(value: Any) -> int:
    return value if type(value) is int else 0


def _bounded_confidence(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(min(1.0, max(0.0, number)), 4)


def _return_status(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("return_status")
    return status if isinstance(status, dict) else {}


def _distance_confidence(payload: dict[str, Any]) -> float:
    status = _return_status(payload)
    threshold_seconds = 2.0
    close_seconds = status.get("close_seconds", threshold_seconds)
    try:
        return min(1.0, float(close_seconds) / threshold_seconds)
    except (TypeError, ValueError):
        return 1.0


def _face_presence_confidence(payload: dict[str, Any]) -> float:
    return _bounded_confidence(
        _return_status(payload).get("face_presence_ratio"),
        default=1.0,
    )


def _distance_context(payload: dict[str, Any]) -> dict[str, Any]:
    distance = _return_status(payload).get("smoothed_distance_m")
    try:
        distance_m = round(max(0.0, float(distance)), 3)
    except (TypeError, ValueError):
        return {}
    return {"distance_m": distance_m}


def _emotion_confidence(payload: dict[str, Any], emotion_code: int) -> float:
    emotions = payload.get("emotions")
    if not isinstance(emotions, list):
        return 1.0
    for item in emotions:
        if not isinstance(item, dict):
            continue
        if _integer_code(item.get("return_code")) == emotion_code:
            return _bounded_confidence(item.get("confidence"), default=1.0)
    return 1.0
