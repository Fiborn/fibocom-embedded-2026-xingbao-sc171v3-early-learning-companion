from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.settings import AppSettings
from multimodal.wake_word import OPENWAKEWORD_FRAME_SAMPLES, OpenWakeWordDetector, WakeWordConfig


def make_wake_config(tmp_path: Path, *, threshold: float = 0.5) -> WakeWordConfig:
    model_path = tmp_path / "xingbao.tflite"
    model_path.write_bytes(b"tflite")
    feature_dir = tmp_path / "openwakeword"
    feature_dir.mkdir()
    (feature_dir / "melspectrogram.tflite").write_bytes(b"melspec")
    (feature_dir / "embedding_model.tflite").write_bytes(b"embedding")
    return WakeWordConfig(model_path=model_path, threshold=threshold)


class FakeModel:
    scores: list[float] = [0.6]
    received: list[np.ndarray] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def predict(self, audio: np.ndarray) -> dict[str, float]:
        type(self).received.append(audio.copy())
        return {"xingbao": type(self).scores.pop(0) if type(self).scores else 0.0}


class FakeRawInputStream:
    def __init__(self, callback: Any, blocksize: int, **_kwargs: Any) -> None:
        self.callback = callback
        self.blocksize = blocksize

    def __enter__(self) -> "FakeRawInputStream":
        for _ in range(2):
            samples = np.zeros(self.blocksize, dtype=np.int16)
            self.callback(samples.tobytes(), self.blocksize, None, None)
        return self

    def __exit__(self, *_args: Any) -> None:
        pass


class FakeSoundDevice:
    RawInputStream = FakeRawInputStream


def test_wake_word_config_uses_bundled_openwakeword_model() -> None:
    config = WakeWordConfig.from_settings(AppSettings(), input_device=5)

    assert config.model_path == Path("model_voice/xingbao.tflite")
    assert config.input_device == 5
    assert config.threshold == 0.5
    assert config.sample_rate == 16000


def test_wake_word_config_reports_missing_model(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="model files"):
        WakeWordConfig(model_path=tmp_path / "xingbao.tflite").validate_files()


def test_detector_waits_for_openwakeword_score_above_threshold(tmp_path: Path) -> None:
    FakeModel.scores = [0.6]
    FakeModel.received = []
    detector = OpenWakeWordDetector(
        make_wake_config(tmp_path, threshold=0.5),
        model_class=FakeModel,
        sounddevice_module=FakeSoundDevice,
        numpy_module=np,
    )

    assert detector.wait_for_wake_word() == "星宝星宝"
    assert len(FakeModel.received) == 1
    assert FakeModel.received[0].size == OPENWAKEWORD_FRAME_SAMPLES
    assert detector._get_model().kwargs["wakeword_models"] == [str(tmp_path / "xingbao.tflite")]
    assert detector._get_model().kwargs["inference_framework"] == "tflite"
    assert detector._get_model().kwargs["melspec_model_path"] == str(tmp_path / "openwakeword/melspectrogram.tflite")


def test_score_equal_to_point_five_does_not_wake(tmp_path: Path) -> None:
    FakeModel.scores = [0.5]
    detector = OpenWakeWordDetector(make_wake_config(tmp_path), model_class=FakeModel, numpy_module=np)

    assert detector.detect_pcm_frame(np.zeros(OPENWAKEWORD_FRAME_SAMPLES, dtype=np.int16).tobytes()) == ""


def test_runtime_never_allows_a_threshold_below_point_five(tmp_path: Path) -> None:
    FakeModel.scores = [0.4]
    detector = OpenWakeWordDetector(
        make_wake_config(tmp_path, threshold=0.1), model_class=FakeModel, numpy_module=np
    )

    assert detector.detect_pcm_frame(np.zeros(OPENWAKEWORD_FRAME_SAMPLES, dtype=np.int16).tobytes()) == ""


def test_detector_checks_recorded_wav_offline(tmp_path: Path) -> None:
    wav_path = tmp_path / "wake.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(np.zeros(OPENWAKEWORD_FRAME_SAMPLES, dtype=np.int16).tobytes())
    FakeModel.scores = [0.7]
    detector = OpenWakeWordDetector(make_wake_config(tmp_path), model_class=FakeModel, numpy_module=np)

    assert detector.detect_wav(wav_path) == ["星宝星宝"]
