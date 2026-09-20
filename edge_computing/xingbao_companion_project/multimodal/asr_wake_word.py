"""ASR-backed wake-word detector for board deployments with weak local KWS."""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

from core.settings import AppSettings
from multimodal.asr_client import (
    EmptyRecognitionResult,
    SherpaOnnxASRClient,
)
from multimodal.audio_io import AudioDeviceConfig
from multimodal.vad import NoSpeechTimeout, VADConfig, capture_utterance_vad


_WAKE_ALIASES = (
    "星宝星宝",
    "星宝",
    "新宝新宝",
    "新宝",
    "心宝",
    "馨宝",
    "鑫宝",
)
_WAKE_INITIALS = "星新心馨鑫"
_WAKE_FINALS = "宝保包堡报"
_WAKE_PINYIN_ALIASES = ("xingbao", "xinbao")


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _environment_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    """Read a board-tunable wake VAD value without making boot fragile."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _build_local_keyword_detector(
    settings: AppSettings,
    input_device: int | None,
) -> Any:
    """Build the local openWakeWord detector lazily for an already-captured WAV."""
    from multimodal.wake_word import OpenWakeWordDetector, WakeWordConfig

    return OpenWakeWordDetector(
        WakeWordConfig.from_settings(settings, input_device=input_device)
    )


def _compact_wake_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(char.lower() for char in normalized if char.isalnum())


def _wake_match_reason(text: str) -> str | None:
    """Return the limited wake-name match that accepts an ASR transcript.

    This deliberately tolerates common same-sound Chinese transcriptions, but
    never guesses a wake word from an arbitrary sentence.  A single-channel
    microphone cannot distinguish a child from a nearby video, so the name
    itself remains mandatory for cloud-ASR acceptance.
    """
    return _wake_match_detail(text)[0]


def _wake_match_detail(text: str) -> tuple[str | None, str]:
    """Return only a whitelisted wake token suitable for operational logs.

    The ASR transcript can contain child speech unrelated to wake-up.  Keep
    service logs useful for keyword tuning without persisting that transcript.
    """
    compact = _compact_wake_text(text)
    if any(alias in compact for alias in _WAKE_ALIASES):
        return "exact_alias", next(alias for alias in _WAKE_ALIASES if alias in compact)
    if any(alias in compact for alias in _WAKE_PINYIN_ALIASES):
        return "pinyin_alias", next(
            alias for alias in _WAKE_PINYIN_ALIASES if alias in compact
        )
    phonetic_match = re.search(rf"[{_WAKE_INITIALS}][{_WAKE_FINALS}]", compact)
    if phonetic_match:
        return "phonetic_name", phonetic_match.group(0)
    return None, "none"


class _WakeCaptureStop:
    """Expose either the caller stop request or a real-time local-KWS hit."""

    def __init__(
        self,
        outer_stop_event: threading.Event | None,
        local_wake_event: threading.Event,
    ) -> None:
        self._outer_stop_event = outer_stop_event
        self._local_wake_event = local_wake_event

    def is_set(self) -> bool:
        return self._local_wake_event.is_set() or bool(
            self._outer_stop_event and self._outer_stop_event.is_set()
        )


class ASRWakeWordDetector:
    """Recognize short utterances and accept only configured wake-word aliases.

    This detector is intended for the board's USB microphone route, where the
    bundled offline KWS model can miss clearly audible child speech. It only
    sends audio to ASR after local VAD observes speech; silence stays local.
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        input_device: int | None = None,
        capture: Callable[..., tuple[Path, dict[str, float]]] = capture_utterance_vad,
        asr_factory: Callable[[AppSettings], Any] = SherpaOnnxASRClient,
        fallback_asr_factory: Callable[[AppSettings], Any] = SherpaOnnxASRClient,
        offline_detector: Any | None = None,
        offline_detector_factory: Callable[
            [AppSettings, int | None], Any
        ] = _build_local_keyword_detector,
        recognition_timeout_seconds: float | None = None,
    ) -> None:
        self.settings = settings
        self.input_device = input_device
        self._capture = capture
        self._asr_factory = asr_factory
        self._fallback_asr_factory = fallback_asr_factory
        self._fallback_on_speech = os.environ.get(
            "XINGBAO_ASR_WAKE_FALLBACK_ON_SPEECH", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._local_kws_enabled = _environment_bool(
            "XINGBAO_ASR_WAKE_LOCAL_KWS",
            True,
        )
        self._offline_detector = offline_detector
        if self._offline_detector is None and self._local_kws_enabled:
            self._offline_detector = offline_detector_factory(settings, input_device)
        self._local_kws_failed = False
        self._prepare_local_keyword_detector()
        self._recognition_timeout_seconds = max(
            0.5,
            float(
                recognition_timeout_seconds
                if recognition_timeout_seconds is not None
                else _environment_float(
                    "XINGBAO_ASR_WAKE_RECOGNITION_TIMEOUT_SECONDS",
                    3.0,
                    minimum=0.5,
                )
            ),
        )
        self._asr_retry_after_perf = 0.0
        self._asr_failure_backoff_seconds = _environment_float(
            "XINGBAO_ASR_WAKE_FAILURE_BACKOFF_SECONDS",
            1.2,
            minimum=0.0,
        )
        self._recognition_lock = threading.Lock()
        self._recognition_inflight = False

    def _prepare_local_keyword_detector(self) -> None:
        detector = self._offline_detector
        prepare = getattr(detector, "prepare_live_detection", None)
        if detector is None or not callable(prepare):
            return
        try:
            prepare()
        except Exception as exc:
            self._local_kws_failed = True
            print(
                "[wake-asr] local KWS unavailable; continuing with cloud ASR "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )

    def wait_for_wake_word(
        self,
        *,
        stop_event: threading.Event | None = None,
        announce: bool = True,
    ) -> str:
        if announce:
            print(
                "[wake-asr] Waiting for speech containing "
                f"'{self.settings.wake_word}' (input_device={self.input_device})...",
                flush=True,
            )

        while stop_event is None or not stop_event.is_set():
            local_keyword: list[str] = []
            local_wake_event = threading.Event()

            def on_audio_frame(frame: bytes) -> None:
                detector = self._offline_detector
                detect_frame = getattr(detector, "detect_pcm_frame", None)
                if (
                    detector is None
                    or self._local_kws_failed
                    or local_wake_event.is_set()
                    or not callable(detect_frame)
                ):
                    return
                try:
                    keyword = str(
                        detect_frame(
                            frame,
                            source_sample_rate=self.settings.record_sample_rate,
                        )
                    ).strip()
                except Exception as exc:
                    self._local_kws_failed = True
                    print(
                        "[wake-asr] local KWS unavailable; continuing with cloud ASR "
                        f"error={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    return
                if self._wake_match_reason(keyword) is not None:
                    local_keyword.append(keyword)
                    local_wake_event.set()

            try:
                wav_path, vad_info = self._capture(
                    out_path=self._capture_path(),
                    audio_config=AudioDeviceConfig(
                        input_device=self.input_device,
                        channels=1,
                        sample_rate=self.settings.record_sample_rate,
                    ),
                    vad_config=VADConfig(
                        calibrate_seconds=0.18,
                        # A sustained 120 ms human-voice segment rejects
                        # single-frame video and room-noise spikes without
                        # making a normal short wake phrase feel slow.
                        start_hold_ms=int(
                            _environment_float(
                                "XINGBAO_ASR_WAKE_START_HOLD_MS",
                                120.0,
                                minimum=30.0,
                            )
                        ),
                        end_silence_ms=int(
                            _environment_float(
                                "XINGBAO_ASR_WAKE_END_SILENCE_MS",
                                450.0,
                                minimum=80.0,
                            )
                        ),
                        # A child often says "星宝星宝" in well under one
                        # second.  Keeping this independently tunable avoids
                        # extending that short call to the 4.5s max capture.
                        min_utterance_ms=int(
                            _environment_float(
                                "XINGBAO_ASR_WAKE_MIN_UTTERANCE_MS",
                                420.0,
                                minimum=120.0,
                            )
                        ),
                        max_utterance_seconds=_environment_float(
                            "XINGBAO_ASR_WAKE_MAX_UTTERANCE_SECONDS",
                            4.5,
                            minimum=0.8,
                        ),
                        listen_timeout_seconds=1.2,
                        threshold_multiplier=_environment_float(
                            "XINGBAO_ASR_WAKE_THRESHOLD_MULTIPLIER",
                            3.0,
                            minimum=1.0,
                        ),
                        min_rms=_environment_float(
                            "XINGBAO_ASR_WAKE_MIN_RMS", 180.0, minimum=1.0
                        ),
                        manual_threshold=_environment_float(
                            "XINGBAO_ASR_WAKE_MANUAL_THRESHOLD",
                            0.0,
                            minimum=0.0,
                        ),
                        # Use the WebRTC speech classifier rather than a
                        # relative energy jump for wake capture.  The normal
                        # dialogue VAD retains its RMS guard.
                        start_requires_rms=not _environment_bool(
                            "XINGBAO_ASR_WAKE_WEBRTC_START_ONLY",
                            True,
                        ),
                        # WebRTC labels some distant video narration as
                        # speech.  Keep a stable, venue-tunable absolute
                        # floor while avoiding the over-reactive noise
                        # multiplier used by dialogue capture.
                        webrtc_start_min_rms=_environment_float(
                            "XINGBAO_ASR_WAKE_WEBRTC_MIN_RMS",
                            1500.0,
                            minimum=0.0,
                        ),
                        # Disabled by default for portable PC launches.  The
                        # board launcher enables a bounded live RMS report so
                        # venue tuning does not require recording audio.
                        debug_level_interval_ms=_environment_float(
                            "XINGBAO_ASR_WAKE_RMS_LOG_INTERVAL_MS",
                            0.0,
                            minimum=0.0,
                        ),
                    ),
                    audio_frame_callback=on_audio_frame,
                    stop_event=_WakeCaptureStop(stop_event, local_wake_event),
                )
            except NoSpeechTimeout:
                if local_keyword:
                    return self._announce_local_wake(announce)
                continue
            except Exception as exc:
                print(
                    "[wake-asr] microphone capture skipped "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )
                time.sleep(0.15)
                continue

            print(
                "[wake-asr] vad_capture_finished "
                f"utterance_ms={float(vad_info.get('utterance_ms', 0.0)):.1f}, "
                f"noise={float(vad_info.get('noise', 0.0)):.1f}, "
                f"start_threshold={float(vad_info.get('start_threshold', 0.0)):.1f}, "
                f"detector={vad_info.get('speech_detector', 'unknown')}",
                flush=True,
            )
            if local_keyword:
                return self._announce_local_wake(announce)
            if stop_event is not None and stop_event.is_set():
                return ""
            if self._detect_local_keyword(wav_path, announce=announce):
                return self.settings.wake_word
            if time.monotonic() < self._asr_retry_after_perf:
                print("[wake-asr] recognition_skipped reason=backoff", flush=True)
                continue
            recognition_source = "primary"
            text, timed_out, error = self._transcribe_with_deadline(
                self._asr_factory,
                wav_path,
                source=recognition_source,
            )
            if timed_out:
                self._defer_cloud_asr()
                print(
                    "[wake-asr] recognition timed out; keeping wake listener alive",
                    flush=True,
                )
                continue
            if isinstance(error, EmptyRecognitionResult):
                try:
                    recognition_source = "fallback"
                    text, timed_out, error = self._transcribe_with_deadline(
                        self._fallback_asr_factory,
                        wav_path,
                        source=recognition_source,
                    )
                    if timed_out:
                        self._defer_cloud_asr()
                        print(
                            "[wake-asr] fallback recognition timed out; "
                            "keeping wake listener alive",
                            flush=True,
                        )
                        continue
                    if error is not None:
                        raise error
                except Exception as exc:
                    self._defer_cloud_asr()
                    print(
                        "[wake-asr] recognition skipped "
                        f"error={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue
            elif error is not None:
                self._defer_cloud_asr()
                print(
                    "[wake-asr] recognition skipped "
                    f"error={type(error).__name__}: {error}",
                    flush=True,
                )
                continue

            self._asr_retry_after_perf = 0.0
            match_reason, wake_keyword = _wake_match_detail(text)
            print(
                "[wake-asr] recognition_keyword "
                f"source={recognition_source}, "
                f"wake_keyword={wake_keyword}, "
                f"match={match_reason or 'none'}",
                flush=True,
            )
            if match_reason is not None:
                if announce:
                    print(
                        "[wake-asr] Detected: "
                        f"{self.settings.wake_word} source=cloud_asr "
                        f"wake_keyword={wake_keyword} match={match_reason}",
                        flush=True,
                    )
                return self.settings.wake_word
            print(
                "[wake-asr] recognition_rejected "
                f"reason=no_wake_match, wake_keyword={wake_keyword}, "
                f"recognized_chars={len(text)}, "
                f"utterance_ms={float(vad_info.get('utterance_ms', 0.0)):.1f}",
                flush=True,
            )
            if self._fallback_on_speech and text and float(
                vad_info.get("utterance_ms", 0.0)
            ) >= 700.0:
                if announce:
                    print(
                        "[wake-asr] Speech-activity fallback activated "
                        f"(recognized_chars={len(text)})",
                        flush=True,
                    )
                return self.settings.wake_word
        return ""

    def detect_wav(self, wav_path: Path | str) -> list[str]:
        """Best-effort diagnostic helper consistent with the KWS detector API."""
        text = str(self._asr_factory(self.settings).transcribe(wav_path)).strip()
        return [self.settings.wake_word] if self._wake_match_reason(text) else []

    def _detect_local_keyword(self, wav_path: Path, *, announce: bool) -> bool:
        """Check the captured utterance locally before depending on cloud ASR."""
        detector = self._offline_detector
        if detector is None or self._local_kws_failed:
            return False
        try:
            detected = detector.detect_wav(wav_path)
        except Exception as exc:
            # Missing model files or an optional runtime failure must leave the
            # existing cloud path available.  Log once to avoid flooding the
            # board terminal while a video is playing nearby.
            self._local_kws_failed = True
            print(
                "[wake-asr] local KWS unavailable; continuing with cloud ASR "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )
            return False
        if not any(self._wake_match_reason(str(keyword)) for keyword in detected):
            return False
        self._announce_local_wake(announce, source="local_kws_wav_fallback")
        return True

    def _announce_local_wake(
        self,
        announce: bool,
        *,
        source: str = "local_kws_realtime",
    ) -> str:
        if announce:
            print(
                "[wake-asr] Detected: "
                f"{self.settings.wake_word} source={source}",
                flush=True,
            )
        return self.settings.wake_word

    def _defer_cloud_asr(self) -> None:
        if self._asr_failure_backoff_seconds > 0:
            self._asr_retry_after_perf = time.monotonic() + self._asr_failure_backoff_seconds

    def _transcribe_with_deadline(
        self,
        factory: Callable[[AppSettings], Any],
        wav_path: Path,
        *,
        source: str,
    ) -> tuple[str, bool, BaseException | None]:
        """Bound one cloud wake-recognition request without accumulating workers.

        Third-party ASR clients do not consistently expose a network timeout.
        When one request stalls, leave its daemon worker to unwind but do not
        start another one for every VAD segment.  The wake loop remains alive
        and resumes recognition as soon as that worker finishes.
        """
        with self._recognition_lock:
            if self._recognition_inflight:
                print(
                    f"[wake-asr] recognition_skipped source={source} reason=inflight",
                    flush=True,
                )
                return "", True, None
            self._recognition_inflight = True

        request_started_at = time.perf_counter()
        print(
            "[wake-asr] recognition_started "
            f"source={source}, timeout_s={self._recognition_timeout_seconds:.1f}",
            flush=True,
        )
        done = threading.Event()
        result: dict[str, Any] = {"text": "", "error": None}

        def worker() -> None:
            try:
                result["text"] = str(factory(self.settings).transcribe(wav_path)).strip()
            except BaseException as exc:  # defensive third-party boundary
                result["error"] = exc
            finally:
                with self._recognition_lock:
                    self._recognition_inflight = False
                done.set()

        threading.Thread(target=worker, name="asr-wake-recognition", daemon=True).start()
        if not done.wait(timeout=self._recognition_timeout_seconds):
            print(
                "[wake-asr] recognition_finished "
                f"source={source}, outcome=timeout, "
                f"elapsed_ms={round((time.perf_counter() - request_started_at) * 1000, 1)}",
                flush=True,
            )
            return "", True, None
        error = result.get("error")
        text = str(result.get("text") or "")
        outcome = "error" if isinstance(error, BaseException) else "ok"
        print(
            "[wake-asr] recognition_finished "
            f"source={source}, outcome={outcome}, "
            f"elapsed_ms={round((time.perf_counter() - request_started_at) * 1000, 1)}, "
            f"recognized_chars={len(text)}, "
            f"error_type={type(error).__name__ if isinstance(error, BaseException) else 'none'}",
            flush=True,
        )
        return text, False, error if isinstance(error, BaseException) else None

    def _capture_path(self) -> Path:
        return Path("work/cache") / f"asr_wake_{threading.get_ident()}.wav"

    @staticmethod
    def _wake_match_reason(text: str) -> str | None:
        return _wake_match_reason(text)

    @staticmethod
    def _contains_wake_alias(text: str) -> bool:
        return _wake_match_reason(text) is not None
