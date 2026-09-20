"""Shared, local audio preferences for the companion and touch desktop."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_PREFERENCES_PATH = PROJECT_ROOT / "data" / "audio_preferences.json"
DEFAULT_OUTPUT_VOLUME = 100

_LOCK = threading.RLock()


def load_output_volume(
    path: Path | str = DEFAULT_AUDIO_PREFERENCES_PATH,
    *,
    default: int = DEFAULT_OUTPUT_VOLUME,
) -> int:
    """Load the shared playback volume as a bounded percentage."""
    fallback = _bounded_volume(default)
    with _LOCK:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return fallback
    if not isinstance(payload, dict):
        return fallback
    return _bounded_volume(payload.get("volume"), fallback=fallback)


def save_output_volume(
    volume: Any,
    path: Path | str = DEFAULT_AUDIO_PREFERENCES_PATH,
) -> int:
    """Atomically save the shared playback volume."""
    bounded = _bounded_volume(volume)
    target = Path(path)
    with _LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(
            f".{target.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(
            json.dumps({"volume": bounded}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    return bounded


def _bounded_volume(value: Any, *, fallback: int = DEFAULT_OUTPUT_VOLUME) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return max(0, min(100, parsed))
