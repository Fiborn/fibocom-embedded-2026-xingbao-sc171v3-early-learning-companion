"""Local 2×3 hand-grid runtime for Xingbao high-fives.

The camera process can only emit one of six fixed high-level action names.
It cannot send joint angles, motion timings, arbitrary action groups, or
network-addressable control commands to the mechanical arm.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from core.arm_action_bridge import (
    HAND_RECOGNITION_CONTROL_HOST,
    HAND_RECOGNITION_CONTROL_PORT,
    VISION_POINT_ACTION_HOST,
    VISION_POINT_ACTION_PORT,
    send_vision_point_command,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = "http://127.0.0.1:4445/?action=stream"
DEFAULT_MODEL = ROOT / "models" / "vision" / "hand_landmarker.task"
DEFAULT_FIBO_MODEL = Path(
    os.environ.get(
        "XINGBAO_FIBO_HAND_MODEL",
        str(ROOT / "models" / "vision" / "mediapipe-hand_1.0.2_qcom_all_snpe_2.25_dsp.fmodel"),
    )
)
DEFAULT_FIBO_LICENSE_DIR = Path(
    os.environ.get("XINGBAO_FIBO_LICENSE_DIR", "/home/fibo/qcom_6490_license")
)
GRID_ACTIONS = {
    (1, 1): "vision_high_five_11",
    (1, 2): "vision_high_five_12",
    (1, 3): "vision_high_five_13",
    (2, 1): "vision_high_five_21",
    (2, 2): "vision_high_five_22",
    (2, 3): "vision_high_five_23",
}
GRID_COMMANDS = {
    (1, 1): "11",
    (1, 2): "12",
    (1, 3): "13",
    (2, 1): "21",
    (2, 2): "22",
    (2, 3): "23",
}
# The hardware service starts the neutral-to-point transition with the
# reviewed 90 x 0.04 second profile, then owns the actual 3.5 second idle
# return timer.  Keep camera recognition enabled long enough to accept a new
# stable position after the arm has physically reached its first point.
FOLLOW_IDLE_SECONDS = 3.5
FOLLOW_OUTBOUND_SECONDS = 3.6
FOLLOW_INPUT_WINDOW_SECONDS = FOLLOW_OUTBOUND_SECONDS + FOLLOW_IDLE_SECONDS + 0.4
FOLLOW_MAX_SESSION_SECONDS = 24.0
ACCEPTED_FOLLOW_QUEUE_STATUSES = frozenset(
    {
        "follow_session_started",
        "follow_redirect_accepted",
        "follow_duplicate_position",
    }
)


def grid_position(center_x: int, center_y: int, width: int, height: int) -> tuple[int, int]:
    """Map a pixel center to the fixed 2×3 calibration grid."""
    if width <= 0 or height <= 0:
        raise ValueError("invalid_frame_size")
    column = min(3, max(1, int(center_x * 3 / width) + 1))
    row = 1 if center_y < height / 2 else 2
    return row, column


@dataclass
class StableGridAction:
    """Require a position to persist before issuing one action."""

    required_frames: int = 3
    _candidate: tuple[int, int] | None = None
    _count: int = 0
    _sent: tuple[int, int] | None = None

    def reset(self) -> None:
        self._candidate = None
        self._count = 0
        self._sent = None

    def observe(self, position: tuple[int, int] | None) -> str | None:
        if position not in GRID_ACTIONS:
            self.reset()
            return None
        if position != self._candidate:
            self._candidate = position
            self._count = 1
        else:
            self._count += 1
        if self._count < max(1, int(self.required_frames)) or position == self._sent:
            return None
        self._sent = position
        return GRID_ACTIONS[position]


@dataclass
class HandPositionSampler:
    """Sample the newest camera hand position at a bounded cadence."""

    interval_seconds: float = 0.8
    _last_sample_at: float | None = None

    def reset(self) -> None:
        self._last_sample_at = None

    def is_due(self, now: float) -> bool:
        if self._last_sample_at is None or now - self._last_sample_at >= self.interval_seconds:
            self._last_sample_at = now
            return True
        return False


def follow_dispatch_accepted(receipt: object) -> tuple[bool, str]:
    """Return whether the arm service accepted a reviewed follow point."""

    if not isinstance(receipt, dict):
        return False, "missing_arm_receipt"
    feedback = receipt.get("hardware_feedback")
    if not isinstance(feedback, dict):
        return False, "missing_hardware_feedback"
    queue_status = str(feedback.get("queue_status") or "")
    if bool(feedback.get("ok")) and queue_status in ACCEPTED_FOLLOW_QUEUE_STATUSES:
        return True, queue_status
    return False, str(feedback.get("error") or receipt.get("error") or queue_status or "arm_rejected")


@dataclass
class FollowInputWindow:
    """Keep one invitation open for reviewed point changes, never raw motion."""

    idle_seconds: float = FOLLOW_INPUT_WINDOW_SECONDS
    max_session_seconds: float = FOLLOW_MAX_SESSION_SECONDS
    _started_at: float | None = None
    _last_position_at: float | None = None

    @property
    def active(self) -> bool:
        return self._started_at is not None

    def reset(self) -> None:
        self._started_at = None
        self._last_position_at = None

    def observe_action(self, now: float) -> None:
        if self._started_at is None:
            self._started_at = now
        self._last_position_at = now

    def should_close(self, now: float) -> bool:
        if self._started_at is None or self._last_position_at is None:
            return False
        return (
            now - self._started_at >= max(0.5, float(self.max_session_seconds))
            or now - self._last_position_at >= max(0.5, float(self.idle_seconds))
        )


class HandRecognitionGate:
    """Thread-safe local enable/disable state; vision starts disabled."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._generation = 0
        self._enabled_at: float | None = None
        self._follow_start_count = 0
        self._follow_redirect_count = 0
        self._last_follow_at: float | None = None

    def set_enabled(self, enabled: bool) -> tuple[bool, int]:
        with self._lock:
            if self._enabled != bool(enabled):
                self._enabled = bool(enabled)
                self._generation += 1
                self._enabled_at = time.monotonic() if self._enabled else None
                if self._enabled:
                    self._follow_start_count = 0
                    self._follow_redirect_count = 0
                    self._last_follow_at = None
            return self._enabled, self._generation

    def snapshot(self) -> tuple[bool, int]:
        with self._lock:
            return self._enabled, self._generation

    def status(self, *, now: float | None = None) -> dict[str, object]:
        """Return privacy-safe control state for completion polling."""
        with self._lock:
            checked_at = time.monotonic() if now is None else float(now)
            enabled_seconds = (
                max(0.0, checked_at - self._enabled_at)
                if self._enabled and self._enabled_at is not None
                else 0.0
            )
            last_follow_seconds_ago = (
                max(0.0, checked_at - self._last_follow_at)
                if self._last_follow_at is not None
                else None
            )
            return {
                "hand_recognition_enabled": self._enabled,
                "generation": self._generation,
                "enabled_seconds": round(enabled_seconds, 3),
                "follow_start_count": self._follow_start_count,
                "follow_redirect_count": self._follow_redirect_count,
                "last_follow_seconds_ago": (
                    round(last_follow_seconds_ago, 3)
                    if last_follow_seconds_ago is not None
                    else None
                ),
            }

    def record_follow_action(self, phase: str, *, now: float | None = None) -> None:
        """Record only a high-level accepted follow transition for narration."""
        with self._lock:
            if not self._enabled:
                return
            if phase == "follow_start":
                self._follow_start_count += 1
            elif phase == "follow_redirect":
                self._follow_redirect_count += 1
            else:
                return
            self._last_follow_at = time.monotonic() if now is None else float(now)


