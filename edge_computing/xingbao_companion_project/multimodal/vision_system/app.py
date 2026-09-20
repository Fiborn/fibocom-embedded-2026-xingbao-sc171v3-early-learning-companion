"""星宝视觉运行时：距离、久坐、饮水、物体与面部情绪识别。

该模块由 2026-07-24 视觉发布包迁入。输出继续保留旧版
``return_code`` 和 ``drink_return_code``，并新增独立的
``emotion_return_code``，从而避免破坏现有调用方。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import queue
import socket
import socketserver
import threading
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from multimodal.high_five_vision_runtime import (
    HandControlServer,
    HandDetection,
    HandDetector,
    HandRecognitionGate,
    HighFiveFrameProcessor,
    wait_for_vision_point_endpoint,
)
from multimodal.vision_adapter import VisionEventAdapter
from .scene_description import (
    DEFAULT_MOONSHOT_API_KEY,
    KimiSceneClient,
    SceneDescriptionController,
    SceneDescriptionStatus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def active_companion_enabled(settings_path: Path) -> bool:
    """Read the desktop's privacy control; invalid or absent settings mean off."""
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    return bool(payload.get("active_companion", False)) if isinstance(payload, dict) else False


def non_hand_inference_paused(hand_interaction_active: bool) -> bool:
    """Keep a handshake/high-five session exclusive to hand inference."""
    return bool(hand_interaction_active)


class UiVisionStatusWriter:
    """Publish the two small UI safety flags without exposing camera data."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_flags: tuple[int, int] | None = None

    def write(self, distance_too_close: bool, needs_water: bool) -> None:
        flags = (int(bool(distance_too_close)), int(bool(needs_water)))
        if flags == self.last_flags:
            return
        payload = {
            "distance_too_close": flags[0],
            "needs_water": flags[1],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
            self.last_flags = flags
            print(
                "ui_vision_status_written:path={} distance_too_close={} needs_water={}".format(
                    self.path, flags[0], flags[1]
                ),
                file=sys.stderr,
                flush=True,
            )
        except OSError as exc:
            print(f"ui_vision_status_write_failed:{exc}", file=sys.stderr, flush=True)


class UiVisionStatusNotifier:
    """Push compact safety state to the UI bridge on transitions only."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        self.last_flags: tuple[int, int] | None = None

    def publish(self, distance_too_close: bool, needs_water: bool) -> None:
        flags = (int(bool(distance_too_close)), int(bool(needs_water)))
        if flags == self.last_flags:
            return
        message = {
            "type": "vision_status",
            "source": "vision_runtime",
            "payload": {
                "vision_status": {
                    "distance_too_close": flags[0],
                    "needs_water": flags[1],
                },
            },
        }
        print(
            "ui_vision_status_ipc_attempt:host={} port={} payload={}".format(
                self.host,
                self.port,
                json.dumps(message["payload"]["vision_status"], ensure_ascii=False),
            ),
            file=sys.stderr,
            flush=True,
        )
        try:
            encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            with socket.create_connection((self.host, self.port), timeout=0.5) as client:
                client.settimeout(0.5)
                client.sendall(encoded)
                client.recv(4096)
            self.last_flags = flags
            print(
                "ui_vision_status_ipc_sent:host={} port={} distance_too_close={} needs_water={}".format(
                    self.host, self.port, flags[0], flags[1]
                ),
                file=sys.stderr,
                flush=True,
            )
        except OSError as exc:
            print(
                "ui_vision_status_ipc_failed:host={} port={} error={}".format(
                    self.host, self.port, exc
                ),
                file=sys.stderr,
                flush=True,
            )


class EmotionInferenceBroker:
    """Marshal one explicit emotion request onto the camera-owning thread."""

    def __init__(self) -> None:
        self._requests: "queue.Queue[queue.Queue[dict[str, Any]]]" = queue.Queue()

    def request(self, timeout_seconds: float = 8.0) -> dict[str, Any]:
        reply: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=1)
        self._requests.put(reply)
        try:
            return reply.get(timeout=max(0.2, float(timeout_seconds)))
        except queue.Empty:
            return {"ok": False, "error": "emotion_inference_timeout"}

    def take_pending(self) -> list["queue.Queue[dict[str, Any]]"]:
        pending: list["queue.Queue[dict[str, Any]]"] = []
        while True:
            try:
                pending.append(self._requests.get_nowait())
            except queue.Empty:
                return pending

    @staticmethod
    def respond(
        pending: list["queue.Queue[dict[str, Any]]"], result: dict[str, Any]
    ) -> None:
        for reply in pending:
            try:
                reply.put_nowait(result)
            except queue.Full:
                pass


class _EmotionInferenceHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(4096)
            request = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            request = {}
        if not isinstance(request, dict) or request.get("action") != "infer_emotion_once":
            result = {"ok": False, "error": "invalid_emotion_request"}
        else:
            result = self.server.broker.request()  # type: ignore[attr-defined]
        self.wfile.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))


class EmotionInferenceServer:
    """Local-only synchronous endpoint for an LLM-requested FER inference."""

    def __init__(self, broker: EmotionInferenceBroker, host: str, port: int) -> None:
        self.broker = broker
        self.host = str(host)
        self.port = int(port)
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("emotion_control_host_must_be_loopback")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server((self.host, self.port), _EmotionInferenceHandler)
        self._server.broker = self.broker  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - depends on deployment extras
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    VISION_DEPENDENCY_ERROR: ImportError | None = exc
else:
    VISION_DEPENDENCY_ERROR = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "vision" / "yolo11n.pt"
DEFAULT_EMOTION_MODEL_PATH = (
    PROJECT_ROOT / "models" / "vision" / "enet_b0_8_best_afew.onnx"
)
DEFAULT_HAND_MODEL_PATH = PROJECT_ROOT / "models" / "vision" / "hand_landmarker.task"
DEFAULT_FIBO_OBJECT_MODEL_PATH = (
    PROJECT_ROOT / "models" / "vision" / "yolov8n_det_1.0.1_qcom_all_snpe_2.25_dsp.fmodel"
)
DEFAULT_FIBO_FACE_MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "vision"
    / "yolov5-face_1.0.0_qcom_all_snpe_2.25_dsp_bea5118250d803f865b358dcac6cad1c.fmodel"
)
DEFAULT_FIBO_LICENSE_DIR = Path(
    os.environ.get("XINGBAO_FIBO_LICENSE_DIR", "/home/fibo/qcom_6490_license")
)
DRINK_CONTAINER_NAMES = frozenset({"bottle", "cup"})


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height


def six_point_grid_rectangles(*, frame_width: int, frame_height: int) -> dict[tuple[int, int], Box]:
    """Return the reviewed 2×3 high-five calibration grid for a frame."""
    if frame_width <= 0 or frame_height <= 0:
        return {}
    x_edges = [round(frame_width * column / 3) for column in range(4)]
    y_edges = [0, round(frame_height / 2), frame_height]
    return {
        (row, column): Box(
            x_edges[column - 1],
            y_edges[row - 1],
            x_edges[column],
            y_edges[row],
        )
        for row in (1, 2)
        for column in (1, 2, 3)
    }


def mirror_box_for_display(box: Box, *, frame_width: int) -> Box:
    """Map raw camera bounds to the horizontally mirrored display frame."""
    return Box(frame_width - 1 - box.x2, box.y1, frame_width - 1 - box.x1, box.y2)


@dataclass
class FaceResult:
    box: Box
    distance_m: float | None
    distance_band: str


@dataclass
class ObjectResult:
    box: Box
    class_id: int
    name: str
    confidence: float
    is_priority: bool


def fibo_objects_to_results(
    raw_objects: object, *, priority_names: set[str], cup_only: bool, confidence_threshold: float = 0.0
) -> list[ObjectResult]:
    """Flatten CVAPI's nested detection groups into Xingbao object results."""
    results: list[ObjectResult] = []

    def visit(item: object) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        box = getattr(item, "bbox", None)
        if box is None:
            return
        name = str(getattr(item, "label", ""))
        confidence = float(getattr(item, "score", 0.0))
        if confidence < confidence_threshold:
            return
        if cup_only and name not in priority_names:
            return
        x1, y1 = int(box.x), int(box.y)
        results.append(
            ObjectResult(
                box=Box(x1, y1, x1 + int(box.w), y1 + int(box.h)),
                class_id=int(item.class_id),
                name=name,
                confidence=confidence,
                is_priority=name in priority_names,
            )
        )

    visit(raw_objects)
    return results


