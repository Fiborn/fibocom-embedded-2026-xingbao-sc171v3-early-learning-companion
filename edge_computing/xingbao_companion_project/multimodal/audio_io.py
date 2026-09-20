"""Audio device, recording, playback, and acknowledgement helpers."""

from __future__ import annotations

import array
import audioop
import os
import shutil
import subprocess
import sys
import threading
import time
import tempfile
import wave
import re
import queue
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.audio_preferences import load_output_volume
from core.settings import AppSettings
from core.settings import get_dashscope_api_key
from core.voice_profiles import VoiceProfile
from multimodal.tts_client import DashScopeTTSClient


DEFAULT_INPUT_WAV = Path("work/cache/input.wav")
DEFAULT_REPLY_WAV = Path("work/cache/reply.wav")
DEFAULT_QUICK_ACK_WAV = Path("work/cache/quick_ack_cloud.wav")
DEFAULT_CHIME_ACK_WAV = Path("work/cache/quick_ack_chime.wav")
DEFAULT_QUICK_ACK_TEXT = "星宝收到啦，我想一想。"

BOARD_APLAY_OUTPUT_DEVICE = -1000
LAHAINA_CARD_NAME = "lahainayupikiot"
LAHAINA_MIXER_SETTINGS = (
    ("RX HPH Mode", "CLS_AB"),
    ("RX_MACRO RX0 MUX", "AIF1_PB"),
    ("RX_MACRO RX1 MUX", "AIF1_PB"),
    ("RX_CDC_DMA_RX_0 Channels", "Two"),
    ("RX INT0_1 MIX1 INP0", "RX0"),
    ("RX INT1_1 MIX1 INP0", "RX1"),
    ("RX INT0 DEM MUX", "CLSH_DSM_OUT"),
    ("RX INT1 DEM MUX", "CLSH_DSM_OUT"),
    ("RX_COMP1 Switch", "1"),
    ("RX_COMP2 Switch", "1"),
    ("HPHL_COMP Switch", "1"),
    ("HPHR_COMP Switch", "1"),
    ("HPHL_RDAC Switch", "1"),
    ("HPHR_RDAC Switch", "1"),
    ("RX_CDC_DMA_RX_0 Audio Mixer MultiMedia1", "1"),
)

_AUDIO_PLAY_LOCK = threading.Lock()
_LAHAINA_MIXER_CONFIGURED_CARDS: set[str] = set()
_TTS_QUEUE_LOCAL = threading.local()
# At most one PCM stream owns the output device.  Keeping its owner lets a
# safety reminder preempt an ordinary cloud reply instead of waiting behind it
# while the global audio lock is held.
_ACTIVE_REALTIME_PLAYER_LOCK = threading.RLock()
_ACTIVE_REALTIME_PLAYER: Any | None = None


def interrupt_active_realtime_playback() -> bool:
    """Immediately release the current cloud-TTS output for a priority cue."""
    with _ACTIVE_REALTIME_PLAYER_LOCK:
        player = _ACTIVE_REALTIME_PLAYER
    if player is None:
        return False
    return bool(player.interrupt_for_priority())


@dataclass(frozen=True)
class AudioDeviceConfig:
    input_device: int | None = None
    output_device: int | None = None
    channels: int = 1
    sample_rate: int = 16000
    alsa_input_device: str | None = None
    alsa_input_gain: float | None = None


def resolve_alsa_input_device(config: AudioDeviceConfig | None = None) -> str:
    """Return an optional direct ALSA microphone selected for board use."""
    configured = config.alsa_input_device if config is not None else None
    return str(configured or os.getenv("XINGBAO_ALSA_INPUT_DEVICE", "")).strip()


def resolve_alsa_input_gain(config: AudioDeviceConfig | None = None) -> float:
    """Return bounded software gain for direct ALSA capture."""
    configured = config.alsa_input_gain if config is not None else None
    raw_value: object = (
        configured
        if configured is not None
        else os.getenv("XINGBAO_ALSA_INPUT_GAIN", "1.0")
    )
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.1, min(16.0, value))


def resolve_alsa_output_device() -> str:
    """Return the board ALSA playback route for realtime PCM.

    A board launch uses ``BOARD_APLAY_OUTPUT_DEVICE`` as a sentinel instead of
    a PortAudio index.  Realtime TTS must therefore write its PCM stream to
    the same reviewed lahaina route used by ordinary WAV playback.
    """
    configured = os.getenv("XINGBAO_ALSA_OUTPUT_DEVICE", "").strip()
    if configured:
        return configured
    card = configure_lahaina_output_mixer()
    return f"plughw:{card},0"


def apply_pcm16_input_gain(data: bytes, gain: float) -> bytes:
    """Boost PCM audio while preserving the shape of loud speech peaks."""
    requested_gain = max(0.1, min(16.0, float(gain)))
    if not data or requested_gain == 1.0:
        return data
    peak = audioop.max(data, 2)
    if peak > 0:
        requested_gain = min(requested_gain, 30000.0 / float(peak))
    return audioop.mul(data, 2, requested_gain)


