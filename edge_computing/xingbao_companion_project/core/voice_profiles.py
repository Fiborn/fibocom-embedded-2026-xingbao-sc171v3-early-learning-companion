"""Configurable TTS voice profiles for Xingbao."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.settings import AppSettings


DEFAULT_VOICE_PROFILES_PATH = Path("config/voice_profiles.json")
DEFAULT_VOICE_PROFILE_ID = "xingbao_daily"
DEFAULT_QUICK_ACK_TEXT = "星宝收到啦，我想一想。"


@dataclass(frozen=True)
class VoiceProfile:
    """A named TTS personality backed by one DashScope voice setting."""

    id: str
    label: str
    model: str
    voice: str
    sample_rate: int = 24000
    volume: int = 70
    rate: float = 1.0
    quick_ack_text: str = DEFAULT_QUICK_ACK_TEXT
    description: str = ""

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None) -> "VoiceProfile":
        active_settings = settings or AppSettings.load()
        return cls(
            id=DEFAULT_VOICE_PROFILE_ID,
            label="日常星宝",
            model=active_settings.tts_model,
            voice=active_settings.tts_voice,
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any], settings: AppSettings) -> "VoiceProfile":
        profile_id = str(data.get("id", "")).strip()
        if not profile_id:
            raise ValueError("Voice profile id cannot be empty.")
        return cls(
            id=profile_id,
            label=str(data.get("label") or profile_id),
            model=str(data.get("model") or settings.tts_model),
            voice=str(data.get("voice") or settings.tts_voice),
            sample_rate=_int_value(data.get("sample_rate"), 24000),
            volume=_bounded_int(data.get("volume"), 70, minimum=0, maximum=100),
            rate=_bounded_float(data.get("rate"), 1.0, minimum=0.5, maximum=2.0),
            quick_ack_text=str(data.get("quick_ack_text") or DEFAULT_QUICK_ACK_TEXT),
            description=str(data.get("description") or ""),
        )

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "id": self.id,
            "label": self.label,
            "model": self.model,
            "voice": self.voice,
            "sample_rate": self.sample_rate,
            "volume": self.volume,
            "rate": self.rate,
            "description": self.description,
        }


def load_voice_profiles(
    settings: AppSettings | None = None,
    path: Path | str | None = None,
) -> tuple[VoiceProfile, ...]:
    """Load voice profiles from JSON, falling back to settings defaults."""
    active_settings = settings or AppSettings.load()
    profiles_path = Path(path or active_settings.voice_profiles_path)
    if not profiles_path.exists():
        return (VoiceProfile.from_settings(active_settings),)

    data = json.loads(profiles_path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        raw_profiles = data.get("profiles", [])
    else:
        raw_profiles = data
    if not isinstance(raw_profiles, list):
        raise ValueError(f"Expected voice profile list: {profiles_path}")

    profiles = tuple(
        VoiceProfile.from_mapping(item, active_settings)
        for item in raw_profiles
        if isinstance(item, dict)
    )
    if not profiles:
        raise ValueError(f"No usable voice profiles found: {profiles_path}")
    _ensure_unique_ids(profiles)
    return profiles


def select_voice_profile(
    settings: AppSettings | None = None,
    profile_id: str | None = None,
    path: Path | str | None = None,
) -> VoiceProfile:
    active_settings = settings or AppSettings.load()
    profiles = load_voice_profiles(active_settings, path)
    selected_id = (profile_id or active_settings.active_voice_profile).strip()
    if not selected_id:
        selected_id = profiles[0].id
    for profile in profiles:
        if profile.id == selected_id:
            return profile
    available = ", ".join(profile.id for profile in profiles)
    raise ValueError(f"Unknown voice profile '{selected_id}'. Available: {available}")


def _ensure_unique_ids(profiles: tuple[VoiceProfile, ...]) -> None:
    seen: set[str] = set()
    for profile in profiles:
        if profile.id in seen:
            raise ValueError(f"Duplicate voice profile id: {profile.id}")
        seen.add(profile.id)


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _bounded_int(value: Any, fallback: int, *, minimum: int, maximum: int) -> int:
    return min(max(_int_value(value, fallback), minimum), maximum)


def _float_value(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _bounded_float(value: Any, fallback: float, *, minimum: float, maximum: float) -> float:
    return min(max(_float_value(value, fallback), minimum), maximum)