def fibo_faces_from_objects(
    raw_objects: object,
    *,
    frame_width: int,
    frame_height: int,
    min_face_px: int,
    confidence_threshold: float,
    distance_estimator: FaceDistanceEstimator,
) -> list[FaceResult]:
    """Convert Fibo YOLO-face output into Xingbao's single primary face."""
    candidates: list[tuple[float, Box]] = []

    def visit(item: object) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        raw_box = getattr(item, "bbox", None)
        confidence = float(getattr(item, "score", 0.0))
        if raw_box is None or confidence < confidence_threshold:
            return
        x1 = max(0, min(frame_width - 1, int(raw_box.x)))
        y1 = max(0, min(frame_height - 1, int(raw_box.y)))
        x2 = max(x1, min(frame_width, x1 + int(raw_box.w)))
        y2 = max(y1, min(frame_height, y1 + int(raw_box.h)))
        box = Box(x1, y1, x2, y2)
        if box.width >= min_face_px and box.height >= min_face_px:
            candidates.append((confidence, box))

    visit(raw_objects)
    if not candidates:
        return []
    _, box = max(candidates, key=lambda candidate: (candidate[0], candidate[1].area))
    distance_m = distance_estimator.estimate(frame_width, box.width)
    return [
        FaceResult(
            box=box,
            distance_m=distance_m,
            distance_band=FaceDistanceEstimator.band(distance_m),
        )
    ]


@dataclass
class EmotionResult:
    face_index: int
    box: Box
    label: str
    display_name: str
    confidence: float
    return_code: int
    confirmed: bool


def prepare_hsemotion_b0_input(bgr_face: np.ndarray) -> np.ndarray:
    """Convert an OpenCV BGR face crop to HSEmotion EmotiEffNet-B0 input."""
    rgb = cv2.cvtColor(bgr_face, cv2.COLOR_BGR2RGB)
    image = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    mean = np.asarray((0.485, 0.456, 0.406), dtype=np.float32)
    std = np.asarray((0.229, 0.224, 0.225), dtype=np.float32)
    normalized = (image - mean) / std
    return normalized.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)


@dataclass
class DrinkReminderStatus:
    enabled: bool
    overlap_now: bool
    alert: bool
    seconds_since_overlap: float
    seconds_until_alert: float
    bottle_count: int
    face_count: int


@dataclass
class ReturnCodeStatus:
    code: int
    smoothed_distance_m: float | None
    close_seconds: float
    face_presence_ratio: float
    face_window_seconds: float
    face_seen_seconds: float


class DrinkReminder:
    def __init__(self, interval_seconds: float, overlap_threshold: float) -> None:
        self.interval_seconds = max(1.0, interval_seconds)
        self.overlap_threshold = max(0.0, overlap_threshold)
        self.last_overlap_time = time.monotonic()

    def update(self, faces: list[FaceResult], objects: list[ObjectResult]) -> DrinkReminderStatus:
        now = time.monotonic()
        containers = [obj for obj in objects if obj.name in DRINK_CONTAINER_NAMES]
        overlap_now = any(
            normalized_intersection(face.box, container.box) >= self.overlap_threshold
            for face in faces
            for container in containers
        )
        if overlap_now:
            self.last_overlap_time = now

        seconds_since_overlap = now - self.last_overlap_time
        return DrinkReminderStatus(
            enabled=True,
            overlap_now=overlap_now,
            alert=seconds_since_overlap >= self.interval_seconds,
            seconds_since_overlap=seconds_since_overlap,
            seconds_until_alert=max(0.0, self.interval_seconds - seconds_since_overlap),
            bottle_count=len(containers),
            face_count=len(faces),
        )


class HydrationInferenceScheduler:
    """Run denser bottle/face checks only while confirming a drink."""

    def __init__(
        self,
        *,
        normal_object_interval_seconds: float,
        normal_face_interval_seconds: float,
        confirm_interval_seconds: float,
        bottle_cooldown_seconds: float,
    ) -> None:
        self.normal_object_interval_seconds = max(0.0, normal_object_interval_seconds)
        self.normal_face_interval_seconds = max(0.0, normal_face_interval_seconds)
        self.confirm_interval_seconds = max(0.05, confirm_interval_seconds)
        self.bottle_cooldown_seconds = max(0.0, bottle_cooldown_seconds)
        self._last_object_inference = float("-inf")
        self._last_face_inference = float("-inf")
        self._cooldown_until = float("-inf")
        self._confirming = False
        self._force_face = False
        self._force_object = False

    @property
    def confirming(self) -> bool:
        return self._confirming

    def _advance(self, now: float) -> None:
        if not self._confirming and now >= self._cooldown_until and self._cooldown_until != float("-inf"):
            self._cooldown_until = float("-inf")
            self._force_object = True

    def object_inference_due(self, now: float) -> bool:
        self._advance(now)
        if now < self._cooldown_until:
            return False
        if self._force_object:
            return True
        interval = (
            self.confirm_interval_seconds
            if self._confirming
            else self.normal_object_interval_seconds
        )
        return interval == 0.0 or now - self._last_object_inference >= interval

    def face_inference_due(self, now: float) -> bool:
        self._advance(now)
        if self._force_face:
            return True
        interval = (
            self.confirm_interval_seconds
            if self._confirming
            else self.normal_face_interval_seconds
        )
        return interval == 0.0 or now - self._last_face_inference >= interval

    def record_object_inference(self, now: float, *, bottle_detected: bool) -> None:
        self._last_object_inference = now
        self._force_object = False
        if bottle_detected and not self._confirming:
            self._confirming = True
            self._force_face = True

    def record_face_inference(self, now: float) -> None:
        self._last_face_inference = now
        self._force_face = False

    def record_drink_reset(self, now: float) -> bool:
        if not self._confirming:
            return False
        self._confirming = False
        self._force_face = False
        self._cooldown_until = now + self.bottle_cooldown_seconds
        return True


class FaceReturnCodeMonitor:
    def __init__(
        self,
        distance_threshold_m: float,
        close_duration_seconds: float,
        face_window_seconds: float,
        face_ratio_threshold: float,
        smoothing: float,
    ) -> None:
        self.distance_threshold_m = distance_threshold_m
        self.close_duration_seconds = close_duration_seconds
        self.face_window_seconds = face_window_seconds
        self.face_ratio_threshold = face_ratio_threshold
        self.smoothing = min(1.0, max(0.0, smoothing))
        self.smoothed_distance_m: float | None = None
        self.close_start_time: float | None = None
        self.last_update_time: float | None = None
        self.face_intervals: list[tuple[float, float, bool]] = []

    def update(self, faces: list[FaceResult]) -> ReturnCodeStatus:
        now = time.monotonic()
        face_present = len(faces) > 0
        if self.last_update_time is not None:
            dt = max(0.0, min(now - self.last_update_time, 5.0))
            if dt > 0.0:
                self._add_face_interval(now, dt, face_present)
        self.last_update_time = now

        nearest_distance_m = faces[0].distance_m if faces else None
        if nearest_distance_m is not None:
            if self.smoothed_distance_m is None:
                self.smoothed_distance_m = nearest_distance_m
            else:
                alpha = self.smoothing
                self.smoothed_distance_m = alpha * nearest_distance_m + (1.0 - alpha) * self.smoothed_distance_m

        if nearest_distance_m is not None and self.smoothed_distance_m is not None and self.smoothed_distance_m < self.distance_threshold_m:
            if self.close_start_time is None:
                self.close_start_time = now
            close_seconds = now - self.close_start_time
        else:
            self.close_start_time = None
            close_seconds = 0.0

        face_window_seconds, face_seen_seconds = self._face_window_stats()
        face_ratio = 0.0 if face_window_seconds <= 0.0 else face_seen_seconds / face_window_seconds

        code = 0
        if close_seconds >= self.close_duration_seconds:
            code = 1
        elif face_window_seconds >= self.face_window_seconds and face_ratio > self.face_ratio_threshold:
            code = 2

        return ReturnCodeStatus(
            code=code,
            smoothed_distance_m=self.smoothed_distance_m,
            close_seconds=close_seconds,
            face_presence_ratio=face_ratio,
            face_window_seconds=face_window_seconds,
            face_seen_seconds=face_seen_seconds,
        )

    def _add_face_interval(self, end_time: float, duration: float, present: bool) -> None:
        self.face_intervals.append((end_time, duration, present))
        cutoff = end_time - self.face_window_seconds
        while self.face_intervals:
            first_end, first_duration, first_present = self.face_intervals[0]
            first_start = first_end - first_duration
            if first_end <= cutoff:
                self.face_intervals.pop(0)
                continue
            if first_start < cutoff:
                self.face_intervals[0] = (first_end, first_end - cutoff, first_present)
            break

    def _face_window_stats(self) -> tuple[float, float]:
        total = sum(duration for _, duration, _ in self.face_intervals)
        seen = sum(duration for _, duration, present in self.face_intervals if present)
        return total, seen


