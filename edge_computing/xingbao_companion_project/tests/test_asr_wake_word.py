from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from core.settings import AppSettings
from multimodal.asr_wake_word import ASRWakeWordDetector
from multimodal.vad import NoSpeechTimeout


class _NoLocalKeyword:
    def detect_wav(self, _path: Path) -> list[str]:
        return []


def test_wake_name_match_tolerates_limited_phonetic_asr_variants() -> None:
    assert ASRWakeWordDetector._wake_match_reason("小星宝在吗") == "exact_alias"
    assert ASRWakeWordDetector._wake_match_reason("小新保在吗") == "phonetic_name"
    assert ASRWakeWordDetector._wake_match_reason("xingbao，你在吗") == "pinyin_alias"
    assert ASRWakeWordDetector._wake_match_reason("视频的声音有点大") is None


def test_wake_match_detail_logs_only_whitelisted_keyword() -> None:
    from multimodal.asr_wake_word import _wake_match_detail

    assert _wake_match_detail("小新保在吗") == ("phonetic_name", "新保")
    assert _wake_match_detail("xingbao，你在吗") == ("pinyin_alias", "xingbao")
    assert _wake_match_detail("我想说一个不相关的句子") == (None, "none")


def test_local_keyword_wakes_without_calling_cloud_asr(tmp_path: Path) -> None:
    wav_path = tmp_path / "wake.wav"
    wav_path.write_bytes(b"pcm")
    captured_configs: list[Any] = []

    class LocalKeyword:
        def detect_wav(self, _path: Path) -> list[str]:
            return ["星宝星宝"]

    class CloudASR:
        def transcribe(self, _path: Path) -> str:
            raise AssertionError("cloud ASR must not be called after a local KWS hit")

    def capture(**kwargs: Any) -> tuple[Path, dict[str, float]]:
        captured_configs.append(kwargs["vad_config"])
        return wav_path, {"utterance_ms": 600.0}

    detector = ASRWakeWordDetector(
        AppSettings(),
        capture=capture,
        offline_detector=LocalKeyword(),
        asr_factory=lambda _settings: CloudASR(),
    )

    assert detector.wait_for_wake_word(announce=False) == "星宝星宝"
    assert captured_configs[0].start_requires_rms is False


def test_wake_vad_uses_configured_rms_log_interval(monkeypatch, tmp_path: Path) -> None:
    wav_path = tmp_path / "wake.wav"
    wav_path.write_bytes(b"pcm")
    captured_configs: list[Any] = []
    monkeypatch.setenv("XINGBAO_ASR_WAKE_RMS_LOG_INTERVAL_MS", "250")

    stop_event = threading.Event()

    def capture(**kwargs: Any) -> tuple[Path, dict[str, float]]:
        captured_configs.append(kwargs["vad_config"])
        stop_event.set()
        raise NoSpeechTimeout("test stop")

    detector = ASRWakeWordDetector(
        AppSettings(),
        capture=capture,
        offline_detector=_NoLocalKeyword(),
    )
    detector.wait_for_wake_word(stop_event=stop_event, announce=False)

    assert captured_configs[-1].debug_level_interval_ms == 250.0


def test_cloud_asr_uses_phonetic_name_match_after_local_miss(tmp_path: Path) -> None:
    wav_path = tmp_path / "wake.wav"
    wav_path.write_bytes(b"pcm")

    class CloudASR:
        def transcribe(self, _path: Path) -> str:
            return "小新保在吗"

    detector = ASRWakeWordDetector(
        AppSettings(),
        capture=lambda **_kwargs: (wav_path, {"utterance_ms": 600.0}),
        offline_detector=_NoLocalKeyword(),
        asr_factory=lambda _settings: CloudASR(),
    )

    assert detector.wait_for_wake_word(announce=False) == "星宝星宝"


def test_cloud_asr_debug_logs_metadata_without_transcript(tmp_path: Path, capsys) -> None:
    wav_path = tmp_path / "wake.wav"
    wav_path.write_bytes(b"pcm")

    class CloudASR:
        def transcribe(self, _path: Path) -> str:
            return "与唤醒词无关的儿童原始语句"

    detector = ASRWakeWordDetector(AppSettings(), asr_factory=lambda _settings: CloudASR())

    text, timed_out, error = detector._transcribe_with_deadline(
        detector._asr_factory,
        wav_path,
        source="primary",
    )
    output = capsys.readouterr().out

    assert text == "与唤醒词无关的儿童原始语句"
    assert timed_out is False
    assert error is None
    assert "recognition_started source=primary" in output
    assert "recognized_chars=" in output
    assert "儿童原始语句" not in output


def test_realtime_local_keyword_interrupts_vad_before_cloud_asr() -> None:
    class LocalKeyword:
        def prepare_live_detection(self) -> None:
            pass

        def detect_pcm_frame(self, _frame: bytes, **_kwargs: Any) -> str:
            return "星宝星宝"

        def detect_wav(self, _path: Path) -> list[str]:
            raise AssertionError("WAV fallback must not run after a realtime hit")

    class CloudASR:
        def transcribe(self, _path: Path) -> str:
            raise AssertionError("cloud ASR must not run after a realtime KWS hit")

    def capture(**kwargs: Any) -> tuple[Path, dict[str, float]]:
        kwargs["audio_frame_callback"](b"pcm")
        assert kwargs["stop_event"].is_set()
        raise NoSpeechTimeout("interrupted by a local KWS hit")

    detector = ASRWakeWordDetector(
        AppSettings(),
        capture=capture,
        offline_detector=LocalKeyword(),
        asr_factory=lambda _settings: CloudASR(),
    )

    assert detector.wait_for_wake_word(announce=False) == "星宝星宝"
