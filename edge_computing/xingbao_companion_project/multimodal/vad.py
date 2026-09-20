"""Voice activity detection helpers adapted from pc5.py."""

from __future__ import annotations

import queue
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from multimodal.audio_io import (
    AudioDeviceConfig,
    import_audio_libs,
    import_numpy,
    open_raw_input_stream,
)


DEFAULT_VAD_INPUT_WAV = Path("work/cache/vad_input.wav")


class NoSpeechTimeout(TimeoutError):
    """Raised when VAD does not hear speech before the listen timeout."""


@dataclass(frozen=True)
class VADConfig:
    frame_ms: int = 30
    # Silero does not need a room-noise calibration phase. Keeping this at
    # zero makes the voice turn ready as soon as the wake acknowledgement has
    # handed off the microphone.
    calibrate_seconds: float = 0.0
    pre_roll_ms: int = 300
    start_hold_ms: int = 120
    end_silence_ms: int = 500
    min_utterance_ms: int = 500
    max_utterance_seconds: float = 30.0
    threshold_multiplier: float = 3.0
    min_rms: float = 180.0
    end_threshold_ratio: float = 0.62
    manual_threshold: float = 0.0
    listen_timeout_seconds: float = 0.0
    debug_level_interval_ms: float = 0.0
    # Silero VAD is the sole speech classifier for dialogue capture.  The
    # values below are its speech / non-speech hysteresis thresholds.
    silero_threshold: float = 0.5
    silero_negative_threshold: float = 0.35
    silero_model_path: str = "third_party/silero_vad/data/silero_vad.onnx"
    # Retained only for compatibility with old callers' configuration files.
    # They no longer select the speech detector.
    hybrid_vad_enabled: bool = True
    webrtc_aggressiveness: int = 3
    # Wake-word capture can rely on WebRTC speech classification without a
    # relative RMS gate.  A small absolute floor still filters distant video
    # narration and short noise bursts; dialogue capture keeps its adaptive
    # RMS guard.
    start_requires_rms: bool = True
    webrtc_start_min_rms: float = 0.0


_SILERO_SESSION: Any | None = None
_SILERO_SESSION_LOCK = threading.Lock()


def _silero_model_path(config: VADConfig) -> Path:
    path = Path(config.silero_model_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[1] / path


def _get_silero_session(config: VADConfig) -> Any:
    """Load the vendored official Silero ONNX model once per process."""
    global _SILERO_SESSION
    with _SILERO_SESSION_LOCK:
        if _SILERO_SESSION is not None:
            return _SILERO_SESSION
        model_path = _silero_model_path(config)
        if not model_path.is_file():
            raise RuntimeError(f"Silero VAD model is missing: {model_path}")
        try:
            import onnxruntime  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError("Silero VAD requires onnxruntime.") from exc
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        # ONNX Runtime otherwise prints a large graph-cleanup warning block
        # when the model is first loaded, obscuring the real-time voice log.
        options.log_severity_level = 3
        _SILERO_SESSION = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )
        return _SILERO_SESSION


class _SileroSpeechGate:
    """Stateful 16 kHz Silero ONNX inference for one VAD capture session."""

    def __init__(self, config: VADConfig, *, sample_rate: int) -> None:
        if sample_rate != 16000:
            raise RuntimeError(
                f"Silero VAD in this runtime requires 16000 Hz input, got {sample_rate}."
            )
        np = import_numpy()
        self._np = np
        self._session = _get_silero_session(config)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)
        self.last_probability = 0.0

    def is_speech(self, frame: bytes, *, threshold: float) -> bool:
        audio = self._np.frombuffer(frame, dtype=self._np.int16).astype(self._np.float32)
        audio = audio / 32768.0
        # Silero consumes exactly 512 samples (32 ms) per 16 kHz inference.
        # The live capture may use a 30 ms frame, so zero-pad its final 2 ms.
        if audio.size < 512:
            audio = self._np.pad(audio, (0, 512 - audio.size))
        elif audio.size > 512:
            audio = audio[:512]
        audio = audio.reshape(1, 512)
        model_input = self._np.concatenate((self._context, audio), axis=1)
        output, state = self._session.run(
            None,
            {
                "input": model_input,
                "state": self._state,
                "sr": self._np.asarray(16000, dtype=self._np.int64),
            },
        )
        self._state = state
        self._context = model_input[:, -64:]
        self.last_probability = float(output.reshape(-1)[0])
        return self.last_probability >= float(threshold)