class FaceDistanceEstimator:
    def __init__(
        self,
        known_face_width_m: float,
        horizontal_fov_deg: float,
        focal_px: float | None,
        smoothing: float,
    ) -> None:
        self.known_face_width_m = known_face_width_m
        self.horizontal_fov_deg = horizontal_fov_deg
        self.focal_px = focal_px
        self.smoothing = smoothing
        self._smoothed_m: float | None = None

    def estimate(self, frame_width_px: int, face_width_px: int) -> float | None:
        if face_width_px <= 0:
            return None

        focal_px = self.focal_px
        if focal_px is None:
            fov_rad = math.radians(self.horizontal_fov_deg)
            focal_px = frame_width_px / (2.0 * math.tan(fov_rad / 2.0))

        raw_m = (self.known_face_width_m * focal_px) / float(face_width_px)
        if self._smoothed_m is None:
            self._smoothed_m = raw_m
        else:
            alpha = min(1.0, max(0.0, self.smoothing))
            self._smoothed_m = alpha * raw_m + (1.0 - alpha) * self._smoothed_m
        return self._smoothed_m

    @staticmethod
    def band(distance_m: float | None) -> str:
        if distance_m is None:
            return "unknown"
        if distance_m < 0.2:
            return "very_close"
        if distance_m < 0.5:
            return "close"
        if distance_m < 1.0:
            return "middle"
        return "far"


class YoloObjectDetector:
    def __init__(
        self,
        model_path: str,
        imgsz: int,
        conf: float,
        iou: float,
        device: str,
        priority_names: set[str],
        cup_only: bool,
    ) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "Ultralytics is not installed. Run: python -m pip install ultralytics"
            ) from exc

        self.model = YOLO(model_path)
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = device
        self.priority_names = priority_names
        self.cup_only = cup_only

    def detect(self, frame: np.ndarray) -> list[ObjectResult]:
        results = self.model.predict(
            source=frame,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            verbose=False,
        )
        if not results:
            return []

        names = results[0].names
        objects: list[ObjectResult] = []
        boxes = results[0].boxes
        if boxes is None:
            return objects

        for item in boxes:
            class_id = int(item.cls.item())
            name = str(names.get(class_id, class_id))
            if self.cup_only and name not in self.priority_names:
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in item.xyxy[0].tolist()]
            confidence = float(item.conf.item())
            objects.append(
                ObjectResult(
                    box=Box(x1, y1, x2, y2),
                    class_id=class_id,
                    name=name,
                    confidence=confidence,
                    is_priority=name in self.priority_names,
                )
            )
        return objects


class FiboYoloObjectDetector:
    """QCS6490 licensed DSP/HTP YOLOv8 detector; no Ultralytics fallback."""

    def __init__(
        self,
        model_path: Path,
        priority_names: set[str],
        cup_only: bool,
        confidence_threshold: float,
        license_dir: Path = DEFAULT_FIBO_LICENSE_DIR,
    ) -> None:
        from fiboaisdk.api_aisdk_py import api_cv_py, license_py

        if not model_path.is_file():
            raise RuntimeError(f"fibo_object_model_missing:{model_path}")
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
        status = self._api.Init(str(model_path))
        if status != 0:
            self._api.Release()
            raise RuntimeError(f"fibo_object_model_init_failed:{status}")
        self.priority_names = priority_names
        self.cup_only = cup_only
        self.confidence_threshold = confidence_threshold

    def detect(self, frame: np.ndarray) -> list[ObjectResult]:
        height, width = frame.shape[:2]
        image = self._cv.FIBO_CV_Img()
        image.width, image.height = width, height
        image.channels, image.size = frame.shape[2], frame.size
        image.format, image.layout = 0, 0  # CVAPI expects OpenCV BGR HWC input.
        image.data = frame.reshape(-1).tolist()
        result = self._cv.ResultCvDetect()
        status = self._api.InferCvDetectSync(image, result)
        if status != 0:
            raise RuntimeError(f"fibo_object_infer_failed:{status}")
        return fibo_objects_to_results(
            result.objects,
            priority_names=self.priority_names,
            cup_only=self.cup_only,
            confidence_threshold=self.confidence_threshold,
        )

    def close(self) -> None:
        self._api.Release()


class MediaPipeFaceDetector:
    """Original local MediaPipe face detector used by Xingbao."""

    def __init__(self, min_face_px: int, confidence: float, model_selection: int) -> None:
        try:
            import mediapipe as mp
        except Exception as exc:
            raise RuntimeError("MediaPipe is required for face detection") from exc
        self.min_face_px = min_face_px
        self.detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1 if model_selection == 1 else 0,
            min_detection_confidence=min(1.0, max(0.0, confidence)),
        )

    def detect(self, frame: np.ndarray, distance_estimator: FaceDistanceEstimator) -> list[FaceResult]:
        frame_height, frame_width = frame.shape[:2]
        result = self.detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        faces: list[FaceResult] = []
        for detection in result.detections or []:
            relative_box = detection.location_data.relative_bounding_box
            x1 = max(0, min(frame_width - 1, int(round(relative_box.xmin * frame_width))))
            y1 = max(0, min(frame_height - 1, int(round(relative_box.ymin * frame_height))))
            x2 = max(0, min(frame_width, int(round((relative_box.xmin + relative_box.width) * frame_width))))
            y2 = max(0, min(frame_height, int(round((relative_box.ymin + relative_box.height) * frame_height))))
            box = Box(x1, y1, x2, y2)
            if box.width < self.min_face_px or box.height < self.min_face_px:
                continue
            distance_m = distance_estimator.estimate(frame_width, box.width)
            faces.append(
                FaceResult(
                    box=box,
                    distance_m=distance_m,
                    distance_band=FaceDistanceEstimator.band(distance_m),
                )
            )
        return sorted(faces, key=lambda face: face.box.area, reverse=True)

    def close(self) -> None:
        self.detector.close()


class FiboFaceDetector:
    """Licensed DSP YOLOv5-face detector; the CPU MediaPipe detector is disabled."""

    def __init__(
        self,
        model_path: Path,
        min_face_px: int,
        confidence_threshold: float,
        license_dir: Path = DEFAULT_FIBO_LICENSE_DIR,
    ) -> None:
        from fiboaisdk.api_aisdk_py import api_cv_py, license_py

        if not model_path.is_file():
            raise RuntimeError(f"fibo_face_model_missing:{model_path}")
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
        status = self._api.Init(str(model_path))
        if status != 0:
            self._api.Release()
            raise RuntimeError(f"fibo_face_model_init_failed:{status}")
        self.min_face_px = min_face_px
        self.confidence_threshold = confidence_threshold

    def detect(self, frame: np.ndarray, distance_estimator: FaceDistanceEstimator) -> list[FaceResult]:
        height, width = frame.shape[:2]
        image = self._cv.FIBO_CV_Img()
        image.width, image.height = width, height
        image.channels, image.size = frame.shape[2], frame.size
        image.format, image.layout = 0, 0
        image.data = frame.reshape(-1).tolist()
        result = self._cv.ResultCvDetect()
        status = self._api.InferCvDetectSync(image, result)
        if status != 0:
            raise RuntimeError(f"fibo_face_infer_failed:{status}")
        return fibo_faces_from_objects(
            result.objects,
            frame_width=width,
            frame_height=height,
            min_face_px=self.min_face_px,
            confidence_threshold=self.confidence_threshold,
            distance_estimator=distance_estimator,
        )

    def close(self) -> None:
        self._api.Release()