class _ControlHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        command = self.rfile.readline(64).decode("utf-8", errors="replace").strip().lower()
        gate: HandRecognitionGate = self.server.gate  # type: ignore[attr-defined]
        if command == "status":
            result = {"ok": True, "command": command, **gate.status()}
        elif command not in {"enable", "disable"}:
            result: dict[str, object] = {"ok": False, "error": "invalid_command", "command": command}
        else:
            enabled, generation = gate.set_enabled(command == "enable")
            result = {
                "ok": True,
                "command": command,
                "hand_recognition_enabled": enabled,
                "generation": generation,
            }
        self.wfile.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))


class HandControlServer:
    """Private localhost-only control server for a high-five invitation."""

    def __init__(self, gate: HandRecognitionGate, host: str, port: int) -> None:
        self.gate = gate
        self.host = str(host)
        self.port = int(port)
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        if self.host != "127.0.0.1":
            raise ValueError("hand_control_host_must_be_loopback")
        self._server = Server((self.host, self.port), _ControlHandler)
        self._server.gate = self.gate  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="xingbao-high-five-control",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None


class HandDetector:
    """CPU MediaPipe hand detector used by the unified visual runtime."""

    def __init__(
        self,
        model: Path,
        max_hands: int,
        threshold: float,
    ) -> None:
        self._mediapipe_config = (model, max_hands, threshold)
        self._start_mediapipe()

    def _start_mediapipe(self) -> None:
        model, max_hands, threshold = self._mediapipe_config
        import mediapipe as mp

        if not model.is_file():
            raise RuntimeError(f"hand_model_missing:{model}")
        self._mp = mp
        self._last_timestamp_ms = -1
        self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(
            mp.tasks.vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_hands=max(1, int(max_hands)),
                min_hand_detection_confidence=float(threshold),
                min_hand_presence_confidence=float(threshold),
                min_tracking_confidence=float(threshold),
            )
        )

    def detect(self, frame) -> "HandDetection | None":
        import cv2
        import numpy as np

        height, width = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )
        timestamp_ms = max(self._last_timestamp_ms + 1, int(time.monotonic() * 1000))
        self._last_timestamp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        if not result.hand_landmarks:
            return None
        ranked = list(zip(result.hand_landmarks, result.handedness))
        ranked.sort(
            key=lambda pair: float(pair[1][0].score) if pair[1] else 0.0,
            reverse=True,
        )
        landmarks, handedness = ranked[0]
        if not landmarks:
            return None
        center_x = sum(point.x for point in landmarks) / len(landmarks)
        center_y = sum(point.y for point in landmarks) / len(landmarks)
        center = (
            min(width - 1, max(0, int(round(center_x * width)))),
            min(height - 1, max(0, int(round(center_y * height)))),
        )
        x_values = [point.x for point in landmarks]
        y_values = [point.y for point in landmarks]
        pad_x = max(4, int(round((max(x_values) - min(x_values)) * width * 0.12)))
        pad_y = max(4, int(round((max(y_values) - min(y_values)) * height * 0.12)))
        box = (
            max(0, int(min(x_values) * width) - pad_x),
            max(0, int(min(y_values) * height) - pad_y),
            min(width - 1, int(max(x_values) * width) + pad_x),
            min(height - 1, int(max(y_values) * height) + pad_y),
        )
        confidence = float(handedness[0].score) if handedness else 0.0
        return HandDetection(center=center, box=box, confidence=confidence)

    def detect_center(self, frame) -> tuple[int, int] | None:
        """Compatibility wrapper for the standalone high-five runtime."""
        detection = self.detect(frame)
        return detection.center if detection is not None else None

    def close(self) -> None:
        self._landmarker.close()


