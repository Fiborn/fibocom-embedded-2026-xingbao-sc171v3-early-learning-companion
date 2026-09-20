"""WebRTC AEC3 bridge for full-duplex board audio.

The board records from USB ALSA while its speaker is driven through a separate
ALSA route.  This module keeps the rendered PCM as WebRTC's reverse stream and
returns echo-reduced microphone frames for barge-in VAD.
"""

from __future__ import annotations

import audioop
import ctypes
import os
import threading
from datetime import datetime, timezone
from collections import deque
from pathlib import Path


_SAMPLE_RATE = 16000
_FRAME_BYTES = _SAMPLE_RATE // 100 * 2
_BRIDGE_PATH = Path(__file__).resolve().parents[1] / "native" / "libxingbao_aec3.so"
_AEC3_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "xingbao-aec3.log"
_AEC3_LOG_LOCK = threading.Lock()


def log_aec3(message: str) -> None:
    """Append concise AEC3 diagnostics without mixing them into voice logs."""
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    line = f"{timestamp} {message}\n"
    try:
        _AEC3_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AEC3_LOG_LOCK, _AEC3_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


class Aec3Processor:
    def __init__(self, *, delay_ms: int = 110) -> None:
        library = ctypes.CDLL(str(_BRIDGE_PATH))
        library.xingbao_aec3_create.argtypes = (ctypes.c_int,)
        library.xingbao_aec3_create.restype = ctypes.c_void_p
        library.xingbao_aec3_destroy.argtypes = (ctypes.c_void_p,)
        library.xingbao_aec3_render.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        library.xingbao_aec3_capture.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
        self._library = library
        self._state = library.xingbao_aec3_create(_SAMPLE_RATE)
        if not self._state:
            raise RuntimeError("WebRTC AEC3 initialization failed")
        self._delay_ms = max(0, min(500, int(delay_ms)))
        self._render = bytearray()
        self._lock = threading.Lock()

    def close(self) -> None:
        if self._state:
            self._library.xingbao_aec3_destroy(self._state)
            self._state = None

    def add_render(self, pcm: bytes, sample_rate: int) -> None:
        if not pcm:
            return
        converted, _ = audioop.ratecv(pcm, 2, 1, int(sample_rate), _SAMPLE_RATE, None)
        with self._lock:
            self._render.extend(converted)
            del self._render[:-_FRAME_BYTES * 80]  # retain <=800 ms reference

    def process_capture(self, pcm: bytes, sample_rate: int = _SAMPLE_RATE) -> bytes:
        converted, state = audioop.ratecv(pcm, 2, 1, int(sample_rate), _SAMPLE_RATE, None)
        del state
        output = bytearray()
        with self._lock:
            while len(converted) >= _FRAME_BYTES:
                near = converted[:_FRAME_BYTES]
                converted = converted[_FRAME_BYTES:]
                far = bytes(self._render[:_FRAME_BYTES]) if len(self._render) >= _FRAME_BYTES else bytes(_FRAME_BYTES)
                if len(self._render) >= _FRAME_BYTES:
                    del self._render[:_FRAME_BYTES]
                far_out = ctypes.create_string_buffer(far, _FRAME_BYTES)
                near_in = ctypes.create_string_buffer(near, _FRAME_BYTES)
                near_out = ctypes.create_string_buffer(_FRAME_BYTES)
                self._library.xingbao_aec3_render(self._state, far_out, far_out)
                status = self._library.xingbao_aec3_capture(self._state, near_in, near_out, self._delay_ms)
                output.extend(near_out.raw if status == 0 else near)
        if int(sample_rate) == _SAMPLE_RATE:
            return bytes(output)
        restored, _ = audioop.ratecv(bytes(output), 2, 1, _SAMPLE_RATE, int(sample_rate), None)
        return restored


class TimestampedAec3Processor(Aec3Processor):
    """AEC3 test processor that selects reverse frames by monotonic time.

    This is intentionally separate from the production FIFO processor until
    acoustic measurements prove that timestamp matching reduces residual echo.
    """

    def __init__(self, *, acoustic_delay_ms: int) -> None:
        # Render frames are selected by physical delay, so APM itself receives
        # aligned near/far blocks and uses no additional software delay.
        super().__init__(delay_ms=0)
        self._acoustic_delay_seconds = max(0.0, min(0.5, acoustic_delay_ms / 1000.0))
        self._timed_render: deque[tuple[float, bytes]] = deque()

    def add_render_at(self, pcm: bytes, sample_rate: int, timestamp: float) -> None:
        converted, _ = audioop.ratecv(pcm, 2, 1, int(sample_rate), _SAMPLE_RATE, None)
        with self._lock:
            for offset in range(0, len(converted) - _FRAME_BYTES + 1, _FRAME_BYTES):
                frame_timestamp = timestamp + (offset // 2) / _SAMPLE_RATE
                self._timed_render.append((frame_timestamp, converted[offset : offset + _FRAME_BYTES]))
            while len(self._timed_render) > 300:
                self._timed_render.popleft()

    def process_capture_at(self, pcm: bytes, capture_timestamp: float, sample_rate: int = _SAMPLE_RATE) -> bytes:
        converted, _ = audioop.ratecv(pcm, 2, 1, int(sample_rate), _SAMPLE_RATE, None)
        output = bytearray()
        frame_count = len(converted) // _FRAME_BYTES
        with self._lock:
            for index in range(frame_count):
                near = converted[index * _FRAME_BYTES : (index + 1) * _FRAME_BYTES]
                # ALSA callback timestamps the end of its block; derive each
                # 10 ms frame's start time before matching the physical echo.
                near_start = capture_timestamp - (frame_count - index) * 0.01
                target = near_start - self._acoustic_delay_seconds
                far = self._nearest_render_frame(target)
                far_out = ctypes.create_string_buffer(far, _FRAME_BYTES)
                near_in = ctypes.create_string_buffer(near, _FRAME_BYTES)
                near_out = ctypes.create_string_buffer(_FRAME_BYTES)
                self._library.xingbao_aec3_render(self._state, far_out, far_out)
                status = self._library.xingbao_aec3_capture(self._state, near_in, near_out, 0)
                output.extend(near_out.raw if status == 0 else near)
        if int(sample_rate) == _SAMPLE_RATE:
            return bytes(output)
        restored, _ = audioop.ratecv(bytes(output), 2, 1, _SAMPLE_RATE, int(sample_rate), None)
        return restored

    def _nearest_render_frame(self, target: float) -> bytes:
        while len(self._timed_render) > 1 and self._timed_render[1][0] <= target:
            self._timed_render.popleft()
        if not self._timed_render:
            return bytes(_FRAME_BYTES)
        candidate_time, candidate = self._timed_render[0]
        if abs(candidate_time - target) > 0.040:
            return bytes(_FRAME_BYTES)
        return candidate


class _ReferenceBus:
    def __init__(self) -> None:
        self._processors: set[Aec3Processor] = set()
        self._lock = threading.Lock()

    def register(self, processor: Aec3Processor) -> None:
        with self._lock:
            self._processors.add(processor)

    def unregister(self, processor: Aec3Processor) -> None:
        with self._lock:
            self._processors.discard(processor)
        processor.close()

    def publish(self, pcm: bytes, sample_rate: int) -> None:
        with self._lock:
            processors = tuple(self._processors)
        for processor in processors:
            processor.add_render(pcm, sample_rate)


reference_bus = _ReferenceBus()


def aec3_enabled() -> bool:
    return os.getenv("XINGBAO_ENABLE_WEBRTC_AEC3", "1").strip().lower() not in {"0", "false", "no"}