class EmotionDetector:
    """HSEmotion EmotiEffNet-B0 ONNX emotion classifier."""
    label_to_return_code = {
        "happiness": 1,
        "sadness": 2,
        "anger": 3,
        "surprise": 4,
        "fear": 5,
        "disgust": 6,
        "contempt": 7,
        "neutral": 8,
    }
    label_to_display_name = {
        "happiness": "happy",
        "sadness": "sad",
        "anger": "angry",
        "surprise": "surprise",
        "fear": "fear",
        "disgust": "disgust",
        "contempt": "contempt",
        "neutral": "neutral",
    }
    hsemotion_labels = [
        "anger",
        "contempt",
        "disgust",
        "fear",
        "happiness",
        "neutral",
        "sadness",
        "surprise",
    ]

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float,
        sadness_threshold: float | None = None,
        anger_threshold: float | None = None,
        happiness_threshold: float | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise RuntimeError(f"Emotion model not found: {self.model_path}")
        try:
            import onnxruntime as ort
        except Exception as exc:
            raise RuntimeError("onnxruntime is required for HSEmotion") from exc
        self.session = ort.InferenceSession(
            str(self.model_path), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.confidence_threshold = min(1.0, max(0.0, confidence_threshold))
        self.sadness_threshold = (
            self.confidence_threshold
            if sadness_threshold is None
            else min(1.0, max(0.0, sadness_threshold))
        )
        self.anger_threshold = (
            self.confidence_threshold
            if anger_threshold is None
            else min(1.0, max(0.0, anger_threshold))
        )
        self.happiness_threshold = (
            self.confidence_threshold
            if happiness_threshold is None
            else min(1.0, max(0.0, happiness_threshold))
        )

    def detect(self, frame: np.ndarray, faces: list[FaceResult]) -> list[EmotionResult]:
        emotions: list[EmotionResult] = []
        for index, face in enumerate(faces):
            crop = crop_box(frame, face.box, padding_ratio=0.18)
            if crop.size == 0:
                continue

            blob = prepare_hsemotion_b0_input(crop)
            scores = self.session.run(None, {self.input_name: blob})[0]
            probabilities = softmax(np.asarray(scores, dtype=np.float32).reshape(-1))

            class_index = int(np.argmax(probabilities))
            confidence = float(probabilities[class_index])
            label = self.hsemotion_labels[class_index]
            threshold = {
                "sadness": self.sadness_threshold,
                "anger": self.anger_threshold,
                "happiness": self.happiness_threshold,
            }.get(label, self.confidence_threshold)
            confirmed = confidence >= threshold
            return_code = self.label_to_return_code[label] if confirmed else 0
            emotions.append(
                EmotionResult(
                    face_index=index,
                    box=face.box,
                    label=label,
                    display_name=self.label_to_display_name[label],
                    confidence=confidence,
                    return_code=return_code,
                    confirmed=confirmed,
                )
            )
        return emotions


def parse_source(value: str) -> int | str:
    if value.isdigit():
        return int(value)
    return value


def face_inference_due(*, now: float, last_inference_time: float, interval_seconds: float) -> bool:
    """Run face detection on its configured schedule."""
    interval = max(0.0, float(interval_seconds))
    return interval == 0.0 or now - last_inference_time >= interval


def emotion_inference_due(*, now: float, last_inference_time: float, interval_seconds: float) -> bool:
    """Run emotion recognition independently of face-detection cadence."""
    interval = max(0.0, float(interval_seconds))
    return interval == 0.0 or now - last_inference_time >= interval


def emotion_countdown_seconds(
    *, now: float, last_inference_time: float, interval_seconds: float
) -> int | None:
    """Return whole seconds until the next emotion inference, or None before the first one."""
    if math.isinf(last_inference_time) and last_inference_time < 0:
        return None
    interval = max(0.0, float(interval_seconds))
    return max(0, int(math.ceil(interval - (now - last_inference_time))))


def camera_source_candidates(
    source: int | str,
    available_indices: list[int] | None = None,
) -> list[int | str]:
    """Return capture candidates while keeping explicit video files exact.

    USB V4L2 indices can change after a transient disconnect. Numeric sources,
    ``/dev/videoN`` paths, and ``auto`` therefore fall back to the currently
    enumerated Linux capture nodes. Regular video-file paths never fall back.
    """
    raw = str(source).strip()
    is_auto = raw.lower() == "auto"
    is_numeric = isinstance(source, int) or raw.isdigit()
    is_video_node = raw.startswith("/dev/video") and raw[10:].isdigit()
    if not (is_auto or is_numeric or is_video_node):
        return [source]

    candidates: list[int | str] = []
    linux_video_nodes = platform.system() == "Linux"
    if not is_auto:
        if is_numeric and linux_video_nodes:
            candidates.append(f"/dev/video{int(raw)}")
        else:
            candidates.append(int(raw) if is_numeric else source)

    if available_indices is None:
        available_indices = []
        if platform.system() == "Linux":
            for path in Path("/dev").glob("video*"):
                suffix = path.name[5:]
                if suffix.isdigit():
                    available_indices.append(int(suffix))
    for index in sorted(set(available_indices)):
        candidate: int | str = f"/dev/video{index}" if linux_video_nodes else index
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates or [0]


def is_recoverable_camera_source(source: int | str) -> bool:
    """Return whether a source may be re-enumerated by Linux at runtime."""
    raw = str(source).strip()
    return bool(
        raw.lower() == "auto"
        or isinstance(source, int)
        or raw.isdigit()
        or (raw.startswith("/dev/video") and raw[10:].isdigit())
    )


def crop_box(frame: np.ndarray, box: Box, padding_ratio: float) -> np.ndarray:
    height, width = frame.shape[:2]
    pad_x = int(box.width * padding_ratio)
    pad_y = int(box.height * padding_ratio)
    x1 = max(0, box.x1 - pad_x)
    y1 = max(0, box.y1 - pad_y)
    x2 = min(width, box.x2 + pad_x)
    y2 = min(height, box.y2 + pad_y)
    if x2 <= x1 or y2 <= y1:
        return np.empty((0, 0, 3), dtype=frame.dtype)
    return frame[y1:y2, x1:x2]


def softmax(scores: np.ndarray) -> np.ndarray:
    shifted = scores - float(np.max(scores))
    exp = np.exp(shifted)
    total = float(np.sum(exp))
    if total <= 0.0:
        return np.zeros_like(scores, dtype=np.float32)
    return exp / total


def normalized_intersection(a: Box, b: Box) -> float:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    inter_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    smaller_area = min(a.area, b.area)
    if smaller_area <= 0:
        return 0.0
    return inter_area / float(smaller_area)


def draw_label(frame: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.48
    thickness = 1
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
    y = max(text_h + baseline + 4, y)
    x = max(0, min(x, frame.shape[1] - text_w - 6))
    top_left = (x, y - text_h - baseline - 4)
    bottom_right = (x + text_w + 6, y + 2)
    cv2.rectangle(frame, top_left, bottom_right, color, -1)
    cv2.putText(frame, text, (x + 3, y - baseline - 1), font, scale, (255, 255, 255), thickness)


def draw_faces(
    frame: np.ndarray,
    faces: list[FaceResult],
    emotions: list[EmotionResult],
    *,
    mirror_display: bool = False,
) -> None:
    emotion_by_face = {emotion.face_index: emotion for emotion in emotions}
    for face_index, face in enumerate(faces):
        box = (
            mirror_box_for_display(face.box, frame_width=int(frame.shape[1]))
            if mirror_display
            else face.box
        )
        color = (255, 160, 0)
        cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, 2)
        if face.distance_m is None:
            text = f"face {face.distance_band}"
        else:
            text = f"face {face.distance_m:.2f}m {face.distance_band}"
        emotion = emotion_by_face.get(face_index)
        if emotion is not None:
            if emotion.confirmed:
                text += f" | {emotion.display_name} {emotion.confidence:.2f} e={emotion.return_code}"
            else:
                text += f" | emotion? {emotion.confidence:.2f} e=0"
        draw_label(frame, text, box.x1, box.y1 - 4, color)


def draw_objects(
    frame: np.ndarray, objects: list[ObjectResult], *, mirror_display: bool = False
) -> None:
    for obj in objects:
        box = (
            mirror_box_for_display(obj.box, frame_width=int(frame.shape[1]))
            if mirror_display
            else obj.box
        )
        color = (0, 128, 255) if obj.is_priority else (0, 190, 80)
        thickness = 3 if obj.is_priority else 2
        cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, thickness)
        text = f"{obj.name} {obj.confidence:.2f}"
        draw_label(frame, text, box.x1, box.y1 - 4, color)