class _FiboHandDetector:
    """Licensed CVAPI wrapper around Fibocom's DSP MediaPipe hand graph."""

    def __init__(self, model: Path, license_dir: Path) -> None:
        from fiboaisdk.api_aisdk_py import api_cv_py, license_py

        if not model.is_file():
            raise RuntimeError(f"fibo_hand_model_missing:{model}")
        key_paths = (license_dir / "key1.pem", license_dir / "key2.pem", license_dir / "key3.pem")
        license_path = license_dir / "license.bin"
        if not all(path.is_file() for path in (*key_paths, license_path)):
            raise RuntimeError(f"fibo_license_missing:{license_dir}")

        def read(path: Path):
            return path.read_text() if path.suffix == ".pem" else path.read_bytes()

        status = license_py.Init(*(read(path) for path in (*key_paths, license_path)))
        if status != 0:
            raise RuntimeError(f"fibo_license_init_failed:{status}")
        self._cv = api_cv_py
        self._api = api_cv_py.CVAPI()
        status = self._api.Init(str(model))
        if status != 0:
            self._api.Release()
            raise RuntimeError(f"fibo_hand_model_init_failed:{status}")

    def detect(self, frame) -> HandDetection | None:
        height, width = frame.shape[:2]
        image = self._cv.FIBO_CV_Img()
        image.width, image.height = width, height
        image.channels, image.size = frame.shape[2], frame.size
        image.format, image.layout = 0, 0  # BGR HWC; verified with CVAPI on QCS6490.
        image.data = frame.reshape(-1).tolist()
        result = self._cv.ResultCvDetect()
        status = self._api.InferCvDetectSync(image, result)
        if status != 0:
            raise RuntimeError(f"fibo_hand_infer_failed:{status}")
        detection = fibo_hand_detection_from_objects(result.objects, width=width, height=height)
        if fibo_result_requires_fallback(count=result.count, detection=detection):
            raise RuntimeError("fibo_hand_coordinates_not_exposed_by_sdk")
        return detection

    def close(self) -> None:
        self._api.Release()


