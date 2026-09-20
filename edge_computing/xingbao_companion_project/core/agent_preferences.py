"""Shared parent-controlled preferences for the live-information agent."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_AGENT_PREFERENCES_PATH = Path("data/agent_preferences.json")


def load_agent_city(path: Path | str, fallback: str) -> str:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        payload = {}
    city = str(payload.get("weather_city", "")).strip() if isinstance(payload, dict) else ""
    return city or fallback
