"""Action whitelist and sanitizer for high-level companion actions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ACTION_SCHEMA_PATH = Path("config/action_schema.json")
DEFAULT_SCREEN_EXPRESSION = "neutral"
DEFAULT_LED_MODE = "off"
DEFAULT_ARM_ACTION = "stay_still"

_RAW_HARDWARE_MARKERS = (
    "servo",
    "angle",
    "pwm",
    "serial",
    "uart",
    "com",
    "gpio",
    "舵机",
    "角度",
    "串口",
    "引脚",
)


@dataclass(frozen=True)
class SafeAction:
    """A sanitized high-level action bundle."""

    screen_expression: str = DEFAULT_SCREEN_EXPRESSION
    led_mode: str = DEFAULT_LED_MODE
    arm_action: str = DEFAULT_ARM_ACTION

    def as_dict(self) -> dict[str, str]:
        action: dict[str, str] = {}
        if self.screen_expression != DEFAULT_SCREEN_EXPRESSION:
            action["screen_expression"] = self.screen_expression
        if self.arm_action != DEFAULT_ARM_ACTION:
            action["arm_action"] = self.arm_action
        if self.led_mode != DEFAULT_LED_MODE:
            action["led_mode"] = self.led_mode
        return action


@dataclass(frozen=True)
class ActionSchema:
    """Whitelist loaded from config/action_schema.json."""

    screen_expressions: frozenset[str]
    led_modes: frozenset[str]
    arm_actions: frozenset[str]

    @classmethod
    def load(cls, path: Path | str = DEFAULT_ACTION_SCHEMA_PATH) -> "ActionSchema":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Action schema must be a JSON object.")
        return cls(
            screen_expressions=frozenset(
                _string_list(data.get("screen_expressions", data.get("faces", [])))
            ),
            led_modes=frozenset(_string_list(data.get("led_modes", []))),
            arm_actions=frozenset(_string_list(data.get("arm_actions", []))),
        )


class ActionSanitizer:
    """Converts untrusted action proposals into whitelisted high-level actions."""

    def __init__(self, schema: ActionSchema | None = None) -> None:
        self.schema = schema or ActionSchema.load()

    def sanitize(self, proposal: SafeAction | dict[str, Any] | str | None) -> SafeAction:
        if isinstance(proposal, SafeAction):
            raw = proposal.as_dict()
        elif isinstance(proposal, dict):
            raw = proposal
        elif isinstance(proposal, str):
            raw = {"arm_action": proposal}
        else:
            raw = {}

        screen_expression = self._safe_value(
            raw.get("screen_expression", raw.get("face")),
            self.schema.screen_expressions,
            DEFAULT_SCREEN_EXPRESSION,
        )
        arm_action = self._safe_value(
            raw.get("arm_action"),
            self.schema.arm_actions,
            DEFAULT_ARM_ACTION,
        )
        led_mode = self._safe_value(raw.get("led_mode"), self.schema.led_modes, DEFAULT_LED_MODE)

        if arm_action != DEFAULT_ARM_ACTION:
            led_mode = DEFAULT_LED_MODE

        return SafeAction(
            screen_expression=screen_expression,
            led_mode=led_mode,
            arm_action=arm_action,
        )

    def _safe_value(self, value: Any, allowed: frozenset[str], fallback: str) -> str:
        if not isinstance(value, str):
            return fallback
        cleaned = value.strip()
        if not cleaned or _looks_like_raw_hardware(cleaned):
            return fallback
        return cleaned if cleaned in allowed else fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _looks_like_raw_hardware(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in _RAW_HARDWARE_MARKERS):
        return True
    return bool(re.search(r"\b\d{2,3}\s*(?:deg|degree|degrees|°)\b", lowered))
