import json
from pathlib import Path

from core.game_speech_cache import GameSpeechCache


def _manifest(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "phrases": [
                    {
                        "id": "game_hub_welcome",
                        "text": "进入游戏啦，请选择一个游戏，再选择难度。",
                        "filename": "game_hub_welcome.wav",
                    },
                    {
                        "id": "difficulty_prompt",
                        "text": "请选择低、中或高难度。",
                        "filename": "difficulty_prompt.wav",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_runtime_path_is_stable_and_voice_specific(tmp_path: Path) -> None:
    cache = GameSpeechCache(
        cache_dir=tmp_path / "cache",
        manifest_path=_manifest(tmp_path / "manifest.json"),
    )

    first = cache.path_for("请找到蓝色在哪里。", "xingbao_daily")
    second = cache.path_for("请找到蓝色在哪里。", "xingbao_daily")
    other_voice = cache.path_for("请找到蓝色在哪里。", "xingbao_soft")

    assert first == second
    assert first != other_voice
    assert first.parent == tmp_path / "cache" / "game_tts"
    assert first.suffix == ".wav"


def test_fixed_phrase_resolves_to_readable_manifest_filename(tmp_path: Path) -> None:
    cache = GameSpeechCache(
        cache_dir=tmp_path / "cache",
        manifest_path=_manifest(tmp_path / "manifest.json"),
    )

    path = cache.resolve_path(
        "进入游戏啦，请选择一个游戏，再选择难度。",
        "xingbao_daily",
    )

    assert path.parent.parent.name == "game_tts"
    assert path.parent.name.startswith("xingbao_daily-")
    assert path.name == "game_hub_welcome.wav"


def test_fixed_phrase_cache_is_voice_specific(tmp_path: Path) -> None:
    cache = GameSpeechCache(
        cache_dir=tmp_path / "cache",
        manifest_path=_manifest(tmp_path / "manifest.json"),
    )

    daily = cache.resolve_path(
        "进入游戏啦，请选择一个游戏，再选择难度。",
        "xingbao_daily",
    )
    soft = cache.resolve_path(
        "进入游戏啦，请选择一个游戏，再选择难度。",
        "xingbao_soft",
    )

    assert daily != soft


def test_manifest_inspection_reports_ready_missing_and_corrupt(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache = GameSpeechCache(
        cache_dir=cache_dir,
        manifest_path=_manifest(tmp_path / "manifest.json"),
        voice_id="xingbao_daily",
    )
    cache.resolve_path(
        "进入游戏啦，请选择一个游戏，再选择难度。",
        "xingbao_daily",
    ).parent.mkdir(parents=True)
    cache.resolve_path(
        "进入游戏啦，请选择一个游戏，再选择难度。",
        "xingbao_daily",
    ).write_bytes(b"R" * 1200)
    cache.resolve_path(
        "请选择低、中或高难度。",
        "xingbao_daily",
    ).write_bytes(b"bad")

    report = cache.inspect_manifest()

    assert report["ok"] is False
    assert report["counts"] == {"total": 2, "ready": 1, "missing": 0, "corrupt": 1}
    assert report["items"][0]["status"] == "ready"
    assert report["items"][1]["status"] == "corrupt"


def test_manifest_inspection_marks_absent_file_missing(tmp_path: Path) -> None:
    cache = GameSpeechCache(
        cache_dir=tmp_path / "cache",
        manifest_path=_manifest(tmp_path / "manifest.json"),
    )

    report = cache.inspect_manifest()

    assert report["counts"] == {"total": 2, "ready": 0, "missing": 2, "corrupt": 0}
    assert {item["status"] for item in report["items"]} == {"missing"}
