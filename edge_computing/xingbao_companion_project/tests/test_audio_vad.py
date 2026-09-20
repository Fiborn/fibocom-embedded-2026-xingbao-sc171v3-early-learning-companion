import math
import threading
import wave
from pathlib import Path

import pytest

from core.settings import AppSettings
from core.voice_profiles import VoiceProfile
from multimodal.audio_io import (
    RealtimeStreamingSpeechPlayer,
    StreamingSpeechPlayer,
    _scale_pcm_frames,
    generate_chime_wav,
    speak,
)
from multimodal.vad import NoSpeechTimeout, VADConfig, capture_utterance_vad, frame_rms_bytes, save_frames_to_wav


def test_save_frames_to_wav_writes_valid_file(tmp_path: Path) -> None:
    out_path = tmp_path / "sample.wav"

    result = save_frames_to_wav(out_path, [b"\x01\x00\x02\x00"], sample_rate=16000)

    assert result == out_path
    with wave.open(str(out_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 2


def test_frame_rms_bytes_computes_int16_rms() -> None:
    frame = (1000).to_bytes(2, "little", signed=True) + (-1000).to_bytes(
        2,
        "little",
        signed=True,
    )

    assert math.isclose(frame_rms_bytes(frame), 1000.0)


def test_generate_chime_wav_writes_audio_file(tmp_path: Path) -> None:
    out_path = generate_chime_wav(tmp_path / "chime.wav")

    assert out_path.exists()
    assert out_path.stat().st_size > 1000


def test_scale_pcm_frames_applies_playback_volume() -> None:
    frames = (
        (10000).to_bytes(2, "little", signed=True)
        + (-10000).to_bytes(2, "little", signed=True)
    )

    scaled = _scale_pcm_frames(frames, 2, 0.4)

    assert int.from_bytes(scaled[:2], "little", signed=True) == 4000
    assert int.from_bytes(scaled[2:], "little", signed=True) == -4000


def test_speak_no_tts_is_noop() -> None:
    assert speak("hello", no_tts=True) is None


def test_speak_requires_tts_client_when_enabled() -> None:
    with pytest.raises(RuntimeError):
        speak("hello")


def test_speak_serializes_tts_jobs_in_submission_order(monkeypatch, tmp_path: Path) -> None:
    first_synthesis_started = threading.Event()
    allow_first_playback_to_finish = threading.Event()
    synthesized: list[str] = []
    played: list[str] = []

    class FakeTTSClient:
        def synthesize(self, text: str, out_wav: Path) -> Path:
            synthesized.append(text)
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            out_wav.write_text(text, encoding="utf-8")
            if text == "第一句":
                first_synthesis_started.set()
            return out_wav

    def fake_play_wav(
        path: Path,
        *,
        output_device: int | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> bool:
        del output_device, interrupt_event
        text = path.read_text(encoding="utf-8")
        played.append(text)
        if text == "第一句":
            allow_first_playback_to_finish.wait(timeout=1.0)
        return True

    monkeypatch.setattr("multimodal.audio_io.play_wav", fake_play_wav)
    client = FakeTTSClient()
    first = threading.Thread(
        target=lambda: speak("第一句", tts_client=client, out_wav=tmp_path / "first.wav"),
    )
    second = threading.Thread(
        target=lambda: speak("第二句", tts_client=client, out_wav=tmp_path / "second.wav"),
    )

    first.start()
    assert first_synthesis_started.wait(timeout=1.0)
    second.start()
    assert synthesized == ["第一句"]

    allow_first_playback_to_finish.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert synthesized == ["第一句", "第二句"]
    assert played == ["第一句", "第二句"]


def test_streaming_speech_player_prefetches_next_segment(monkeypatch, tmp_path: Path) -> None:
    second_synthesis_started = threading.Event()
    second_synthesized = threading.Event()
    allow_first_playback_to_finish = threading.Event()
    synthesized: list[str] = []
    played: list[str] = []
    synthesis_events: list[tuple[str, str, int]] = []

    class FakeTTSClient:
        def synthesize(self, text: str, out_wav: Path) -> Path:
            synthesized.append(text)
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            out_wav.write_text(text, encoding="utf-8")
            if text == "第二句":
                second_synthesized.set()
            return out_wav

    def fake_play_wav(path: Path, *, output_device: int | None = None) -> None:
        del output_device
        text = path.read_text(encoding="utf-8")
        played.append(text)
        if text == "第一句":
            assert second_synthesis_started.wait(timeout=1.0)
            assert second_synthesized.wait(timeout=1.0)
            allow_first_playback_to_finish.wait(timeout=1.0)

    monkeypatch.setattr("multimodal.audio_io.play_wav", fake_play_wav)
    player = StreamingSpeechPlayer(
        tts_client=FakeTTSClient(),  # type: ignore[arg-type]
        cache_dir=tmp_path,
        on_synthesis_start=lambda text, index: (
            synthesis_events.append(("start", text, index)),
            second_synthesis_started.set() if text == "第二句" else None,
        ),
        on_synthesis_done=lambda text, index, wav_path, elapsed: synthesis_events.append(
            ("done", text, index)
        ),
    )

    player.enqueue("第一句")
    player.enqueue("第二句")
    assert second_synthesized.wait(timeout=1.0)
    allow_first_playback_to_finish.set()
    player.close()

    assert synthesized == ["第一句", "第二句"]
    assert played == ["第一句", "第二句"]
    assert ("start", "第一句", 1) in synthesis_events
    assert ("done", "第一句", 1) in synthesis_events
    assert ("start", "第二句", 2) in synthesis_events
    assert ("done", "第二句", 2) in synthesis_events


def test_realtime_streaming_speech_player_writes_pcm_chunks(monkeypatch) -> None:
    class FakeDashScope:
        api_key = ""

    class FakeAudioFormat:
        PCM_22050HZ_MONO_16BIT = "pcm"

    class FakeResultCallback:
        pass

    class FakeSpeechSynthesizer:
        def __init__(self, *, model: str, voice: str, format: str, callback) -> None:
            assert model == "cosyvoice-v3-flash"
            assert voice == "longanyang"
            assert format == "pcm"
            self.callback = callback

        def streaming_call(self, text: str) -> None:
            self.callback.on_data(text.encode("utf-8"))

        def streaming_complete(self) -> None:
            self.callback.on_complete()

    class FakeRawOutputStream:
        written: list[bytes] = []

        def __init__(self, **kwargs) -> None:
            assert kwargs["samplerate"] == 22050
            assert kwargs["channels"] == 1
            assert kwargs["dtype"] == "int16"

        def start(self) -> None:
            pass

        def write(self, data: bytes) -> None:
            self.written.append(data)

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeSoundDevice:
        RawOutputStream = FakeRawOutputStream

    events: list[tuple[str, int | None]] = []
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(
        "multimodal.audio_io._import_dashscope_tts",
        lambda: (FakeDashScope, FakeSpeechSynthesizer, FakeAudioFormat, FakeResultCallback),
    )
    monkeypatch.setattr("multimodal.audio_io.import_sounddevice", lambda: FakeSoundDevice)

    player = RealtimeStreamingSpeechPlayer(
        settings=AppSettings(),
        on_stream_start=lambda: events.append(("start", None)),
        on_audio_start=lambda size: events.append(("audio", size)),
        on_stream_done=lambda total, _elapsed: events.append(("done", total)),
    )

    player.start()
    player.enqueue("你好")
    player.enqueue("星宝")
    player.close()

    assert FakeDashScope.api_key == "test-key"
    assert FakeRawOutputStream.written == ["你好".encode("utf-8"), "星宝".encode("utf-8")]
    assert events[0] == ("start", None)
    assert events[1] == ("audio", len("你好".encode("utf-8")))
    assert events[-1] == ("done", len("你好星宝".encode("utf-8")))


def test_realtime_streaming_speech_player_reports_completion_timeout(monkeypatch) -> None:
    class FakeDashScope:
        api_key = ""

    class FakeAudioFormat:
        PCM_22050HZ_MONO_16BIT = "pcm"

    class FakeResultCallback:
        pass

    class HangingSpeechSynthesizer:
        def __init__(self, *, model: str, voice: str, format: str, callback) -> None:
            del model, voice, format
            self.callback = callback

        def streaming_call(self, text: str) -> None:
            self.callback.on_data(text.encode("utf-8"))

        def streaming_complete(self) -> None:
            pass

    class FakeRawOutputStream:
        closed = False

        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def write(self, _data: bytes) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            self.__class__.closed = True

    class FakeSoundDevice:
        RawOutputStream = FakeRawOutputStream

    events: list[tuple[str, int]] = []
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(
        "multimodal.audio_io._import_dashscope_tts",
        lambda: (FakeDashScope, HangingSpeechSynthesizer, FakeAudioFormat, FakeResultCallback),
    )
    monkeypatch.setattr("multimodal.audio_io.import_sounddevice", lambda: FakeSoundDevice)

    player = RealtimeStreamingSpeechPlayer(
        settings=AppSettings(),
        on_audio_start=lambda size: events.append(("audio", size)),
        on_stream_done=lambda total, _elapsed: events.append(("done", total)),
    )
    player.completion_timeout_seconds = 0.0

    player.start()
    player.enqueue("你好")
    with pytest.raises(RuntimeError, match="Realtime streaming TTS failed"):
        player.close()

    assert player.audio_started is True
    assert FakeRawOutputStream.closed is True
    assert events == [("audio", len("你好".encode("utf-8")))]


def test_realtime_streaming_speech_player_uses_voice_profile_rate(monkeypatch) -> None:
    """The camera acknowledgement can slow down without changing its voice."""
    class FakeDashScope:
        api_key = ""

    class FakeAudioFormat:
        PCM_22050HZ_MONO_16BIT = "pcm"

    class FakeResultCallback:
        pass

    class FakeSpeechSynthesizer:
        received_rate: float | None = None

        def __init__(self, *, model, voice, format, callback, speech_rate) -> None:
            del model, voice, format
            self.callback = callback
            self.__class__.received_rate = speech_rate

        def streaming_call(self, text: str) -> None:
            self.callback.on_data(text.encode("utf-8"))

        def streaming_complete(self) -> None:
            self.callback.on_complete()

    class FakeRawOutputStream:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def write(self, _data: bytes) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeSoundDevice:
        RawOutputStream = FakeRawOutputStream

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(
        "multimodal.audio_io._import_dashscope_tts",
        lambda: (FakeDashScope, FakeSpeechSynthesizer, FakeAudioFormat, FakeResultCallback),
    )
    monkeypatch.setattr("multimodal.audio_io.import_sounddevice", lambda: FakeSoundDevice)
    profile = VoiceProfile(
        id="camera_prompt",
        label="camera prompt",
        model="cosyvoice-v3-flash",
        voice="longanyang",
        rate=0.8,
    )

    player = RealtimeStreamingSpeechPlayer(settings=AppSettings(), voice_profile=profile)
    player.start()
    player.enqueue("稍等一下，我来看看。")
    player.close()

    assert FakeSpeechSynthesizer.received_rate == 0.8


def test_capture_utterance_vad_can_timeout_before_speech(monkeypatch, tmp_path: Path) -> None:
    class EmptyRawInputStream:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self) -> "EmptyRawInputStream":
            return self

        def __exit__(self, *_args) -> None:
            pass

    class FakeSoundDevice:
        RawInputStream = EmptyRawInputStream

    monkeypatch.setattr(
        "multimodal.vad.import_audio_libs",
        lambda: (__import__("numpy"), FakeSoundDevice),
    )

    with pytest.raises(NoSpeechTimeout):
        capture_utterance_vad(
            tmp_path / "none.wav",
            vad_config=VADConfig(
                calibrate_seconds=0.0,
                listen_timeout_seconds=0.01,
            ),
        )


def test_capture_utterance_vad_reports_ready_after_calibration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import numpy as np

    silence = np.zeros(480, dtype=np.int16).tobytes()
    voice = np.full(480, 1200, dtype=np.int16).tobytes()
    frames = [silence, voice, silence]
    order: list[str] = []

    class FeedingStream:
        def __init__(self, callback) -> None:
            self.callback = callback

        def __enter__(self):
            for frame in frames:
                self.callback(frame, 480, None, None)
            return self

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setattr(
        "multimodal.vad.import_audio_libs",
        lambda: (np, object()),
    )
    monkeypatch.setattr(
        "multimodal.vad.open_raw_input_stream",
        lambda _config, *, blocksize, callback, sounddevice_module: FeedingStream(
            callback
        ),
    )

    path, _metrics = capture_utterance_vad(
        tmp_path / "ready.wav",
        vad_config=VADConfig(
            frame_ms=30,
            calibrate_seconds=0.03,
            pre_roll_ms=30,
            start_hold_ms=30,
            end_silence_ms=30,
            min_utterance_ms=30,
            min_rms=100.0,
        ),
        on_listening_ready=lambda: order.append("ready"),
    )

    assert order == ["ready"]
    assert path.exists()


def test_capture_utterance_vad_keeps_recording_through_a_short_thinking_pause(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import numpy as np

    silence = np.zeros(480, dtype=np.int16).tobytes()
    first_phrase = np.full(480, 1200, dtype=np.int16).tobytes()
    second_phrase = np.full(480, 1600, dtype=np.int16).tobytes()
    # A 600 ms pause is common while a child searches for the next word.  It
    # must remain part of the same utterance when the end-silence window is 1 s.
    frames = [silence, first_phrase, *([silence] * 20), second_phrase, *([silence] * 34)]

    class FeedingStream:
        def __init__(self, callback) -> None:
            self.callback = callback

        def __enter__(self):
            for frame in frames:
                self.callback(frame, 480, None, None)
            return self

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setattr("multimodal.vad.import_audio_libs", lambda: (np, object()))
    monkeypatch.setattr(
        "multimodal.vad.open_raw_input_stream",
        lambda _config, *, blocksize, callback, sounddevice_module: FeedingStream(callback),
    )

    path, metrics = capture_utterance_vad(
        tmp_path / "continuous.wav",
        vad_config=VADConfig(
            frame_ms=30,
            calibrate_seconds=0.03,
            pre_roll_ms=30,
            start_hold_ms=30,
            end_silence_ms=1000,
            min_utterance_ms=650,
            min_rms=100.0,
        ),
    )

    assert path.exists()
    assert metrics["utterance_ms"] >= 1600.0
    with wave.open(str(path), "rb") as wav_file:
        samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
    assert 1600 in samples


def test_hybrid_vad_ends_when_loud_music_is_not_classified_as_speech(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import sys
    import numpy as np

    silence = np.zeros(480, dtype=np.int16).tobytes()
    child_voice = np.full(480, 1200, dtype=np.int16).tobytes()
    loud_music = np.full(480, 3000, dtype=np.int16).tobytes()
    frames = [silence, child_voice, loud_music, loud_music, loud_music]

    class FakeVad:
        def __init__(self, _aggressiveness: int) -> None:
            pass

        def is_speech(self, frame: bytes, _sample_rate: int) -> bool:
            level = int(np.frombuffer(frame, dtype=np.int16)[0])
            return 800 <= level <= 1800

    class FakeWebRtcModule:
        Vad = FakeVad

    class FeedingStream:
        def __init__(self, callback) -> None:
            self.callback = callback

        def __enter__(self):
            for frame in frames:
                self.callback(frame, 480, None, None)
            return self

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setitem(sys.modules, "webrtcvad", FakeWebRtcModule)
    monkeypatch.setattr("multimodal.vad.import_audio_libs", lambda: (np, object()))
    monkeypatch.setattr(
        "multimodal.vad.open_raw_input_stream",
        lambda _config, *, blocksize, callback, sounddevice_module: FeedingStream(callback),
    )

    path, metrics = capture_utterance_vad(
        tmp_path / "hybrid.wav",
        vad_config=VADConfig(
            frame_ms=30,
            calibrate_seconds=0.03,
            pre_roll_ms=30,
            start_hold_ms=30,
            end_silence_ms=60,
            min_utterance_ms=30,
            min_rms=100.0,
        ),
    )

    assert path.exists()
    assert metrics["speech_detector"] == "webrtc_rms"
    assert metrics["utterance_ms"] < 180.0


def test_hybrid_vad_ends_when_distant_video_voice_is_below_end_rms_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import sys
    import numpy as np

    silence = np.zeros(480, dtype=np.int16).tobytes()
    child_voice = np.full(480, 1200, dtype=np.int16).tobytes()
    distant_video_voice = np.full(480, 400, dtype=np.int16).tobytes()
    frames = [silence, child_voice, distant_video_voice, distant_video_voice, distant_video_voice]

    class FakeVad:
        def __init__(self, _aggressiveness: int) -> None:
            pass

        def is_speech(self, frame: bytes, _sample_rate: int) -> bool:
            level = int(np.frombuffer(frame, dtype=np.int16)[0])
            return 300 <= level <= 1800

    class FakeWebRtcModule:
        Vad = FakeVad

    class FeedingStream:
        def __init__(self, callback) -> None:
            self.callback = callback

        def __enter__(self):
            for frame in frames:
                self.callback(frame, 480, None, None)
            return self

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setitem(sys.modules, "webrtcvad", FakeWebRtcModule)
    monkeypatch.setattr("multimodal.vad.import_audio_libs", lambda: (np, object()))
    monkeypatch.setattr(
        "multimodal.vad.open_raw_input_stream",
        lambda _config, *, blocksize, callback, sounddevice_module: FeedingStream(callback),
    )

    path, metrics = capture_utterance_vad(
        tmp_path / "distant-video.wav",
        vad_config=VADConfig(
            frame_ms=30,
            calibrate_seconds=0.03,
            pre_roll_ms=30,
            start_hold_ms=30,
            end_silence_ms=60,
            min_utterance_ms=30,
            min_rms=100.0,
            manual_threshold=1000.0,
        ),
    )

    assert path.exists()
    assert metrics["end_threshold"] == 620.0
    assert metrics["utterance_ms"] < 180.0


def test_wake_vad_can_start_from_webrtc_speech_without_relative_rms_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import sys
    import numpy as np

    loud_video = np.full(480, 9000, dtype=np.int16).tobytes()
    quiet_child_voice = np.full(480, 700, dtype=np.int16).tobytes()
    silence = np.zeros(480, dtype=np.int16).tobytes()
    frames = [loud_video, quiet_child_voice, silence, silence]

    class FakeVad:
        def __init__(self, _aggressiveness: int) -> None:
            pass

        def is_speech(self, frame: bytes, _sample_rate: int) -> bool:
            level = int(np.frombuffer(frame, dtype=np.int16)[0])
            return 300 <= level <= 1500

    class FakeWebRtcModule:
        Vad = FakeVad

    class FeedingStream:
        def __init__(self, callback) -> None:
            self.callback = callback

        def __enter__(self):
            for frame in frames:
                self.callback(frame, 480, None, None)
            return self

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setitem(sys.modules, "webrtcvad", FakeWebRtcModule)
    monkeypatch.setattr("multimodal.vad.import_audio_libs", lambda: (np, object()))
    monkeypatch.setattr(
        "multimodal.vad.open_raw_input_stream",
        lambda _config, *, blocksize, callback, sounddevice_module: FeedingStream(callback),
    )

    path, metrics = capture_utterance_vad(
        tmp_path / "wake-webrtc.wav",
        vad_config=VADConfig(
            frame_ms=30,
            calibrate_seconds=0.03,
            pre_roll_ms=30,
            start_hold_ms=30,
            end_silence_ms=60,
            min_utterance_ms=30,
            threshold_multiplier=3.0,
            min_rms=180.0,
            start_requires_rms=False,
        ),
    )

    assert path.exists()
    assert metrics["start_threshold"] == 27000.0
    assert metrics["speech_detector"] == "webrtc"
