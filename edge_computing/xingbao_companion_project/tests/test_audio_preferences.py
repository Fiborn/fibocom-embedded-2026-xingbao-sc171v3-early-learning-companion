from pathlib import Path

from core.audio_preferences import load_output_volume, save_output_volume


def test_audio_preferences_round_trip_and_clamp(tmp_path: Path) -> None:
    path = tmp_path / "audio_preferences.json"

    assert load_output_volume(path, default=65) == 65
    assert save_output_volume(140, path) == 100
    assert load_output_volume(path) == 100
    assert save_output_volume(-5, path) == 0
    assert load_output_volume(path) == 0
