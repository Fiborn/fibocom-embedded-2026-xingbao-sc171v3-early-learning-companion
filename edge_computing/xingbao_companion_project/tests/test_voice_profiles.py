import json
from pathlib import Path

import pytest

from core.settings import AppSettings
from core.voice_profiles import load_voice_profiles, select_voice_profile


def test_load_voice_profiles_from_config() -> None:
    profiles = load_voice_profiles(AppSettings.load())

    assert any(profile.id == "xingbao_daily" for profile in profiles)
    assert any(profile.id == "xingbao_soft" for profile in profiles)


def test_select_voice_profile_by_id(tmp_path: Path) -> None:
    profile_path = tmp_path / "voices.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "daily",
                        "label": "Daily",
                        "voice": "longanyang",
                    },
                    {
                        "id": "story",
                        "label": "Story",
                        "voice": "longxiaoxia",
                        "rate": 0.9,
                        "volume": 66,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(voice_profiles_path=str(profile_path))

    profile = select_voice_profile(settings, "story")

    assert profile.id == "story"
    assert profile.voice == "longxiaoxia"
    assert profile.rate == 0.9
    assert profile.volume == 66


def test_select_voice_profile_rejects_unknown_id(tmp_path: Path) -> None:
    profile_path = tmp_path / "voices.json"
    profile_path.write_text(
        json.dumps({"profiles": [{"id": "daily", "voice": "longanyang"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown voice profile"):
        select_voice_profile(
            AppSettings(voice_profiles_path=str(profile_path)),
            "missing",
        )