class AlsaRawInputStream:
    """A callback-style int16 microphone stream backed by ``arecord``."""

    def __init__(
        self,
        *,
        device: str,
        samplerate: int,
        blocksize: int,
        channels: int,
        dtype: str,
        callback: Any,
        gain: float = 1.0,
    ) -> None:
        if dtype.lower() != "int16":
            raise ValueError("ALSA raw input supports dtype='int16' only.")
        if blocksize <= 0 or channels <= 0 or samplerate <= 0:
            raise ValueError("ALSA raw input requires positive stream dimensions.")
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.channels = channels
        self.callback = callback
        self.gain = max(0.1, min(16.0, float(gain)))
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stopped = threading.Event()
        self._error = ""

    def __enter__(self) -> "AlsaRawInputStream":
        if shutil.which("arecord") is None:
            raise RuntimeError("ALSA input backend requires the system command 'arecord'.")
        command = [
            "arecord", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
            "-c", str(self.channels), "-r", str(self.samplerate),
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start ALSA input: {' '.join(command)}") from exc
        self._reader = threading.Thread(
            target=self._read_loop,
            name="alsa-raw-input",
            daemon=True,
        )
        self._reader.start()
        return self

    def __exit__(self, exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self._stopped.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            reader = self._reader
            self._process = None
            self._reader = None
            threading.Thread(
                target=self._reap_after_shutdown,
                args=(process, reader),
                name="alsa-raw-input-reaper",
                daemon=True,
            ).start()
            if exc_type is None and self._error:
                raise RuntimeError(f"ALSA microphone capture failed: {self._error}")
            return
        if self._reader is not None:
            self._reader.join(timeout=1.0)
        if process is not None and process.stderr is not None:
            detail = process.stderr.read().decode("utf-8", "replace").strip()
            if detail and process.returncode not in (0, -15):
                self._error = detail
        if exc_type is None and self._error:
            raise RuntimeError(f"ALSA microphone capture failed: {self._error}")

    @staticmethod
    def _reap_after_shutdown(
        process: subprocess.Popen[bytes],
        reader: threading.Thread | None,
    ) -> None:
        try:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        finally:
            if reader is not None:
                reader.join(timeout=1.0)
            if process.stderr is not None:
                try:
                    process.stderr.read()
                except Exception:
                    pass

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._error = "ALSA capture process has no stdout stream."
            return
        frame_bytes = self.channels * 2
        target_bytes = self.blocksize * frame_bytes
        while not self._stopped.is_set():
            chunks: list[bytes] = []
            remaining = target_bytes
            while remaining > 0 and not self._stopped.is_set():
                chunk = process.stdout.read(remaining)
                if not chunk:
                    if not self._stopped.is_set():
                        self._error = "arecord ended before delivering an audio block."
                    return
                chunks.append(chunk)
                remaining -= len(chunk)
            if self._stopped.is_set():
                return
            data = b"".join(chunks)
            if self.gain != 1.0:
                data = apply_pcm16_input_gain(data, self.gain)
            try:
                self.callback(data, len(data) // frame_bytes, None, None)
            except Exception:
                self._error = "audio callback raised an exception."
                return


class AlsaRawOutputStream:
    """A small PCM sink backed by a long-lived ``aplay`` process.

    DashScope realtime TTS supplies 22050 Hz mono signed-16-bit PCM.  The
    board has no usable PortAudio output index, while ordinary Xingbao WAV
    playback already uses the lahaina ALSA route.  Keeping one ``aplay``
    process open avoids a file round-trip and lets each cloud PCM callback be
    heard as soon as it arrives.
    """

    def __init__(
        self,
        *,
        device: str | None = None,
        samplerate: int = 22050,
        channels: int = 1,
    ) -> None:
        if samplerate <= 0 or channels <= 0:
            raise ValueError("ALSA raw output requires positive stream dimensions.")
        self.device = (device or "").strip()
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                return
            if self._closed:
                raise RuntimeError("ALSA raw output stream is already closed.")
            if shutil.which("aplay") is None:
                raise RuntimeError("ALSA realtime output requires the system command 'aplay'.")
            device = self.device or resolve_alsa_output_device()
            command = [
                "aplay",
                "-q",
                "-D",
                device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-c",
                str(self.channels),
                "-r",
                str(self.samplerate),
            ]
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except OSError as exc:
                raise RuntimeError(
                    f"Could not start ALSA realtime output: {' '.join(command)}"
                ) from exc
            # Give aplay a moment to reject an invalid device before treating
            # the stream as ready; this keeps the ordinary TTS fallback safe.
            time.sleep(0.03)
            if process.poll() is not None:
                detail = self._read_process_error(process)
                raise RuntimeError(
                    f"ALSA realtime output could not open {' '.join(command)}"
                    + (f"\\n{detail}" if detail else "")
                )
            self.device = device
            self._process = process

    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            process = self._process
            if process is None:
                raise RuntimeError("ALSA realtime output stream is not started.")
            if process.poll() is not None:
                detail = self._read_process_error(process)
                raise RuntimeError(
                    "ALSA realtime output stopped unexpectedly"
                    + (f": {detail}" if detail else ".")
                )
            if process.stdin is None:
                raise RuntimeError("ALSA realtime output has no stdin stream.")
            try:
                process.stdin.write(data)
                process.stdin.flush()
                # Feed the exact PCM sent to the speaker into AEC3's reverse
                # stream. Import lazily so ordinary audio playback still works
                # on development hosts without the optional native bridge.
                try:
                    from multimodal.webrtc_aec3 import reference_bus
                    reference_bus.publish(data, self.samplerate)
                except Exception:
                    pass
            except (BrokenPipeError, OSError) as exc:
                detail = self._read_process_error(process)
                raise RuntimeError(
                    "Could not write realtime PCM to ALSA output"
                    + (f": {detail}" if detail else "")
                ) from exc

    def stop(self) -> None:
        self._shutdown(drain=True)

    def abort(self) -> None:
        """Stop immediately when an interaction interrupts playback."""
        self._shutdown(drain=False)

    def close(self) -> None:
        self.stop()

    def _shutdown(self, *, drain: bool) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if drain:
                try:
                    process.wait(timeout=2.0)
                    return
                except subprocess.TimeoutExpired:
                    pass
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
        finally:
            self._read_process_error(process)

    @staticmethod
    def _read_process_error(process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None:
            return ""
        try:
            return process.stderr.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""


def open_raw_input_stream(
    config: AudioDeviceConfig,
    *,
    blocksize: int,
    callback: Any,
    sounddevice_module: Any | None = None,
) -> Any:
    """Open the configured microphone using ALSA on the board or sounddevice elsewhere."""
    alsa_device = resolve_alsa_input_device(config)
    if alsa_device:
        return AlsaRawInputStream(
            device=alsa_device,
            samplerate=config.sample_rate,
            blocksize=blocksize,
            channels=config.channels,
            dtype="int16",
            callback=callback,
            gain=resolve_alsa_input_gain(config),
        )
    sd = sounddevice_module or import_sounddevice()
    return sd.RawInputStream(
        samplerate=config.sample_rate,
        blocksize=blocksize,
        channels=config.channels,
        dtype="int16",
        device=config.input_device,
        callback=callback,
    )


def import_numpy() -> Any:
    try:
        import numpy as np

        return np
    except Exception as exc:  # pragma: no cover - depends on local deps
        raise RuntimeError("Missing audio dependency: numpy") from exc


def import_sounddevice() -> Any:
    try:
        import sounddevice as sd

        return sd
    except Exception as exc:  # pragma: no cover - depends on local audio deps
        raise RuntimeError("Missing audio dependency: sounddevice") from exc


def import_audio_libs() -> tuple[Any, Any]:
    # Board deployments use ``arecord`` directly. Avoid importing PortAudio
    # merely to satisfy a legacy return shape: on some Qualcomm images that
    # import can block even though the ALSA path is fully usable.
    if resolve_alsa_input_device():
        return import_numpy(), None
    try:
        return import_numpy(), import_sounddevice()
    except Exception as exc:  # pragma: no cover - depends on local audio deps
        raise RuntimeError("Missing audio dependencies: sounddevice and numpy") from exc


def list_devices() -> Any:
    _np, sd = import_audio_libs()
    return sd.query_devices()


def record_wav(
    path: Path | str = DEFAULT_INPUT_WAV,
    *,
    seconds: int = 5,
    config: AudioDeviceConfig | None = None,
) -> tuple[Path, float]:
    """Record fixed-length microphone audio to a WAV file."""
    np, sd = import_audio_libs()
    device_config = config or AudioDeviceConfig()
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    audio = sd.rec(
        int(seconds * device_config.sample_rate),
        samplerate=device_config.sample_rate,
        channels=device_config.channels,
        dtype="int16",
        device=device_config.input_device,
    )
    sd.wait()
    audio = np.asarray(audio, dtype=np.int16)
    rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) if audio.size else 0.0

    with wave.open(str(out_path), "wb") as wav_file:
        wav_file.setnchannels(device_config.channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(device_config.sample_rate)
        wav_file.writeframes(audio.tobytes())

    return out_path, rms


def play_wav(
    path: Path | str,
    *,
    output_device: int | None = None,
    interrupt_event: threading.Event | None = None,
) -> bool:
    """Play a WAV file through the configured output device."""
    output_volume = load_output_volume()
    if output_device == BOARD_APLAY_OUTPUT_DEVICE:
        if interrupt_event is not None and interrupt_event.is_set():
            return False
        with _AUDIO_PLAY_LOCK:
            if interrupt_event is not None and interrupt_event.is_set():
                return False
            with _volume_adjusted_wav(path, output_volume) as playback_path:
                play_wav_lahaina_aplay(
                    playback_path,
                    interrupt_event=interrupt_event,
                )
        return True

    np, sd = import_audio_libs()
    wav_path = Path(path)
    if not wav_path.exists():
        raise FileNotFoundError(wav_path)

    with _AUDIO_PLAY_LOCK:
        with wave.open(str(wav_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

        if sample_width == 2:
            audio = np.frombuffer(frames, dtype=np.int16)
            audio_float = audio.astype(np.float32) / 32768.0
        elif sample_width == 1:
            audio = np.frombuffer(frames, dtype=np.uint8)
            audio_float = (audio.astype(np.float32) - 128.0) / 128.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype=np.int32)
            audio_float = audio.astype(np.float32) / 2147483648.0
        else:
            raise RuntimeError(f"Unsupported WAV sample width: {sample_width} bytes")

        if channels > 1:
            audio_float = audio_float.reshape(-1, channels)
        audio_float = audio_float * (output_volume / 100.0)

        if interrupt_event is None:
            sd.play(audio_float, samplerate=sample_rate, device=output_device)
            sd.wait()
            return True

        if interrupt_event.is_set():
            return False

        playback_audio = audio_float.reshape(-1, 1) if channels == 1 else audio_float
        frame_count = len(playback_audio)
        chunk_frames = max(1, int(sample_rate * 0.05))
        with sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            device=output_device,
        ) as stream:
            for start in range(0, frame_count, chunk_frames):
                if interrupt_event.is_set():
                    return False
                stream.write(playback_audio[start : start + chunk_frames])
        return True


@contextmanager
def _volume_adjusted_wav(path: Path | str, volume: int):
    """Yield a temporary PCM WAV with software gain for the board aplay path."""
    wav_path = Path(path)
    bounded = max(0, min(100, int(volume)))
    if bounded >= 100:
        yield wav_path
        return

    temporary_name = ""
    try:
        with wave.open(str(wav_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frames = source.readframes(source.getnframes())

        adjusted = _scale_pcm_frames(frames, sample_width, bounded / 100.0)
        with tempfile.NamedTemporaryFile(
            prefix="xingbao-volume-",
            suffix=".wav",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        with wave.open(temporary_name, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(sample_width)
            target.setframerate(sample_rate)
            target.writeframes(adjusted)
        yield Path(temporary_name)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _scale_pcm_frames(frames: bytes, sample_width: int, gain: float) -> bytes:
    gain = max(0.0, min(1.0, float(gain)))
    if sample_width == 1:
        return bytes(
            max(0, min(255, round(128 + (sample - 128) * gain)))
            for sample in frames
        )
    typecode = {2: "h", 4: "i"}.get(sample_width)
    if typecode is None:
        raise RuntimeError(f"Unsupported WAV sample width: {sample_width} bytes")
    samples = array.array(typecode)
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    minimum = -(1 << (sample_width * 8 - 1))
    maximum = (1 << (sample_width * 8 - 1)) - 1
    for index, sample in enumerate(samples):
        samples[index] = max(minimum, min(maximum, round(sample * gain)))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def wait_for_audio_playback_idle(*, settle_seconds: float = 0.2) -> None:
    """Wait until queued board playback finishes before opening the microphone."""
    with _AUDIO_PLAY_LOCK:
        pass
    if settle_seconds > 0:
        time.sleep(settle_seconds)


def get_lahaina_sound_card_index(card_name: str = LAHAINA_CARD_NAME) -> str:
    """Return the ALSA card index for the board's lahaina audio card."""
    cards_path = Path("/proc/asound/cards")
    try:
        output = cards_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise RuntimeError(f"Cannot read {cards_path}.") from exc

    wanted = card_name.lower()
    pattern = re.compile(r"^\s*(\d+)\s+\[([^]]+)\]")
    for line in output.splitlines():
        match = pattern.match(line)
        if match and wanted in (line + " " + match.group(2)).lower():
            return match.group(1)
    raise RuntimeError(f"Sound card '{card_name}' not found in /proc/asound/cards.")


def configure_lahaina_output_mixer(card_index: str | int | None = None) -> str:
    """Configure the lahaina board mixer route used by the reference playback code."""
    card = str(card_index) if card_index is not None else get_lahaina_sound_card_index()
    if card in _LAHAINA_MIXER_CONFIGURED_CARDS:
        return card

    for control, value in LAHAINA_MIXER_SETTINGS:
        command = ["amixer", "-q", "-c", card, "cset", f"name={control}", value]
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Board audio mixer command failed: {' '.join(command)}\n{detail}")

    _LAHAINA_MIXER_CONFIGURED_CARDS.add(card)
    return card


def play_wav_lahaina_aplay(
    path: Path | str,
    *,
    card_index: str | int | None = None,
    interrupt_event: threading.Event | None = None,
) -> None:
    """Play a WAV through the board's lahaina ALSA route using aplay."""
    wav_path = Path(path)
    if not wav_path.exists():
        raise FileNotFoundError(wav_path)
    if wav_path.suffix.lower() != ".wav":
        raise RuntimeError("Board audio playback currently supports WAV files only.")
    if interrupt_event is not None and interrupt_event.is_set():
        return
    card = configure_lahaina_output_mixer(card_index)
    # Stream PCM instead of handing the whole WAV to aplay. This preserves the
    # exact render reference needed by AEC3 while retaining interrupt support.
    with wave.open(str(wav_path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        if sample_width != 2:
            raise RuntimeError("Board AEC playback requires 16-bit PCM WAV files.")
        pcm = source.readframes(source.getnframes())
    command = [
        "aplay", "-q", "-D", f"plughw:{card},0", "-t", "raw", "-f", "S16_LE",
        "-c", str(channels), "-r", str(sample_rate),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    try:
        chunk_bytes = max(channels * 2, int(sample_rate * channels * 2 * 0.02))
        for offset in range(0, len(pcm), chunk_bytes):
            if interrupt_event is not None and interrupt_event.is_set():
                process.terminate()
                process.wait(timeout=0.5)
                return
            chunk = pcm[offset : offset + chunk_bytes]
            if process.stdin is None:
                raise RuntimeError("Board audio playback has no PCM input pipe.")
            process.stdin.write(chunk)
            process.stdin.flush()
            try:
                from multimodal.webrtc_aec3 import reference_bus
                reference_bus.publish(chunk, sample_rate)
            except Exception:
                pass
        if process.stdin is not None:
            process.stdin.close()
        process.wait()
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
    stdout = process.stdout.read() if process.stdout is not None else b""
    stderr = process.stderr.read() if process.stderr is not None else b""
    if process.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", "replace").strip()
        raise RuntimeError(f"Board audio playback failed: {' '.join(command)}\n{detail}")


def local_tts_windows(text: str) -> None:
    """Use Windows local speech as a fallback without cloud TTS."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("Windows local TTS is only available on Windows.")
    safe = text.replace("'", "''")
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Speak('{safe}');",
    ]
    subprocess.run(command, check=False)


@dataclass
class _TTSPlaybackJob:
    text: str
    tts_client: DashScopeTTSClient | None
    no_tts: bool
    local_fallback: bool
    out_wav: Path | str
    output_device: int | None
    interrupt_event: threading.Event | None
    done: threading.Event
    result: Path | None = None
    error: BaseException | None = None


class TTSPlaybackQueue:
    """Serializes ordinary TTS synthesis and playback across threads."""

    def __init__(self) -> None:
        self._queue: queue.Queue[_TTSPlaybackJob | None] = queue.Queue()
        self._worker = threading.Thread(
            target=self._run,
            name="tts-playback-queue",
            daemon=True,
        )
        self._worker.start()

    def speak(
        self,
        text: str,
        *,
        tts_client: DashScopeTTSClient | None = None,
        no_tts: bool = False,
        local_fallback: bool = False,
        out_wav: Path | str = DEFAULT_REPLY_WAV,
        output_device: int | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> Path | None:
        if no_tts:
            return None
        if getattr(_TTS_QUEUE_LOCAL, "in_worker", False):
            return _speak_direct(
                text,
                tts_client=tts_client,
                no_tts=no_tts,
                local_fallback=local_fallback,
                out_wav=out_wav,
                output_device=output_device,
                interrupt_event=interrupt_event,
            )

        job = _TTSPlaybackJob(
            text=text,
            tts_client=tts_client,
            no_tts=no_tts,
            local_fallback=local_fallback,
            out_wav=out_wav,
            output_device=output_device,
            interrupt_event=interrupt_event,
            done=threading.Event(),
        )
        self._queue.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error
        return job.result

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        done = threading.Event()
        self._queue.put(
            _TTSPlaybackJob(
                text="",
                tts_client=None,
                no_tts=True,
                local_fallback=False,
                out_wav=DEFAULT_REPLY_WAV,
                output_device=None,
                interrupt_event=None,
                done=done,
            )
        )
        return done.wait(timeout=max(0.0, timeout))

    def _run(self) -> None:
        _TTS_QUEUE_LOCAL.in_worker = True
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                if job.no_tts and not job.text:
                    job.done.set()
                    continue
                try:
                    if job.interrupt_event is not None and job.interrupt_event.is_set():
                        job.result = None
                    else:
                        job.result = _speak_direct(
                            job.text,
                            tts_client=job.tts_client,
                            no_tts=job.no_tts,
                            local_fallback=job.local_fallback,
                            out_wav=job.out_wav,
                            output_device=job.output_device,
                            interrupt_event=job.interrupt_event,
                        )
                except BaseException as exc:
                    job.error = exc
                finally:
                    job.done.set()
            finally:
                self._queue.task_done()


_TTS_PLAYBACK_QUEUE = TTSPlaybackQueue()


def wait_for_tts_queue_idle(*, timeout: float = 5.0) -> bool:
    """Wait until ordinary queued TTS work submitted before this call has finished."""
    return _TTS_PLAYBACK_QUEUE.wait_until_idle(timeout=timeout)


def generate_chime_wav(path: Path | str = DEFAULT_CHIME_ACK_WAV, sample_rate: int = 24000) -> Path:
    """Generate a short local chime used as an immediate acknowledgement."""
    np = import_numpy()
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and out_path.stat().st_size > 1000:
        return out_path

    parts = []
    for frequency, duration, amplitude in (
        (660, 0.16, 0.23),
        (0, 0.05, 0.0),
        (880, 0.22, 0.20),
        (0, 0.19, 0.0),
    ):
        sample_count = int(sample_rate * duration)
        if frequency <= 0:
            wave_data = np.zeros(sample_count, dtype=np.float32)
        else:
            t = np.arange(sample_count, dtype=np.float32) / sample_rate
            wave_data = amplitude * np.sin(2 * np.pi * frequency * t)
            fade = max(1, int(sample_rate * 0.025))
            wave_data[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            wave_data[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        parts.append(wave_data)

    audio = np.concatenate(parts)
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return out_path


class QuickAckManager:
    """Prepares and plays the fast acknowledgement sound."""

    def __init__(
        self,
        *,
        tts_client: DashScopeTTSClient | None = None,
        quick_ack_text: str = DEFAULT_QUICK_ACK_TEXT,
        cloud_ack_path: Path | str = DEFAULT_QUICK_ACK_WAV,
        chime_ack_path: Path | str = DEFAULT_CHIME_ACK_WAV,
        use_cloud_cache: bool = False,
        output_device: int | None = None,
    ) -> None:
        self.tts_client = tts_client
        self.quick_ack_text = quick_ack_text
        self.cloud_ack_path = Path(cloud_ack_path)
        self.chime_ack_path = Path(chime_ack_path)
        self.use_cloud_cache = use_cloud_cache
        self.output_device = output_device
        self._ack_wav_path: Path | None = None

    def prepare(self) -> Path:
        if self._ack_wav_path is not None and self._ack_wav_path.exists():
            return self._ack_wav_path

        generate_chime_wav(self.chime_ack_path)
        if self.use_cloud_cache and self.tts_client is not None:
            if self.cloud_ack_path.exists() and self.cloud_ack_path.stat().st_size > 1000:
                self._ack_wav_path = self.cloud_ack_path
                return self._ack_wav_path
            try:
                self._ack_wav_path = self.tts_client.synthesize(
                    self.quick_ack_text,
                    self.cloud_ack_path,
                )
                return self._ack_wav_path
            except Exception:
                pass

        self._ack_wav_path = self.chime_ack_path
        return self._ack_wav_path

    def play_async(self, deadline_start: float | None = None) -> threading.Thread:
        ack_path = self.prepare()

        def worker() -> None:
            if deadline_start is not None:
                _ = time.perf_counter() - deadline_start
            # A quick acknowledgement is optional.  The board audio device
            # can briefly be occupied by a just-finished TTS stream; never
            # leave an unhandled exception in this daemon thread.
            try:
                play_wav(ack_path, output_device=self.output_device)
            except Exception:
                pass

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread


def speak(
    text: str,
    *,
    tts_client: DashScopeTTSClient | None = None,
    no_tts: bool = False,
    local_fallback: bool = False,
    out_wav: Path | str = DEFAULT_REPLY_WAV,
    output_device: int | None = None,
    interrupt_event: threading.Event | None = None,
) -> Path | None:
    """Queue one ordinary TTS utterance and wait until it finishes."""
    return _TTS_PLAYBACK_QUEUE.speak(
        text,
        tts_client=tts_client,
        no_tts=no_tts,
        local_fallback=local_fallback,
        out_wav=out_wav,
        output_device=output_device,
        interrupt_event=interrupt_event,
    )


def speak_interruptible_direct(
    text: str,
    *,
    tts_client: DashScopeTTSClient | None = None,
    no_tts: bool = False,
    local_fallback: bool = False,
    out_wav: Path | str = DEFAULT_REPLY_WAV,
    output_device: int | None = None,
    interrupt_event: threading.Event | None = None,
) -> Path | None:
    """Synthesize independently so a newer replaceable utterance is not queued behind it."""
    return _speak_direct(
        text,
        tts_client=tts_client,
        no_tts=no_tts,
        local_fallback=local_fallback,
        out_wav=out_wav,
        output_device=output_device,
        interrupt_event=interrupt_event,
    )


def _speak_direct(
    text: str,
    *,
    tts_client: DashScopeTTSClient | None = None,
    no_tts: bool = False,
    local_fallback: bool = False,
    out_wav: Path | str = DEFAULT_REPLY_WAV,
    output_device: int | None = None,
    interrupt_event: threading.Event | None = None,
) -> Path | None:
    """Play text immediately through the realtime DashScope WebSocket stream."""
    if no_tts:
        return None
    if tts_client is None:
        if local_fallback:
            local_tts_windows(text)
            return None
        raise RuntimeError("A TTS client is required when no_tts is False.")

    try:
        if interrupt_event is not None and interrupt_event.is_set():
            return None
        player = RealtimeStreamingSpeechPlayer(
            settings=tts_client.settings,
            voice_profile=tts_client.voice_profile,
            output_device=output_device,
            interrupt_event=interrupt_event,
        )
        player.start()
        player.enqueue(text)
        player.close()
        # The realtime API yields PCM directly to the selected output device;
        # no temporary WAV file or HTTP audio URL is created.
        return None
    except Exception:
        if local_fallback:
            local_tts_windows(text)
            return None
        raise


class StreamingSpeechPlayer:
    """Streams sentence fragments on one DashScope WebSocket connection.

    The historical class name is retained for callers, but runtime playback no
    longer prefetches HTTP WAV URLs.
    """

    def __init__(
        self,
        *,
        tts_client: DashScopeTTSClient | None = None,
        no_tts: bool = False,
        local_fallback: bool = False,
        output_device: int | None = None,
        cache_dir: Path | str = Path("work/cache"),
        on_segment_start: Any | None = None,
        on_segment_done: Any | None = None,
        on_synthesis_start: Any | None = None,
        on_synthesis_done: Any | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> None:
        self.tts_client = tts_client
        self.no_tts = no_tts
        self.local_fallback = local_fallback
        self.output_device = output_device
        self.cache_dir = Path(cache_dir)
        self.on_segment_start = on_segment_start
        self.on_segment_done = on_segment_done
        self.on_synthesis_start = on_synthesis_start
        self.on_synthesis_done = on_synthesis_done
        self.interrupt_event = interrupt_event
        self._condition = threading.Condition()
        self._results: dict[int, tuple[str, Path | None, BaseException | None]] = {}
        self._synthesis_threads: list[threading.Thread] = []
        self._errors: list[BaseException] = []
        self._counter = 0
        self._closed = False
        self._next_playback_index = 1
        self._realtime_segments: list[tuple[str, int]] = []
        self._realtime_player: RealtimeStreamingSpeechPlayer | None = None
        self._use_realtime_stream = not self.no_tts
        if self._use_realtime_stream:
            if self.tts_client is None:
                if self.local_fallback:
                    self._use_realtime_stream = False
                else:
                    raise RuntimeError("A TTS client is required when no_tts is False.")
            else:
                self._realtime_player = RealtimeStreamingSpeechPlayer(
                    settings=self.tts_client.settings,
                    voice_profile=self.tts_client.voice_profile,
                    output_device=self.output_device,
                    interrupt_event=self.interrupt_event,
                )
        self._playback_thread = None
        if not self._use_realtime_stream:
            self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
            self._playback_thread.start()

    def enqueue(self, text: str) -> None:
        segment = text.strip()
        if self.interrupt_event is not None and self.interrupt_event.is_set():
            return
        if segment:
            with self._condition:
                self._counter += 1
                index = self._counter
            if self._use_realtime_stream:
                started_at = time.perf_counter()
                try:
                    if self.on_synthesis_start is not None:
                        self.on_synthesis_start(segment, index)
                    if self.on_segment_start is not None:
                        self.on_segment_start(segment, index)
                    assert self._realtime_player is not None
                    self._realtime_player.start()
                    self._realtime_player.enqueue(segment)
                    self._realtime_segments.append((segment, index))
                    if self.on_synthesis_done is not None:
                        self.on_synthesis_done(
                            segment,
                            index,
                            Path("realtime-websocket"),
                            time.perf_counter() - started_at,
                        )
                except BaseException as exc:
                    self._errors.append(exc)
                return
            thread = threading.Thread(
                target=self._synthesize_item,
                args=(index, segment),
                daemon=True,
            )
            self._synthesis_threads.append(thread)
            thread.start()

    def close(self) -> None:
        if self._use_realtime_stream:
            try:
                if self._realtime_player is not None:
                    self._realtime_player.close()
                if self.interrupt_event is None or not self.interrupt_event.is_set():
                    for segment, index in self._realtime_segments:
                        if self.on_segment_done is not None:
                            self.on_segment_done(segment, index)
            except BaseException as exc:
                self._errors.append(exc)
            if self._errors:
                raise RuntimeError("Realtime streaming TTS failed.") from self._errors[0]
            return
        for thread in self._synthesis_threads:
            thread.join()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._playback_thread is not None:
            self._playback_thread.join()
        if self._errors:
            raise RuntimeError("Streaming TTS failed.") from self._errors[0]

    def _synthesize_item(self, index: int, segment: str) -> None:
        error: BaseException | None = None
        wav_path: Path | None = None
        try:
            out_wav = self.cache_dir / f"reply_stream_{index:03d}.wav"
            started_at = time.perf_counter()
            if self.on_synthesis_start is not None:
                self.on_synthesis_start(segment, index)
            wav_path = self._synthesize_segment(segment, out_wav)
            if self.on_synthesis_done is not None:
                self.on_synthesis_done(
                    segment,
                    index,
                    wav_path,
                    time.perf_counter() - started_at,
                )
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            error = exc
            self._errors.append(exc)
        finally:
            with self._condition:
                self._results[index] = (segment, wav_path, error)
                self._condition.notify_all()

    def _playback_worker(self) -> None:
        while True:
            with self._condition:
                while self._next_playback_index not in self._results:
                    if self.interrupt_event is not None and self.interrupt_event.is_set():
                        return
                    if self._closed and self._next_playback_index > self._counter:
                        return
                    self._condition.wait(timeout=0.05)
                if self.interrupt_event is not None and self.interrupt_event.is_set():
                    return
                index = self._next_playback_index
                segment, wav_path, error = self._results.pop(index)
                self._next_playback_index += 1
            if error is not None:
                return
            try:
                if self.on_segment_start is not None:
                    self.on_segment_start(segment, index)
                if wav_path is not None:
                    play_kwargs: dict[str, Any] = {"output_device": self.output_device}
                    if self.interrupt_event is not None:
                        play_kwargs["interrupt_event"] = self.interrupt_event
                    completed = play_wav(wav_path, **play_kwargs)
                    if completed is False:
                        return
                elif self.local_fallback and not self.no_tts:
                    local_tts_windows(segment)
                if self.on_segment_done is not None:
                    self.on_segment_done(segment, index)
            except BaseException as exc:  # pragma: no cover - defensive thread boundary
                self._errors.append(exc)
                return

    def _synthesize_segment(self, segment: str, out_wav: Path) -> Path | None:
        """Legacy no-TTS/local-fallback helper; HTTP runtime playback is removed."""
        del segment, out_wav
        if self.no_tts:
            return None
        if self.local_fallback:
            return None
        raise RuntimeError("HTTP TTS playback has been removed; use realtime streaming TTS.")


class RealtimeStreamingSpeechPlayer:
    """Streams text fragments to DashScope TTS and plays PCM audio chunks immediately."""

    sample_rate = 22050
    completion_timeout_seconds = 30.0

    def __init__(
        self,
        *,
        settings: AppSettings,
        voice_profile: VoiceProfile | None = None,
        output_device: int | None = None,
        on_stream_start: Any | None = None,
        on_audio_start: Any | None = None,
        on_stream_done: Any | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> None:
        self.settings = settings
        self.voice_profile = voice_profile or VoiceProfile.from_settings(settings)
        self.output_device = output_device
        self.on_stream_start = on_stream_start
        self.on_audio_start = on_audio_start
        self.on_stream_done = on_stream_done
        self.interrupt_event = interrupt_event
        self._audio_started = False
        self._started_at = 0.0
        self._total_bytes = 0
        self._complete = threading.Event()
        self._error: BaseException | None = None
        self._stream: Any | None = None
        self._synthesizer: Any | None = None
        self._callback: Any | None = None
        self._play_lock_acquired = False
        self._stream_lock = threading.RLock()
        self._forced_interrupt = threading.Event()

    @property
    def audio_started(self) -> bool:
        return self._audio_started

    def start(self) -> None:
        """Open the realtime TTS stream before the first text fragment arrives."""
        self._ensure_started()

    def enqueue(self, text: str) -> None:
        fragment = text.strip()
        if not fragment or self._is_interrupted():
            return
        self._ensure_started()
        self._synthesizer.streaming_call(fragment)

    def _is_interrupted(self) -> bool:
        return self._forced_interrupt.is_set() or (
            self.interrupt_event is not None and self.interrupt_event.is_set()
        )

    def interrupt_for_priority(self) -> bool:
        """Abort device output now so a local safety WAV can play immediately."""
        self._forced_interrupt.set()
        if self.interrupt_event is not None:
            self.interrupt_event.set()
        with self._stream_lock:
            had_active_stream = self._stream is not None or self._play_lock_acquired
            stream = self._stream
            self._stream = None
            if stream is not None:
                try:
                    if hasattr(stream, "abort"):
                        stream.abort()
                    else:
                        stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            if self._play_lock_acquired:
                self._play_lock_acquired = False
                _AUDIO_PLAY_LOCK.release()
        self._complete.set()
        self._clear_active_player()
        return had_active_stream

    def _set_active_player(self) -> None:
        global _ACTIVE_REALTIME_PLAYER
        with _ACTIVE_REALTIME_PLAYER_LOCK:
            _ACTIVE_REALTIME_PLAYER = self

    def _clear_active_player(self) -> None:
        global _ACTIVE_REALTIME_PLAYER
        with _ACTIVE_REALTIME_PLAYER_LOCK:
            if _ACTIVE_REALTIME_PLAYER is self:
                _ACTIVE_REALTIME_PLAYER = None

    def close(self) -> None:
        if self._synthesizer is None:
            return
        try:
            self._synthesizer.streaming_complete()
            if not self._complete.wait(timeout=self.completion_timeout_seconds):
                self._error = TimeoutError(
                    f"Realtime TTS did not complete within {self.completion_timeout_seconds:.1f}s."
                )
        finally:
            self._close_stream()
        if self._error is not None:
            raise RuntimeError("Realtime streaming TTS failed.") from self._error

    def _ensure_started(self) -> None:
        if self._synthesizer is not None:
            return

        dashscope, SpeechSynthesizer, AudioFormat, ResultCallback = _import_dashscope_tts()
        dashscope.api_key = get_dashscope_api_key()
        callback = self._build_callback(ResultCallback)

        _AUDIO_PLAY_LOCK.acquire()
        self._play_lock_acquired = True
        try:
            if self.output_device == BOARD_APLAY_OUTPUT_DEVICE:
                self._stream = AlsaRawOutputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                )
            else:
                sd = import_sounddevice()
                self._stream = sd.RawOutputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    device=self.output_device,
                )
            self._stream.start()
            self._started_at = time.perf_counter()
            self._callback = callback
            synthesizer_args = {
                "model": self.voice_profile.model,
                "voice": self.voice_profile.voice,
                "format": AudioFormat.PCM_22050HZ_MONO_16BIT,
                "speech_rate": self.voice_profile.rate,
                "callback": callback,
            }
            try:
                self._synthesizer = SpeechSynthesizer(**synthesizer_args)
            except TypeError as exc:
                # Older local test doubles (and any legacy SDK) may not yet
                # expose speech_rate.  Real board SDKs receive it above.
                if "speech_rate" not in str(exc):
                    raise
                synthesizer_args.pop("speech_rate")
                self._synthesizer = SpeechSynthesizer(**synthesizer_args)
            self._set_active_player()
        except BaseException:
            self._close_stream()
            raise

        if self.on_stream_start is not None:
            self.on_stream_start()

    def _build_callback(self, callback_base: Any) -> Any:
        player = self

        class Callback(callback_base):
            def on_complete(self) -> None:
                player._complete.set()

            def on_error(self, message: str) -> None:
                player._error = RuntimeError(message)
                player._complete.set()

            def on_close(self) -> None:
                player._complete.set()

            def on_event(self, message: Any) -> None:
                del message

            def on_data(self, data: bytes) -> None:
                with player._stream_lock:
                    if not data or player._stream is None or player._is_interrupted():
                        return
                    if not player._audio_started:
                        player._audio_started = True
                        if player.on_audio_start is not None:
                            player.on_audio_start(len(data))
                    player._total_bytes += len(data)
                    player._stream.write(data)

        return Callback()

    def _close_stream(self) -> None:
        elapsed_seconds = time.perf_counter() - self._started_at if self._started_at else 0.0
        try:
            with self._stream_lock:
                stream = self._stream
                self._stream = None
                if stream is not None:
                    if self._is_interrupted() and hasattr(stream, "abort"):
                        stream.abort()
                    else:
                        stream.stop()
                    stream.close()
        finally:
            with self._stream_lock:
                if self._play_lock_acquired:
                    self._play_lock_acquired = False
                    _AUDIO_PLAY_LOCK.release()
            self._clear_active_player()
        if self.on_stream_done is not None and self._started_at and self._error is None:
            self.on_stream_done(self._total_bytes, elapsed_seconds)


def _import_dashscope_tts() -> tuple[Any, Any, Any, Any]:
    try:
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer

        return dashscope, SpeechSynthesizer, AudioFormat, ResultCallback
    except Exception as exc:  # pragma: no cover - optional realtime dependency
        raise RuntimeError(
            "Realtime TTS requires the DashScope SDK. Install it with "
            "`python -m pip install dashscope` or update the virtual environment "
            "from requirements.txt."
        ) from exc


def check_realtime_tts_ready(
    settings: AppSettings | None = None,
    voice_profile: VoiceProfile | None = None,
    *,
    output_device: int | None = None,
) -> dict[str, Any]:
    """Validate realtime TTS dependencies and the selected local audio sink."""
    active_settings = settings or AppSettings.load()
    active_profile = voice_profile or VoiceProfile.from_settings(active_settings)
    _import_dashscope_tts()
    get_dashscope_api_key()
    backend = "sounddevice"
    if output_device == BOARD_APLAY_OUTPUT_DEVICE:
        backend = "alsa_aplay"
        stream = AlsaRawOutputStream(
            samplerate=RealtimeStreamingSpeechPlayer.sample_rate,
            channels=1,
        )
        stream.start()
        stream.close()
    else:
        import_sounddevice()
    return {
        "status": "ready",
        "backend": backend,
        "voice_profile_id": active_profile.id,
        "model": active_profile.model,
        "voice": active_profile.voice,
        "sample_rate": RealtimeStreamingSpeechPlayer.sample_rate,
    }