def _build_silero_speech_gate(
    config: VADConfig,
    *,
    sample_rate: int,
) -> _SileroSpeechGate:
    return _SileroSpeechGate(config, sample_rate=sample_rate)


def _start_frame_is_speech(
    frame: bytes,
    *,
    speech_gate: _SileroSpeechGate,
    threshold: float,
) -> bool:
    """Classify a frame with the Silero speech threshold."""
    return speech_gate.is_speech(frame, threshold=threshold)


def _continuing_frame_is_speech(
    frame: bytes,
    *,
    speech_gate: _SileroSpeechGate,
    threshold: float,
) -> bool:
    """Use the lower Silero threshold while an utterance is in progress."""
    return speech_gate.is_speech(frame, threshold=threshold)


def frame_rms_bytes(frame: bytes) -> float:
    np = import_numpy()
    if not frame:
        return 0.0
    audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio**2)))


def save_frames_to_wav(
    path: Path | str,
    frames: list[bytes],
    *,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(frames))
    return out_path


def wait_for_speech_start_vad(
    *,
    audio_config: AudioDeviceConfig | None = None,
    vad_config: VADConfig | None = None,
    stop_event: threading.Event | None = None,
    audio_frame_processor: Callable[[bytes], bytes] | None = None,
    speech_start_after_seconds: float = 0.0,
    speech_start_min_rms: float = 0.0,
    debug_label: str = "barge-vad",
) -> dict[str, float] | None:
    """Wait until VAD sees the start of speech, then return detection metadata."""
    np, sd = import_audio_libs()
    device_config = audio_config or AudioDeviceConfig()
    config = vad_config or VADConfig()
    frame_samples = int(device_config.sample_rate * config.frame_ms / 1000)
    frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
    speech_gate = _build_silero_speech_gate(
        config,
        sample_rate=device_config.sample_rate,
    )
    _barge_log(
        debug_label,
        f"capture_started "
        f"input_device={device_config.input_device}, "
        f"sample_rate={device_config.sample_rate}, "
        f"frame_ms={config.frame_ms}, "
        f"start_hold_ms={config.start_hold_ms}, "
        "detector=silero_onnx",
    )

    def callback(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
        del frames, time_info, status
        try:
            frame_queue.put_nowait(bytes(indata))
        except queue.Full:
            try:
                frame_queue.get_nowait()
                frame_queue.put_nowait(bytes(indata))
            except Exception:
                pass

    with open_raw_input_stream(
        device_config,
        blocksize=frame_samples,
        callback=callback,
        sounddevice_module=sd,
    ):
        listen_start_perf = time.perf_counter()
        calibrate_frames = max(0, int(config.calibrate_seconds * 1000 / config.frame_ms))
        noise_values: list[float] = []
        while len(noise_values) < calibrate_frames:
            if stop_event is not None and stop_event.is_set():
                return None
            try:
                frame = frame_queue.get(timeout=0.05)
            except queue.Empty:
                if (
                    config.listen_timeout_seconds > 0
                    and time.perf_counter() - listen_start_perf
                    >= config.listen_timeout_seconds
                ):
                    return None
                continue
            noise_values.append(frame_rms_bytes(frame))

        noise = float(np.median(noise_values)) if noise_values else 0.0
        if config.manual_threshold > 0:
            start_threshold = float(config.manual_threshold)
        else:
            start_threshold = max(config.min_rms, noise * config.threshold_multiplier)
        start_hold_frames = max(1, int(config.start_hold_ms / config.frame_ms))
        voice_hold = 0
        last_debug_perf = 0.0
        last_rejection_perf = 0.0
        start_after_seconds = max(0.0, float(speech_start_after_seconds))
        start_min_rms = max(0.0, float(speech_start_min_rms))

        while True:
            if stop_event is not None and stop_event.is_set():
                return None
            try:
                frame = frame_queue.get(timeout=0.05)
            except queue.Empty:
                if (
                    config.listen_timeout_seconds > 0
                    and time.perf_counter() - listen_start_perf
                    >= config.listen_timeout_seconds
                ):
                    return None
                continue
            if audio_frame_processor is not None:
                try:
                    frame = audio_frame_processor(frame)
                except Exception as exc:
                    _barge_log(debug_label, f"frame_processor_failed error={type(exc).__name__}: {exc}")
            rms = frame_rms_bytes(frame)
            if config.debug_level_interval_ms > 0:
                now = time.perf_counter()
                if (
                    last_debug_perf <= 0
                    or (now - last_debug_perf) * 1000 >= config.debug_level_interval_ms
                ):
                    _barge_log(
                        debug_label,
                        f"level "
                        f"rms={rms:.1f}, "
                        f"start_threshold={start_threshold:.1f}, "
                        f"aec_start_min_rms={start_min_rms:.1f}, "
                        f"adapt_remaining_ms={max(0.0, start_after_seconds - (now - listen_start_perf)) * 1000:.0f}, "
                        f"voice_hold={voice_hold}",
                    )
                    last_debug_perf = now
            is_speech = _start_frame_is_speech(
                frame,
                speech_gate=speech_gate,
                threshold=config.silero_threshold,
            )
            elapsed_seconds = time.perf_counter() - listen_start_perf
            adaptation_done = elapsed_seconds >= start_after_seconds
            rms_ok = rms >= start_min_rms
            eligible = is_speech and adaptation_done and rms_ok
            voice_hold = voice_hold + 1 if eligible else 0
            if is_speech and not eligible and config.debug_level_interval_ms > 0:
                now = time.perf_counter()
                if last_rejection_perf <= 0 or (now - last_rejection_perf) * 1000 >= config.debug_level_interval_ms:
                    _barge_log(
                        debug_label,
                        f"candidate_rejected "
                        f"reason={'aec_adapting' if not adaptation_done else 'residual_rms_below_gate'}, "
                        f"rms={rms:.1f}, min_rms={start_min_rms:.1f}, "
                        f"silero_probability={speech_gate.last_probability:.3f}, "
                        f"adapt_remaining_ms={max(0.0, start_after_seconds - elapsed_seconds) * 1000:.0f}",
                    )
                    last_rejection_perf = now
            if voice_hold >= start_hold_frames:
                detected_perf = time.perf_counter()
                _barge_log(
                    debug_label,
                    f"speech_started "
                    f"elapsed_ms={round((detected_perf - listen_start_perf) * 1000, 1)}, "
                    f"silero_probability={speech_gate.last_probability:.3f}, "
                    f"silero_threshold={config.silero_threshold:.2f}",
                )
                return {
                    "detected_perf": detected_perf,
                    "elapsed_ms": round((detected_perf - listen_start_perf) * 1000, 1),
                    "start_threshold": float(start_threshold),
                    "noise": float(noise),
                    "rms": float(rms),
                    "frame_ms": float(config.frame_ms),
                    "start_hold_ms": float(config.start_hold_ms),
                    "aec_start_min_rms": float(start_min_rms),
                    "aec_adaptation_ms": round(start_after_seconds * 1000, 1),
                }


def _barge_log(label: str, message: str) -> None:
    """Keep generic VAD output unchanged; mirror AEC3 output to its own log."""
    line = f"[{label}] {message}"
    print(line, flush=True)
    if label.startswith("aec3"):
        try:
            from multimodal.webrtc_aec3 import log_aec3
            log_aec3(line)
        except Exception:
            pass


def capture_utterance_vad(
    out_path: Path | str = DEFAULT_VAD_INPUT_WAV,
    *,
    audio_config: AudioDeviceConfig | None = None,
    vad_config: VADConfig | None = None,
    on_listening_ready: Callable[[], None] | None = None,
    audio_frame_callback: Callable[[bytes], None] | None = None,
    speech_frame_callback: Callable[[bytes], None] | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[Path, dict[str, float]]:
    """Capture one utterance from the microphone using Silero VAD."""
    np, sd = import_audio_libs()
    device_config = audio_config or AudioDeviceConfig()
    config = vad_config or VADConfig()
    frame_samples = int(device_config.sample_rate * config.frame_ms / 1000)
    frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
    speech_gate = _build_silero_speech_gate(
        config,
        sample_rate=device_config.sample_rate,
    )
    print(
        "[vad] capture_started "
        f"input_device={device_config.input_device}, "
        f"sample_rate={device_config.sample_rate}, "
        f"frame_ms={config.frame_ms}, "
        f"calibrate_ms={round(config.calibrate_seconds * 1000, 1)}, "
        f"start_hold_ms={config.start_hold_ms}, "
        f"end_silence_ms={config.end_silence_ms}, "
        f"max_utterance_s={config.max_utterance_seconds:.1f}, "
        "detector=silero_onnx",
        flush=True,
    )

    def callback(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
        del frames, time_info, status
        frame = bytes(indata)
        if audio_frame_callback is not None:
            try:
                audio_frame_callback(frame)
            except Exception:
                pass
        try:
            frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                frame_queue.get_nowait()
                frame_queue.put_nowait(frame)
            except Exception:
                pass

    with open_raw_input_stream(
        device_config,
        blocksize=frame_samples,
        callback=callback,
        sounddevice_module=sd,
    ):
        listen_start_perf = time.perf_counter()
        calibrate_frames = max(0, int(config.calibrate_seconds * 1000 / config.frame_ms))
        noise_values: list[float] = []
        while len(noise_values) < calibrate_frames:
            if stop_event is not None and stop_event.is_set():
                raise NoSpeechTimeout("Speech capture was interrupted.")
            try:
                frame = frame_queue.get(timeout=0.1)
            except queue.Empty:
                if (
                    config.listen_timeout_seconds > 0
                    and time.perf_counter() - listen_start_perf
                    >= config.listen_timeout_seconds
                ):
                    raise NoSpeechTimeout(
                        "No audio frames received from input device "
                        f"within {config.listen_timeout_seconds:.1f}s."
                    )
                continue
            noise_values.append(frame_rms_bytes(frame))
        noise = float(np.median(noise_values)) if noise_values else 0.0

        if config.manual_threshold > 0:
            start_threshold = float(config.manual_threshold)
        else:
            start_threshold = max(config.min_rms, noise * config.threshold_multiplier)
        end_threshold = max(config.min_rms * 0.55, start_threshold * config.end_threshold_ratio)

        pre_roll_max = max(1, int(config.pre_roll_ms / config.frame_ms))
        start_hold_frames = max(1, int(config.start_hold_ms / config.frame_ms))
        end_silence_frames = max(1, int(config.end_silence_ms / config.frame_ms))
        min_frames = max(1, int(config.min_utterance_ms / config.frame_ms))
        max_frames = max(1, int(config.max_utterance_seconds * 1000 / config.frame_ms))
        # Only advertise "listening" after noise calibration is complete, so
        # speech that starts when the UI changes is treated as speech instead
        # of being absorbed into the noise baseline.
        if on_listening_ready is not None:
            on_listening_ready()
        if config.debug_level_interval_ms > 0:
            print(
                "[vad] Calibration "
                f"noise={noise:.1f}, "
                f"start_threshold={start_threshold:.1f}, "
                f"end_threshold={end_threshold:.1f}, "
                "detector=silero_onnx",
                flush=True,
            )

        pre_roll: deque[bytes] = deque(maxlen=pre_roll_max)
        active_frames: list[bytes] = []
        voice_hold = 0
        silence_hold = 0
        speaking = False
        speech_start_perf = 0.0
        last_debug_perf = 0.0

        while True:
            if stop_event is not None and stop_event.is_set():
                raise NoSpeechTimeout("Speech capture was interrupted.")
            try:
                frame = frame_queue.get(timeout=0.1)
            except queue.Empty:
                if (
                    not speaking
                    and config.listen_timeout_seconds > 0
                    and time.perf_counter() - listen_start_perf >= config.listen_timeout_seconds
                ):
                    raise NoSpeechTimeout(
                        f"No speech detected within {config.listen_timeout_seconds:.1f}s."
                    )
                continue
            rms = frame_rms_bytes(frame)
            if config.debug_level_interval_ms > 0:
                now = time.perf_counter()
                if (
                    last_debug_perf <= 0
                    or (now - last_debug_perf) * 1000 >= config.debug_level_interval_ms
                ):
                    state = "speaking" if speaking else "waiting"
                    print(
                        "[vad] level "
                        f"state={state}, "
                        f"rms={rms:.1f}, "
                        f"start_threshold={start_threshold:.1f}, "
                        f"voice_hold={voice_hold}, "
                        f"silence_hold={silence_hold}"
                        ,
                        flush=True,
                    )
                    last_debug_perf = now

            if not speaking:
                pre_roll.append(frame)
                voice_hold = (
                    voice_hold + 1
                    if _start_frame_is_speech(
                        frame,
                        speech_gate=speech_gate,
                        threshold=config.silero_threshold,
                    )
                    else 0
                )
                if voice_hold >= start_hold_frames:
                    speaking = True
                    speech_start_perf = time.perf_counter()
                    active_frames = list(pre_roll)
                    if speech_frame_callback is not None:
                        for speech_frame in active_frames:
                            try:
                                speech_frame_callback(speech_frame)
                            except Exception:
                                pass
                    silence_hold = 0
                    print(
                        "[vad] speech_started "
                        f"elapsed_ms={round((speech_start_perf - listen_start_perf) * 1000, 1)}, "
                        f"silero_probability={speech_gate.last_probability:.3f}, "
                        f"silero_threshold={config.silero_threshold:.2f}, "
                        f"voice_hold_frames={voice_hold}",
                        flush=True,
                    )
                    continue
                if (
                    config.listen_timeout_seconds > 0
                    and time.perf_counter() - listen_start_perf
                    >= config.listen_timeout_seconds
                ):
                    raise NoSpeechTimeout(
                        f"No speech detected within {config.listen_timeout_seconds:.1f}s."
                    )
                continue

            active_frames.append(frame)
            if speech_frame_callback is not None:
                try:
                    speech_frame_callback(frame)
                except Exception:
                    pass
            frame_count = len(active_frames)
            silence_hold = (
                0
                if _continuing_frame_is_speech(
                    frame,
                    speech_gate=speech_gate,
                    threshold=config.silero_negative_threshold,
                )
                else silence_hold + 1
            )

            end_reason = "max_utterance"
            if frame_count >= max_frames:
                break
            if frame_count >= min_frames and silence_hold >= end_silence_frames:
                end_reason = "silence"
                break

        utterance_ms = len(active_frames) * config.frame_ms
        save_frames_to_wav(
            out_path,
            active_frames,
            sample_rate=device_config.sample_rate,
            channels=device_config.channels,
        )
        speech_end_perf = time.perf_counter()
        print(
            "[vad] capture_finished "
            f"reason={end_reason}, "
            f"utterance_ms={utterance_ms:.1f}, "
            f"speech_ms={round((speech_end_perf - speech_start_perf) * 1000, 1)}, "
            f"frames={len(active_frames)}, "
            f"silero_probability={speech_gate.last_probability:.3f}, "
            f"silero_negative_threshold={config.silero_negative_threshold:.2f}, "
            f"final_silence_frames={silence_hold}",
            flush=True,
        )
        return Path(out_path), {
            "utterance_ms": float(utterance_ms),
            "speech_start_perf": speech_start_perf,
            "speech_end_perf": speech_end_perf,
            "start_threshold": float(start_threshold),
            "end_threshold": float(end_threshold),
            "noise": float(noise),
            "frame_ms": float(config.frame_ms),
            "calibrate_ms": round(config.calibrate_seconds * 1000, 1),
            "pre_roll_ms": float(config.pre_roll_ms),
            "start_hold_ms": float(config.start_hold_ms),
            "end_silence_ms": float(config.end_silence_ms),
            "min_utterance_ms": float(config.min_utterance_ms),
            "speech_detector": "silero_onnx",
            "silero_threshold": float(config.silero_threshold),
            "silero_negative_threshold": float(config.silero_negative_threshold),
            "silero_last_probability": float(speech_gate.last_probability),
        }