def draw_six_point_grid(
    frame: np.ndarray,
    *,
    selected_position: tuple[int, int] | None = None,
    mirror_display: bool = False,
) -> None:
    """Draw the reviewed 2×3 high-five grid without changing camera ownership."""
    cells = six_point_grid_rectangles(
        frame_width=int(frame.shape[1]), frame_height=int(frame.shape[0])
    )
    if not cells:
        return
    display_selected = (
        (selected_position[0], 4 - selected_position[1])
        if mirror_display and selected_position in cells
        else selected_position
    )
    if display_selected in cells:
        box = cells[display_selected]
        overlay = frame.copy()
        cv2.rectangle(overlay, (box.x1, box.y1), (box.x2, box.y2), (0, 180, 255), -1)
        cv2.addWeighted(overlay, 0.24, frame, 0.76, 0, frame)
    for position, box in cells.items():
        physical_position = (position[0], 4 - position[1]) if mirror_display else position
        color = (0, 220, 255) if position == display_selected else (230, 230, 230)
        thickness = 3 if position == display_selected else 1
        cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, thickness)
        cv2.putText(
            frame,
            f"{physical_position[0]}{physical_position[1]}",
            (box.x1 + 8, box.y1 + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )


def draw_hand_detection(
    frame: np.ndarray, detection: HandDetection | None, *, mirror_display: bool = False
) -> None:
    """Draw the current MediaPipe hand bounds and centre over the six-point grid."""
    if detection is None:
        return
    raw_box = Box(*detection.box)
    box = (
        mirror_box_for_display(raw_box, frame_width=int(frame.shape[1]))
        if mirror_display
        else raw_box
    )
    x1, y1, x2, y2 = box.x1, box.y1, box.x2, box.y2
    center = (
        int(frame.shape[1]) - 1 - detection.center[0], detection.center[1]
    ) if mirror_display else detection.center
    color = (60, 255, 80)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.circle(frame, center, 5, color, -1)
    draw_label(frame, f"hand {detection.confidence:.2f}", x1, y1 - 4, color)


def mirror_for_display(frame: np.ndarray) -> np.ndarray:
    """Mirror only the visual output; inference and arm coordinates stay physical."""
    return cv2.flip(frame, 1)


def draw_status(frame: np.ndarray, fps: float, object_every: int, objects: list[ObjectResult]) -> None:
    cup_count = sum(1 for obj in objects if obj.name == "cup")
    bottle_count = sum(1 for obj in objects if obj.name == "bottle")
    status = f"FPS {fps:.1f} | objects every {object_every}f | cups {cup_count} | bottles {bottle_count} | q: quit"
    draw_label(frame, status, 8, 24, (70, 70, 70))


def draw_return_code(frame: np.ndarray, status: ReturnCodeStatus | None) -> None:
    if status is None:
        return

    if status.code == 1:
        color = (0, 0, 220)
    elif status.code == 2:
        color = (255, 120, 0)
    else:
        color = (70, 70, 70)

    if status.smoothed_distance_m is None:
        distance = "distance n/a"
    else:
        distance = f"distance {status.smoothed_distance_m * 100.0:.0f}cm"
    face_pct = status.face_presence_ratio * 100.0
    text = f"return={status.code} | {distance} | close {status.close_seconds:.1f}s | face {face_pct:.1f}%"
    draw_label(frame, text, 8, 80, color)


def draw_emotion_status(
    frame: np.ndarray,
    emotions: list[EmotionResult],
    *,
    next_inference_seconds: int | None = None,
    paused: bool = False,
) -> None:
    if not emotions:
        draw_label(frame, "emotion_return=0 | no face emotion", 8, 108, (70, 70, 70))
    else:
        primary = emotions[0]
        if primary.confirmed:
            color = (180, 80, 220)
            text = f"emotion_return={primary.return_code} | {primary.display_name} {primary.confidence:.2f}"
        else:
            color = (70, 70, 70)
            text = f"emotion_return=0 | uncertain {primary.display_name} {primary.confidence:.2f}"
        draw_label(frame, text, 8, 108, color)
    if paused:
        countdown_text = "emotion next: paused"
    elif next_inference_seconds is None:
        countdown_text = "emotion next: waiting for face"
    else:
        minutes, seconds = divmod(next_inference_seconds, 60)
        countdown_text = f"emotion next: {minutes:02d}:{seconds:02d}"
    draw_label(frame, countdown_text, 8, 136, (70, 70, 70))


def draw_drink_reminder(frame: np.ndarray, status: DrinkReminderStatus | None) -> None:

    if status is None or not status.enabled:
        return

    minutes_since = status.seconds_since_overlap / 60.0
    if status.alert:
        color = (0, 0, 220)
        text = f"drink_return=1 | Drink water: no bottle-face overlap for {minutes_since:.1f} min"
    elif status.overlap_now:
        color = (0, 150, 0)
        text = "drink_return=0 | Drink detected: timer reset"
    else:
        color = (70, 70, 70)
        minutes_left = status.seconds_until_alert / 60.0
        text = f"drink_return=0 | Drink reminder in {minutes_left:.1f} min"
    draw_label(frame, text, 8, 52, color)


def result_to_json(
    frame_index: int,
    fps: float,
    faces: list[FaceResult],
    objects: list[ObjectResult],
    emotions: list[EmotionResult],
    drink_status: DrinkReminderStatus | None,
    return_status: ReturnCodeStatus | None,
    scene_status: SceneDescriptionStatus | None = None,
) -> str:
    payload: dict[str, Any] = {
        "frame": frame_index,
        "fps": round(fps, 2),
        "faces": [
            {
                **asdict(face),
                "distance_m": None if face.distance_m is None else round(face.distance_m, 3),
            }
            for face in faces
        ],
        "objects": [asdict(obj) for obj in objects],
        "cups": [asdict(obj) for obj in objects if obj.name == "cup"],
        "bottles": [asdict(obj) for obj in objects if obj.name == "bottle"],
        "return_code": 0 if return_status is None else return_status.code,
        "drink_return_code": 1 if drink_status is not None and drink_status.alert else 0,
        "emotion_return_code": emotions[0].return_code if emotions else 0,
        "scene_description": "" if scene_status is None else scene_status.description,
        "scene_description_updated": False if scene_status is None else scene_status.updated,
        "emotions": [
            {
                **asdict(emotion),
                "confidence": round(emotion.confidence, 4),
            }
            for emotion in emotions
        ],
    }
    if return_status is not None:
        payload["return_status"] = {
            **asdict(return_status),
            "smoothed_distance_m": None
            if return_status.smoothed_distance_m is None
            else round(return_status.smoothed_distance_m, 3),
            "close_seconds": round(return_status.close_seconds, 2),
            "face_presence_ratio": round(return_status.face_presence_ratio, 4),
            "face_window_seconds": round(return_status.face_window_seconds, 2),
            "face_seen_seconds": round(return_status.face_seen_seconds, 2),
        }
    if drink_status is not None:
        payload["drink_reminder"] = {
            **asdict(drink_status),
            "return_code": 1 if drink_status.alert else 0,
            "seconds_since_overlap": round(drink_status.seconds_since_overlap, 2),
            "seconds_until_alert": round(drink_status.seconds_until_alert, 2),
        }
    payload["scene_description_status"] = (
        {"enabled": False, "state": "disabled", "pending": False, "error": ""}
        if scene_status is None
        else asdict(scene_status)
    )
    return json.dumps(payload, ensure_ascii=True)


def open_capture(source: int | str, width: int | None, height: int | None) -> cv2.VideoCapture:
    api_preference = cv2.CAP_DSHOW if isinstance(source, int) and platform.system() == "Windows" else 0
    capture = cv2.VideoCapture(source, api_preference)
    if width:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def open_capture_with_fallback(
    source: int | str,
    width: int | None,
    height: int | None,
) -> tuple[cv2.VideoCapture | None, int | str | None]:
    """Open the requested source, recovering from Linux USB re-enumeration."""
    should_probe_frame = is_recoverable_camera_source(source)
    for candidate in camera_source_candidates(source):
        capture = open_capture(candidate, width, height)
        opened = capture.isOpened()
        if opened and should_probe_frame:
            opened, _ = capture.read()
        if opened:
            return capture, candidate
        capture.release()
    return None, None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monocular face distance, object detection, and emotion recognition demo.")
    parser.add_argument("--source", default="0", help="Camera index or video file path. Default: 0")
    parser.add_argument("--width", type=int, default=640, help="Requested capture width.")
    parser.add_argument("--height", type=int, default=480, help="Requested capture height.")
    parser.add_argument("--target-fps", type=float, default=0.0, help="Maximum processing FPS. 0 processes every captured frame.")
    parser.add_argument(
        "--model",
        default=str(DEFAULT_MODEL_PATH),
        help="YOLO model path/name. Defaults to models/vision/yolo11n.pt.",
    )
    parser.add_argument(
        "--fibo-object-model",
        default=str(DEFAULT_FIBO_OBJECT_MODEL_PATH),
        help="Licensed Fibo YOLOv8n fmodel used for hardware-accelerated object detection.",
    )
    parser.add_argument("--device", default="cpu", help="Ultralytics device, for example cpu, 0, cuda:0.")
    parser.add_argument("--imgsz", type=int, default=320, help="Detector input size. 320 is a good low-latency start.")
    parser.add_argument("--conf", type=float, default=0.35, help="Object confidence threshold.")
    parser.add_argument("--iou", type=float, default=0.45, help="Object NMS IOU threshold.")
    parser.add_argument("--object-every", type=int, default=3, help="Run object detection every N frames.")
    parser.add_argument(
        "--object-interval-seconds",
        type=float,
        default=0.0,
        help="Minimum seconds between object detections. A value above 0 overrides --object-every.",
    )
    parser.add_argument("--cup-only", action="store_true", help="Only keep priority detections: cup and bottle.")
    parser.add_argument("--no-objects", action="store_true", help="Disable object detection.")
    parser.add_argument("--no-faces", action="store_true", help="Disable face detection and distance estimation.")
    parser.add_argument("--min-face-px", type=int, default=60, help="Minimum face size in pixels.")
    parser.add_argument("--face-confidence", type=float, default=0.50, help="MediaPipe face detection confidence threshold.")
    parser.add_argument("--face-interval-seconds", type=float, default=0.0, help="Minimum seconds between face detections. 0 detects every frame.")
    parser.add_argument("--face-model-selection", type=int, choices=(0, 1), default=0, help="MediaPipe face model: 0 for close range, 1 for full range.")
    parser.add_argument("--known-face-width-m", type=float, default=0.16, help="Approximate real face width in meters.")
    parser.add_argument("--hfov-deg", type=float, default=70.0, help="Camera horizontal FOV if focal-px is unknown.")
    parser.add_argument("--focal-px", type=float, default=None, help="Known focal length in pixels. Overrides hfov-deg.")
    parser.add_argument("--distance-smoothing", type=float, default=0.35, help="EMA smoothing alpha for distance.")
    parser.add_argument("--distance-return-threshold-cm", type=float, default=50.0, help="Return 1 when smoothed face distance stays below this threshold.")
    parser.add_argument("--distance-return-seconds", type=float, default=5.0, help="Seconds below distance threshold before return code becomes 1.")
    parser.add_argument("--face-return-window-minutes", type=float, default=20.0, help="Sliding window length for return code 2 face-presence ratio.")
    parser.add_argument("--face-return-ratio", type=float, default=0.90, help="Return 2 when face is detected for at least this ratio of the full window.")
    parser.add_argument(
        "--ui-vision-status-file",
        default=str(PROJECT_ROOT / "components" / "touch_ui" / "saves" / "vision_status.json"),
        help="Deprecated compatibility path; realtime UI state is sent over local IPC.",
    )
    parser.add_argument("--ui-status-host", default="127.0.0.1", help="Touch UI IPC host.")
    parser.add_argument("--ui-status-port", type=int, default=8765, help="Touch UI IPC port.")
    parser.add_argument("--no-ui-status-ipc", action="store_true", help="Disable direct UI status IPC.")
    parser.add_argument("--no-drink-reminder", action="store_true", help="Disable bottle-face hydration reminder.")
    parser.add_argument("--drink-reminder-minutes", type=float, default=20.0, help="Alert after this many minutes without bottle-face overlap.")
    parser.add_argument("--drink-overlap-threshold", type=float, default=0.03, help="Minimum intersection ratio between bottle and face boxes.")
    parser.add_argument(
        "--drink-confirm-interval-seconds",
        type=float,
        default=float(os.environ.get("XINGBAO_VISION_DRINK_CONFIRM_INTERVAL_SECONDS", "0.8")),
        help="Bottle, face, and FER interval while confirming a detected bottle is being used.",
    )
    parser.add_argument(
        "--drink-bottle-cooldown-seconds",
        type=float,
        default=float(os.environ.get("XINGBAO_VISION_DRINK_BOTTLE_COOLDOWN_SECONDS", "60")),
        help="Seconds to suspend bottle inference after a bottle-face overlap resets hydration time.",
    )
    parser.add_argument("--no-emotion", action="store_true", help="Disable facial emotion recognition.")
    parser.add_argument(
        "--emotion-model",
        default=str(DEFAULT_EMOTION_MODEL_PATH),
        help="HSEmotion EmotiEffNet-B0 ONNX model path.",
    )
    parser.add_argument("--emotion-threshold", type=float, default=0.60, help="Minimum emotion confidence before emotion_return_code is non-zero.")
    parser.add_argument(
        "--sadness-threshold",
        type=float,
        default=0.45,
        help="Minimum confidence for sadness only; other emotions use --emotion-threshold.",
    )
    parser.add_argument(
        "--anger-threshold",
        type=float,
        default=0.45,
        help="Minimum confidence for anger only; other emotions use --emotion-threshold.",
    )
    parser.add_argument(
        "--happiness-threshold",
        type=float,
        default=0.70,
        help="Minimum confidence for happiness only; other emotions use --emotion-threshold.",
    )
    parser.add_argument("--emotion-every", type=int, default=1, help="Run emotion inference every N frames when no interval is set.")
    parser.add_argument("--emotion-interval-seconds", type=float, default=300.0, help="Minimum seconds between emotion inferences.")
    parser.add_argument("--emotion-control-listen-host", default="127.0.0.1")
    parser.add_argument("--emotion-control-listen-port", type=int, default=10002)
    parser.add_argument("--no-emotion-control-server", action="store_true")
    parser.add_argument("--no-kimi", action="store_true", help="Disable optional Kimi multi-frame scene description.")
    parser.add_argument("--kimi-model", default="kimi-k2.6", help="Kimi model used only when MOONSHOT_API_KEY is set.")
    parser.add_argument("--kimi-base-url", default="https://api.moonshot.cn/v1", help="Moonshot OpenAI-compatible API base URL.")
    parser.add_argument("--kimi-confirm-seconds", type=float, default=0.8, help="Continuous person/face presence before a Kimi request.")
    parser.add_argument("--kimi-cooldown-seconds", type=float, default=60.0, help="Minimum seconds between Kimi scene requests.")
    parser.add_argument("--kimi-timeout-seconds", type=float, default=30.0, help="Kimi HTTP request timeout.")
    parser.add_argument(
        "--companion-settings-file",
        default=str(PROJECT_ROOT / "components" / "touch_ui" / "saves" / "desktop_settings.json"),
        help="Desktop settings file whose active_companion flag controls Kimi scene recognition.",
    )
    parser.add_argument("--headless", action="store_true", help="Do not show the OpenCV window.")
    parser.add_argument("--always-on-top", action="store_true", help="Keep the visualization window above other windows when supported.")
    parser.add_argument("--no-hands", action="store_true", help="Disable integrated high-five hand recognition.")
    parser.add_argument("--hand-model", default=str(DEFAULT_HAND_MODEL_PATH), help="MediaPipe hand-landmarker model.")
    parser.add_argument("--vision-point-host", default="127.0.0.1")
    parser.add_argument("--vision-point-port", type=int, default=10000)
    parser.add_argument("--vision-point-ready-timeout", type=float, default=12.0)
    parser.add_argument("--no-hand-control-server", action="store_true", help="Disable the localhost high-five enable/disable control endpoint.")
    parser.add_argument("--hand-control-listen-host", default="127.0.0.1")
    parser.add_argument("--hand-control-listen-port", type=int, default=10001)
    parser.add_argument("--hand-stable-frames", type=int, default=1)
    parser.add_argument("--hand-sample-seconds", type=float, default=0.8)
    parser.add_argument("--max-hands", type=int, default=2)
    parser.add_argument("--hand-threshold", type=float, default=0.50)
    parser.add_argument("--json", action="store_true", help="Print JSON result for each frame.")
    parser.add_argument(
        "--xingbao-events",
        action="store_true",
        help="Print debounced high-level vision_state events for Xingbao.",
    )
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames. 0 means run until quit/end.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if VISION_DEPENDENCY_ERROR is not None:
        print(
            "Vision dependencies are unavailable. "
            "Run: python -m pip install -r requirements-vision.txt",
            file=sys.stderr,
        )
        print(f"Import error: {VISION_DEPENDENCY_ERROR}", file=sys.stderr)
        return 5

    source = parse_source(args.source)
    capture, active_source = open_capture_with_fallback(
        source,
        args.width,
        args.height,
    )
    if capture is None:
        print(f"Could not open video source: {args.source}", file=sys.stderr)
        return 2
    if str(active_source) != str(source):
        print(
            f"camera_source_selected: requested={args.source} active={active_source}",
            file=sys.stderr,
            flush=True,
        )

    face_detector: MediaPipeFaceDetector | None = None
    distance_estimator: FaceDistanceEstimator | None = None
    if not args.no_faces:
        try:
            face_detector = MediaPipeFaceDetector(
                args.min_face_px,
                args.face_confidence,
                args.face_model_selection,
            )
            print(
                f"face_detector_backend:mediapipe:model_selection={args.face_model_selection}",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:
            print(f"Could not initialize MediaPipe face detector: {exc}", file=sys.stderr)
            capture.release()
            return 3

    ui_status_notifier = None
    if not args.no_ui_status_ipc:
        ui_status_notifier = UiVisionStatusNotifier(args.ui_status_host, args.ui_status_port)
        ui_status_notifier.publish(False, False)
    if not args.no_faces:
        distance_estimator = FaceDistanceEstimator(
            known_face_width_m=args.known_face_width_m,
            horizontal_fov_deg=args.hfov_deg,
            focal_px=args.focal_px,
            smoothing=args.distance_smoothing,
        )

    object_detector: FiboYoloObjectDetector | None = None
    if not args.no_objects:
        try:
            object_detector = FiboYoloObjectDetector(
                model_path=Path(args.fibo_object_model),
                priority_names=set(DRINK_CONTAINER_NAMES),
                cup_only=True,
                confidence_threshold=args.conf,
            )
            print(
                f"object_detector_backend:fibo_dsp:model={args.fibo_object_model}:classes=bottle,cup",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:
            print(f"Could not initialize object detector: {exc}", file=sys.stderr)
            print("Hint: make sure the Fibo model and board license files are available.", file=sys.stderr)
            return 3

    frame_index = 0
    last_faces: list[FaceResult] = []
    last_objects: list[ObjectResult] = []
    last_object_inference_time = float("-inf")
    last_face_inference_time = float("-inf")
    last_emotions: list[EmotionResult] = []
    last_emotion_inference_time = float("-inf")
    last_time = time.perf_counter()
    fps = 0.0
    return_monitor: FaceReturnCodeMonitor | None = None
    if not args.no_faces:
        return_monitor = FaceReturnCodeMonitor(
            distance_threshold_m=args.distance_return_threshold_cm / 100.0,
            close_duration_seconds=args.distance_return_seconds,
            face_window_seconds=args.face_return_window_minutes * 60.0,
            face_ratio_threshold=args.face_return_ratio,
            smoothing=args.distance_smoothing,
        )
    drink_reminder: DrinkReminder | None = None
    hydration_scheduler: HydrationInferenceScheduler | None = None
    if not args.no_drink_reminder and not args.no_faces and not args.no_objects:
        drink_reminder = DrinkReminder(
            interval_seconds=args.drink_reminder_minutes * 60.0,
            overlap_threshold=args.drink_overlap_threshold,
        )
        hydration_scheduler = HydrationInferenceScheduler(
            normal_object_interval_seconds=args.object_interval_seconds,
            normal_face_interval_seconds=args.face_interval_seconds,
            confirm_interval_seconds=args.drink_confirm_interval_seconds,
            bottle_cooldown_seconds=args.drink_bottle_cooldown_seconds,
        )

    emotion_detector: EmotionDetector | None = None
    if not args.no_emotion and not args.no_faces:
        try:
            emotion_detector = EmotionDetector(
                model_path=args.emotion_model,
                confidence_threshold=args.emotion_threshold,
                sadness_threshold=args.sadness_threshold,
                anger_threshold=args.anger_threshold,
                happiness_threshold=args.happiness_threshold,
            )
        except Exception as exc:
            print(f"Could not initialize emotion detector: {exc}", file=sys.stderr)
            print("Hint: download emotion-ferplus-8.onnx or run with --no-emotion.", file=sys.stderr)
            return 4

    emotion_broker = EmotionInferenceBroker()
    emotion_control: EmotionInferenceServer | None = None
    if not args.no_emotion_control_server:
        try:
            emotion_control = EmotionInferenceServer(
                emotion_broker,
                args.emotion_control_listen_host,
                args.emotion_control_listen_port,
            )
            emotion_control.start()
            print(
                "emotion_inference_endpoint_ready:host={} port={}".format(
                    args.emotion_control_listen_host,
                    args.emotion_control_listen_port,
                ),
                flush=True,
            )
        except OSError as exc:
            print(f"emotion_inference_endpoint_unavailable:{exc}", file=sys.stderr, flush=True)

    hand_detector: HandDetector | None = None
    hand_control: HandControlServer | None = None
    high_five_processor: HighFiveFrameProcessor | None = None
    if not args.no_hands:
        try:
            hand_detector = HandDetector(Path(args.hand_model), args.max_hands, args.hand_threshold)
            gate = HandRecognitionGate()
            wait_for_vision_point_endpoint(args.vision_point_host, args.vision_point_port, args.vision_point_ready_timeout)
            high_five_processor = HighFiveFrameProcessor(
                hand_detector, gate,
                vision_point_host=args.vision_point_host,
                vision_point_port=args.vision_point_port,
                stable_frames=args.hand_stable_frames,
                sample_seconds=args.hand_sample_seconds,
            )
            if not args.no_hand_control_server:
                hand_control = HandControlServer(gate, args.hand_control_listen_host, args.hand_control_listen_port)
                hand_control.start()
            print(json.dumps({"event": "vision_high_five_endpoints_ready", "vision_point_endpoint": f"{args.vision_point_host}:{args.vision_point_port}", "control_endpoint": None if args.no_hand_control_server else f"{args.hand_control_listen_host}:{args.hand_control_listen_port}"}, ensure_ascii=False), flush=True)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            print(f"high_five_vision_unavailable:{type(exc).__name__}:{exc}", file=sys.stderr, flush=True)
            if hand_control is not None:
                hand_control.close()
            if hand_detector is not None:
                hand_detector.close()
            hand_control = None
            hand_detector = None

    scene_controller: SceneDescriptionController | None = None
    companion_settings_path = Path(args.companion_settings_file).expanduser()
    companion_enabled = active_companion_enabled(companion_settings_path)
    last_companion_poll = 0.0
    kimi_key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if kimi_key and not args.no_kimi:
        scene_controller = SceneDescriptionController(
            KimiSceneClient(
                kimi_key,
                model=args.kimi_model,
                base_url=args.kimi_base_url,
                timeout=args.kimi_timeout_seconds,
            ),
            confirm_seconds=args.kimi_confirm_seconds,
            cooldown_seconds=args.kimi_cooldown_seconds,
        )
        scene_controller.set_enabled(companion_enabled)
        print(
            "Kimi scene description {}.".format("enabled" if companion_enabled else "disabled"),
            file=sys.stderr,
            flush=True,
        )
    event_adapter = VisionEventAdapter() if args.xingbao_events else None
    reconnect_attempts = 0
    topmost_requested = bool(args.always_on_top)

    try:
        while True:
            frame_started_at = time.perf_counter()
            ok, frame = capture.read()
            if not ok:
                if not is_recoverable_camera_source(source):
                    break
                capture.release()
                reconnect_attempts += 1
                time.sleep(0.75)
                capture, active_source = open_capture_with_fallback(
                    source,
                    args.width,
                    args.height,
                )
                if capture is None:
                    if reconnect_attempts == 1 or reconnect_attempts % 10 == 0:
                        print(
                            "camera_reconnect_waiting: "
                            f"requested={args.source} attempts={reconnect_attempts}",
                            file=sys.stderr,
                            flush=True,
                        )
                    continue
                print(
                    f"camera_reconnected: requested={args.source} "
                    f"active={active_source} attempts={reconnect_attempts}",
                    file=sys.stderr,
                    flush=True,
                )
                reconnect_attempts = 0
                last_time = time.perf_counter()
                continue

            now = time.perf_counter()
            dt = now - last_time
            last_time = now
            if dt > 0:
                current_fps = 1.0 / dt
                fps = current_fps if fps == 0.0 else 0.12 * current_fps + 0.88 * fps

            hand_interaction_active = (
                high_five_processor.process(frame)
                if high_five_processor is not None
                else False
            )
            if non_hand_inference_paused(hand_interaction_active):
                pending_emotion_requests = emotion_broker.take_pending()
                if pending_emotion_requests:
                    emotion_broker.respond(
                        pending_emotion_requests,
                        {"ok": False, "error": "hand_interaction_active"},
                    )
                last_objects = []
                last_faces = []
                last_emotions = []
                faces = []
                emotions = []
                drink_status = None
                return_status = None
                scene_status = None
                if ui_status_notifier is not None:
                    ui_status_notifier.publish(False, False)
            else:
                pending_emotion_requests = emotion_broker.take_pending()
                if hydration_scheduler is not None:
                    should_run_objects = hydration_scheduler.object_inference_due(now)
                else:
                    object_interval = max(0.0, args.object_interval_seconds)
                    should_run_objects = (
                        object_interval > 0.0
                        and now - last_object_inference_time >= object_interval
                    ) or (
                        object_interval == 0.0
                        and frame_index % max(1, args.object_every) == 0
                    )
                if object_detector is not None and should_run_objects:
                    try:
                        last_objects = object_detector.detect(frame)
                    except RuntimeError as exc:
                        last_objects = []
                        print(f"fibo_object_detection_failed:{exc}", file=sys.stderr, flush=True)
                    last_object_inference_time = now
                    if hydration_scheduler is not None:
                        hydration_scheduler.record_object_inference(
                            now, bottle_detected=bool(last_objects)
                        )

                should_run_faces = bool(pending_emotion_requests) or (
                    hydration_scheduler.face_inference_due(now)
                    if hydration_scheduler is not None
                    else face_inference_due(
                        now=now,
                        last_inference_time=last_face_inference_time,
                        interval_seconds=args.face_interval_seconds,
                    )
                )
                if face_detector is None or distance_estimator is None:
                    last_faces = []
                elif should_run_faces:
                    last_faces = face_detector.detect(frame, distance_estimator)
                    last_face_inference_time = now
                    if hydration_scheduler is not None:
                        hydration_scheduler.record_face_inference(now)
                faces = last_faces

                should_run_emotion = bool(pending_emotion_requests) or emotion_inference_due(
                    now=now,
                    last_inference_time=last_emotion_inference_time,
                    interval_seconds=args.emotion_interval_seconds,
                )
                if emotion_detector is None or not faces:
                    last_emotions = []
                elif should_run_emotion:
                    last_emotions = emotion_detector.detect(frame, faces)
                    last_emotion_inference_time = now
                emotions = last_emotions
                if pending_emotion_requests:
                    primary = emotions[0] if emotions else None
                    emotion_broker.respond(
                        pending_emotion_requests,
                        {
                            "ok": primary is not None,
                            "label": primary.label if primary is not None else "",
                            "display_name": primary.display_name if primary is not None else "",
                            "confidence": round(primary.confidence, 4) if primary is not None else 0.0,
                            "confirmed": bool(primary.confirmed) if primary is not None else False,
                            "error": "no_face_or_uncertain" if primary is None else "",
                        },
                    )
                drink_status = drink_reminder.update(faces, last_objects) if drink_reminder is not None else None
                if (
                    drink_status is not None
                    and drink_status.overlap_now
                    and hydration_scheduler is not None
                    and hydration_scheduler.record_drink_reset(now)
                ):
                    last_objects = []
                    print(
                        "hydration_detection_cooldown:bottle_seconds={}".format(
                            args.drink_bottle_cooldown_seconds
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                return_status = return_monitor.update(faces) if return_monitor is not None else None
                if ui_status_notifier is not None:
                    # UI feedback is immediate: unlike the spoken warning, it does
                    # not wait for distance_return_seconds to elapse.
                    ui_distance_alert = (
                        bool(faces)
                        and return_status is not None
                        and return_status.smoothed_distance_m is not None
                        and return_status.smoothed_distance_m
                        < args.distance_return_threshold_cm / 100.0
                    )
                    ui_status_notifier.publish(
                        ui_distance_alert,
                        drink_status is not None and drink_status.alert,
                    )
                scene_status = None
                if scene_controller is not None:
                    if time.monotonic() - last_companion_poll >= 0.5:
                        last_companion_poll = time.monotonic()
                        desired_enabled = active_companion_enabled(companion_settings_path)
                        if desired_enabled != companion_enabled:
                            companion_enabled = desired_enabled
                            scene_controller.set_enabled(companion_enabled)
                            print(
                                "Kimi scene description {} by active_companion setting.".format(
                                    "enabled" if companion_enabled else "disabled"
                                ),
                                file=sys.stderr,
                                flush=True,
                            )
                    person_present = bool(faces) or any(
                        obj.name == "person" and obj.confidence >= 0.55
                        for obj in last_objects
                    )
                    scene_status = scene_controller.update(frame, person_present=person_present)
                    if scene_status.updated and scene_status.description:
                        print(
                            "Kimi scene description: {}".format(
                                scene_status.description.replace("\n", " ").strip()
                            ),
                            file=sys.stderr,
                            flush=True,
                        )

            display_frame = mirror_for_display(frame)
            draw_objects(display_frame, last_objects, mirror_display=True)
            draw_faces(display_frame, faces, emotions, mirror_display=True)
            draw_six_point_grid(
                display_frame,
                selected_position=(
                    high_five_processor.last_position
                    if high_five_processor is not None
                    else None
                ),
                mirror_display=True,
            )
            draw_hand_detection(
                display_frame,
                high_five_processor.last_detection if high_five_processor is not None else None,
                mirror_display=True,
            )
            draw_status(display_frame, fps, max(1, args.object_every), last_objects)
            draw_drink_reminder(display_frame, drink_status)
            draw_return_code(display_frame, return_status)
            draw_emotion_status(
                display_frame,
                emotions,
                next_inference_seconds=emotion_countdown_seconds(
                    now=now,
                    last_inference_time=last_emotion_inference_time,
                    interval_seconds=args.emotion_interval_seconds,
                ),
                paused=hand_interaction_active,
            )

            if args.json or event_adapter is not None:
                frame_json = result_to_json(
                    frame_index,
                    fps,
                    faces,
                    last_objects,
                    emotions,
                    drink_status,
                    return_status,
                    scene_status,
                )
                if args.json:
                    print(frame_json, flush=True)
                if event_adapter is not None:
                    for event in event_adapter.update(json.loads(frame_json)):
                        event_payload = event.get("payload")
                        safe_event_payload = (
                            event_payload if isinstance(event_payload, dict) else {}
                        )
                        print(
                            "vision_event_emit:state={} confidence={} distance_m={}".format(
                                safe_event_payload.get("state", ""),
                                safe_event_payload.get("confidence", ""),
                                safe_event_payload.get("distance_m", ""),
                            ),
                            file=sys.stderr,
                            flush=True,
                        )
                        print(json.dumps(event, ensure_ascii=False), flush=True)

            if not args.headless:
                cv2.imshow("monocular vision system", display_frame)
                if topmost_requested and platform.system() != "Linux":
                    try:
                        cv2.setWindowProperty(
                            "monocular vision system", cv2.WND_PROP_TOPMOST, 1
                        )
                    except cv2.error:
                        pass
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    break

            frame_index += 1
            if args.max_frames and frame_index >= args.max_frames:
                break
            if args.target_fps > 0.0:
                remaining = 1.0 / args.target_fps - (time.perf_counter() - frame_started_at)
                if remaining > 0.0:
                    time.sleep(remaining)
    finally:
        if emotion_control is not None:
            emotion_control.close()
        if ui_status_notifier is not None:
            ui_status_notifier.publish(False, False)
        if capture is not None:
            capture.release()
        if face_detector is not None:
            face_detector.close()
        if hand_detector is not None:
            hand_detector.close()
        if object_detector is not None:
            object_detector.close()
        if hand_control is not None:
            hand_control.close()
        if not args.headless:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
