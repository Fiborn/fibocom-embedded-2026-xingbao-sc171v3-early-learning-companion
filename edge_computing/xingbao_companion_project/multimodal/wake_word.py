"""Offline wake-word detection using the bundled openWakeWord TFLite model."""

from __future__ import annotations

import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.settings import AppSettings
from multimodal.audio_io import AudioDeviceConfig, import_numpy, open_raw_input_stream


OPENWAKEWORD_FRAME_SAMPLES = 1280
MELSPECTROGRAM_FILENAME = "melspectrogram.tflite"
EMBEDDING_FILENAME = "embedding_model.tflite"


@dataclass(frozen=True)
class WakeWordConfig:
    """Runtime options for the project's custom openWakeWord model."""

    model_path: Path
    wake_word: str = "星宝星宝"
    input_device: int | None = None
    sample_rate: int = 16000
    model_sample_rate: int = 16000
    samples_per_read: int = 800
    threshold: float = 0.5

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        input_device: int | None = None,
        threshold: float | None = None,
    ) -> "WakeWordConfig":
        input_sample_rate = settings.record_sample_rate
        samples_per_read = settings.wake_word_samples_per_read
        if input_sample_rate != 16000:
            samples_per_read = max(1, int(round(samples_per_read * input_sample_rate / 16000)))
        return cls(
            model_path=Path(settings.wake_word_model_path),
            wake_word=settings.wake_word,
            input_device=input_device,
            sample_rate=input_sample_rate,
            samples_per_read=samples_per_read,
            threshold=settings.wake_word_threshold if threshold is None else threshold,
        )

    def validate_files(self) -> None:
        missing = [
            path
            for path in (
                self.model_path,
                self.melspectrogram_path,
                self.embedding_model_path,
            )
            if not path.is_file()
        ]
        if missing:
            paths = "\n".join(f"- {path}" for path in missing)
            raise FileNotFoundError(f"openWakeWord model files are missing:\n{paths}")

    @property
    def melspectrogram_path(self) -> Path:
        return self.model_path.parent / "openwakeword" / MELSPECTROGRAM_FILENAME

    @property
    def embedding_model_path(self) -> Path:
        return self.model_path.parent / "openwakeword" / EMBEDDING_FILENAME


def import_openwakeword_model() -> Any:
    try:
        from openwakeword.model import Model

        return Model
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError(
            "Missing wake-word dependency: openwakeword. "
            "Install requirements-wake-word.txt first."
        ) from exc


def _resample_int16(samples: Any, *, source_sample_rate: int, np: Any) -> Any:
    if source_sample_rate == 16000 or samples.size == 0:
        return samples.astype(np.int16, copy=False)
    count = max(1, int(round(samples.size * 16000 / source_sample_rate)))
    source_x = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    target_x = np.linspace(0.0, 1.0, num=count, endpoint=False)
    return np.clip(np.interp(target_x, source_x, samples), -32768, 32767).astype(np.int16)