@dataclass(frozen=True)
class HandDetection:
    """Privacy-local hand result shared by action routing and visualization."""

    center: tuple[int, int]
    box: tuple[int, int, int, int]
    confidence: float


def fibo_hand_detection_from_objects(
    objects: object, *, width: int, height: int
) -> HandDetection | None:
    """Convert Fibo CV detection boxes to the existing hand result contract."""
    if width <= 0 or height <= 0:
        return None
    candidates = list(objects or [])
    if not candidates:
        return None
    detected = max(candidates, key=lambda item: float(getattr(item, "score", 0.0)))
    box = getattr(detected, "bbox", None)
    if box is None:
        return None
    x1 = max(0, min(width - 1, int(getattr(box, "x", 0))))
    y1 = max(0, min(height - 1, int(getattr(box, "y", 0))))
    x2 = max(x1, min(width - 1, int(getattr(box, "x", 0)) + int(getattr(box, "w", 0))))
    y2 = max(y1, min(height - 1, int(getattr(box, "y", 0)) + int(getattr(box, "h", 0))))
    return HandDetection(
        center=((x1 + x2) // 2, (y1 + y2) // 2),
        box=(x1, y1, x2, y2),
        confidence=float(getattr(detected, "score", 0.0)),
    )


def fibo_result_requires_fallback(*, count: int, detection: HandDetection | None) -> bool:
    """The SDK can report a hand while omitting its coordinates in Python."""
    return int(count) > 0 and detection is None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Xingbao local six-point high-five vision runtime")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="MJPEG stream URL, camera index, or video path")
    parser.add_argument("--hand-model", default=str(DEFAULT_MODEL), help="MediaPipe hand-landmarker model")
    parser.add_argument("--vision-point-host", default=VISION_POINT_ACTION_HOST)
    parser.add_argument("--vision-point-port", type=int, default=VISION_POINT_ACTION_PORT)
    parser.add_argument("--vision-point-ready-timeout", type=float, default=12.0)
    parser.add_argument("--hand-control-listen-host", default=HAND_RECOGNITION_CONTROL_HOST)
    parser.add_argument("--hand-control-listen-port", type=int, default=HAND_RECOGNITION_CONTROL_PORT)
    parser.add_argument("--hand-stable-frames", type=int, default=1)
    parser.add_argument(
        "--hand-sample-seconds",
        type=float,
        default=0.8,
        help="Sample the latest hand grid no more often than this interval.",
    )
    parser.add_argument("--max-hands", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--max-frames", type=int, default=0, help="0 keeps the service running")
    return parser


def wait_for_vision_point_endpoint(host: str, port: int, timeout_seconds: float) -> None:
    """Require the local six-point compatibility endpoint before accepting hands."""
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    detail = type(last_error).__name__ if last_error is not None else "timeout"
    raise OSError(f"vision_point_endpoint_unavailable:{host}:{port}:{detail}")


class HighFiveFrameProcessor:
    """Run reviewed hand-grid actions on frames supplied by the unified vision loop."""

    def __init__(
        self,
        detector: HandDetector,
        gate: HandRecognitionGate,
        *,
        vision_point_host: str,
        vision_point_port: int,
        stable_frames: int,
        sample_seconds: float,
    ) -> None:
        self.detector = detector
        self.gate = gate
        self.vision_point_host = vision_point_host
        self.vision_point_port = int(vision_point_port)
        self.stabilizer = StableGridAction(required_frames=max(1, stable_frames))
        self.sampler = HandPositionSampler(interval_seconds=max(0.05, sample_seconds))
        self.follow_window = FollowInputWindow()
        self.generation = -1
        self.last_position: tuple[int, int] | None = None
        self.last_detection: HandDetection | None = None

    def process(self, frame) -> bool:
        """Process an enabled hand-interaction frame and report exclusive mode."""
        enabled, current_generation = self.gate.snapshot()
        if current_generation != self.generation:
            self.stabilizer.reset()
            self.sampler.reset()
            self.follow_window.reset()
            self.generation = current_generation
            self.last_position = None
            self.last_detection = None
        if not enabled:
            return False
        now = time.monotonic()
        position: tuple[int, int] | None = None
        sampled = False
        if self.sampler.is_due(now):
            sampled = True
            self.last_detection = self.detector.detect(frame)
            position = (
                grid_position(*self.last_detection.center, frame.shape[1], frame.shape[0])
                if self.last_detection is not None
                else None
            )
            self.last_position = position
        if sampled:
            print(json.dumps({"event": "vision_high_five_sample", "position": list(position) if position else None}, ensure_ascii=False), flush=True)
            action = self.stabilizer.observe(position)
            if action:
                try:
                    point_command = GRID_COMMANDS[position]
                    receipt = send_vision_point_command(point_command, host=self.vision_point_host, port=self.vision_point_port)
                    accepted, status = follow_dispatch_accepted(receipt)
                    if accepted:
                        phase = "follow_start" if not self.follow_window.active else "follow_redirect"
                        self.follow_window.observe_action(now)
                        self.gate.record_follow_action(phase, now=now)
                        print(json.dumps({"event": "vision_high_five_action", "phase": phase, "position": position, "action": action, "point_command": point_command, "queue_status": status}, ensure_ascii=False), flush=True)
                    else:
                        print(json.dumps({"event": "vision_high_five_action_rejected", "position": position, "action": action, "point_command": point_command, "reason": status}, ensure_ascii=False), flush=True)
                except OSError as exc:
                    print(f"vision_high_five_dispatch_failed:{type(exc).__name__}:{exc}", file=sys.stderr, flush=True)
        if self.follow_window.should_close(now):
            self.gate.set_enabled(False)
            self.stabilizer.reset()
            self.follow_window.reset()
            print(json.dumps({"event": "vision_high_five_follow_window_closed"}, ensure_ascii=False), flush=True)
        elif float(self.gate.status(now=now)["enabled_seconds"]) >= FOLLOW_MAX_SESSION_SECONDS:
            self.gate.set_enabled(False)
            self.stabilizer.reset()
            self.follow_window.reset()
            print(json.dumps({"event": "vision_high_five_session_timed_out"}, ensure_ascii=False), flush=True)
        return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        import cv2
    except ImportError as exc:
        print(f"vision_dependency_missing:{exc}", file=sys.stderr)
        return 5
    gate = HandRecognitionGate()
    control = HandControlServer(gate, args.hand_control_listen_host, args.hand_control_listen_port)
    capture = cv2.VideoCapture(int(args.source) if str(args.source).isdigit() else args.source)
    if not capture.isOpened():
        print(f"camera_open_failed:{args.source}", file=sys.stderr)
        capture.release()
        return 2
    # The recognition loop drains an MJPEG stream continuously and only runs
    # MediaPipe on the latest scheduled sample.  Asking OpenCV for a one-frame
    # buffer avoids using an older hand position when the camera is busy.
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    detector: HandDetector | None = None
    try:
        detector = HandDetector(Path(args.hand_model), args.max_hands, args.threshold)
        wait_for_vision_point_endpoint(
            args.vision_point_host,
            args.vision_point_port,
            args.vision_point_ready_timeout,
        )
        control.start()
        print(
            json.dumps(
                {
                    "event": "vision_high_five_endpoints_ready",
                    "vision_point_endpoint": f"{args.vision_point_host}:{args.vision_point_port}",
                    "control_endpoint": f"{args.hand_control_listen_host}:{args.hand_control_listen_port}",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        stabilizer = StableGridAction(required_frames=max(1, args.hand_stable_frames))
        sampler = HandPositionSampler(interval_seconds=max(0.05, float(args.hand_sample_seconds)))
        follow_window = FollowInputWindow()
        generation = -1
        frame_count = 0
        while not args.max_frames or frame_count < args.max_frames:
            ok, frame = capture.read()
            if not ok:
                time.sleep(0.15)
                continue
            enabled, current_generation = gate.snapshot()
            if current_generation != generation:
                stabilizer.reset()
                sampler.reset()
                follow_window.reset()
                generation = current_generation
            if enabled:
                now = time.monotonic()
                if sampler.is_due(now):
                    center = detector.detect_center(frame)
                    position = grid_position(*center, frame.shape[1], frame.shape[0]) if center else None
                    print(
                        json.dumps(
                            {
                                "event": "vision_high_five_sample",
                                "position": list(position) if position else None,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    action = stabilizer.observe(position)
                    if action:
                        try:
                            point_command = GRID_COMMANDS[position]
                            receipt = send_vision_point_command(
                                point_command,
                                host=args.vision_point_host,
                                port=args.vision_point_port,
                            )
                            accepted, status = follow_dispatch_accepted(receipt)
                            if accepted:
                                phase = "follow_start" if not follow_window.active else "follow_redirect"
                                follow_window.observe_action(now)
                                gate.record_follow_action(phase, now=now)
                                print(
                                    json.dumps(
                                        {
                                            "event": "vision_high_five_action",
                                            "phase": phase,
                                            "position": position,
                                            "action": action,
                                            "point_command": point_command,
                                            "queue_status": status,
                                        },
                                        ensure_ascii=False,
                                    ),
                                    flush=True,
                                )
                            else:
                                print(
                                    json.dumps(
                                        {
                                            "event": "vision_high_five_action_rejected",
                                            "position": position,
                                            "action": action,
                                            "point_command": point_command,
                                            "reason": status,
                                        },
                                        ensure_ascii=False,
                                    ),
                                    flush=True,
                                )
                        except OSError as exc:
                            print(f"vision_high_five_dispatch_failed:{type(exc).__name__}:{exc}", file=sys.stderr, flush=True)
                if follow_window.should_close(now):
                    gate.set_enabled(False)
                    stabilizer.reset()
                    follow_window.reset()
                    print(
                        json.dumps(
                            {"event": "vision_high_five_follow_window_closed"},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                elif float(gate.status(now=now)["enabled_seconds"]) >= FOLLOW_MAX_SESSION_SECONDS:
                    gate.set_enabled(False)
                    stabilizer.reset()
                    follow_window.reset()
                    print(
                        json.dumps(
                            {"event": "vision_high_five_session_timed_out"},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            frame_count += 1
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"high_five_vision_failed:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 3
    finally:
        capture.release()
        if detector is not None:
            detector.close()
        control.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