class OpenWakeWordDetector:
    """Detect the custom ``xingbao.tflite`` wake word from live PCM or WAV audio."""

    def __init__(
        self,
        config: WakeWordConfig,
        *,
        model_class: Any | None = None,
        sounddevice_module: Any | None = None,
        numpy_module: Any | None = None,
        show_input_level: bool = False,
        level_report_interval_seconds: float = 1.0,
    ) -> None:
        self.config = config
        self._model_class = model_class
        self._sounddevice = sounddevice_module
        self._numpy = numpy_module
        self.show_input_level = show_input_level
        self.level_report_interval_seconds = max(0.05, float(level_report_interval_seconds))
        self._model: Any | None = None
        self._pending_samples: Any | None = None

    def wait_for_wake_word(
        self,
        *,
        stop_event: threading.Event | None = None,
        announce: bool = True,
        audio_frame_processor: Callable[[bytes], bytes] | None = None,
    ) -> str:
        self.prepare_live_detection()
        np = self._numpy or import_numpy()
        if announce:
            print(f"[wake] Waiting for wake word '{self.config.wake_word}' (input_device={self.config.input_device})...")
        frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=20)
        last_level_report = time.monotonic()

        def callback(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
            del frames, time_info, status
            try:
                frame_queue.put_nowait(bytes(indata))
            except queue.Full:
                try:
                    frame_queue.get_nowait()
                    frame_queue.put_nowait(bytes(indata))
                except queue.Empty:
                    pass

        audio_config = AudioDeviceConfig(input_device=self.config.input_device, channels=1, sample_rate=self.config.sample_rate)
        with open_raw_input_stream(audio_config, blocksize=self.config.samples_per_read, callback=callback, sounddevice_module=self._sounddevice):
            while stop_event is None or not stop_event.is_set():
                try:
                    frame = frame_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if audio_frame_processor is not None:
                    try:
                        frame = audio_frame_processor(frame)
                    except Exception:
                        # The caller owns optional processing such as AEC.
                        # Keep wake detection usable if that processor fails.
                        pass
                samples = _resample_int16(np.frombuffer(frame, dtype=np.int16), source_sample_rate=self.config.sample_rate, np=np)
                now = time.monotonic()
                if self.show_input_level and now - last_level_report >= self.level_report_interval_seconds:
                    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0
                    peak = float(np.max(np.abs(samples.astype(np.int32)))) if samples.size else 0.0
                    print(f"[wake-level] rms={rms:.1f} peak={peak:.1f}", flush=True)
                    last_level_report = now
                if self._detect_samples(samples):
                    if announce:
                        print(f"[wake] Detected: {self.config.wake_word}")
                    return self.config.wake_word
        return ""

    def detect_wav(self, wav_path: Path | str) -> list[str]:
        np = self._numpy or import_numpy()
        path = Path(wav_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getsampwidth() != 2:
                raise RuntimeError("Wake-word WAV must use 16-bit PCM samples.")
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels)[:, 0]
        samples = _resample_int16(samples, source_sample_rate=sample_rate, np=np)
        self._pending_samples = np.empty(0, dtype=np.int16)
        detected: list[str] = []
        for start in range(0, len(samples), OPENWAKEWORD_FRAME_SAMPLES):
            if self._detect_samples(samples[start : start + OPENWAKEWORD_FRAME_SAMPLES]):
                detected.append(self.config.wake_word)
        return detected

    def detect_pcm_frame(self, frame: bytes, *, source_sample_rate: int | None = None) -> str:
        if not frame:
            return ""
        np = self._numpy or import_numpy()
        samples = _resample_int16(np.frombuffer(frame, dtype=np.int16), source_sample_rate=source_sample_rate or self.config.sample_rate, np=np)
        return self.config.wake_word if self._detect_samples(samples) else ""

    def prepare_live_detection(self) -> None:
        self._get_model()
        if self._pending_samples is None:
            np = self._numpy or import_numpy()
            self._pending_samples = np.empty(0, dtype=np.int16)

    def _detect_samples(self, samples: Any) -> bool:
        self.prepare_live_detection()
        np = self._numpy or import_numpy()
        self._pending_samples = np.concatenate((self._pending_samples, samples))
        while self._pending_samples.size >= OPENWAKEWORD_FRAME_SAMPLES:
            chunk = self._pending_samples[:OPENWAKEWORD_FRAME_SAMPLES]
            self._pending_samples = self._pending_samples[OPENWAKEWORD_FRAME_SAMPLES:]
            scores = self._get_model().predict(chunk)
            # A score of exactly 0.5 is intentionally not sufficient: the
            # wake contract is strictly greater than the configured threshold.
            threshold = max(0.5, self.config.threshold)
            if any(float(score) > threshold for score in scores.values()):
                self._pending_samples = np.empty(0, dtype=np.int16)
                reset = getattr(self._get_model(), "reset", None)
                if callable(reset):
                    reset()
                return True
        return False

    def _get_model(self) -> Any:
        if self._model is None:
            self.config.validate_files()
            model_class = self._model_class or import_openwakeword_model()
            self._model = model_class(
                wakeword_models=[str(self.config.model_path)],
                inference_framework="tflite",
                melspec_model_path=str(self.config.melspectrogram_path),
                embedding_model_path=str(self.config.embedding_model_path),
            )
        return self._model
