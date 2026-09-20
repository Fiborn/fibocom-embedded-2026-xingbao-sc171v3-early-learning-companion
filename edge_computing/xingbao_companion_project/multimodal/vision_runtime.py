"""Managed subprocess bridge for Xingbao's camera vision runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VisionEventHandler = Callable[[Dict[str, Any]], None]
VisionLogHandler = Callable[[str], None]


@dataclass(frozen=True)
class VisionRuntimeConfig:
    """Runtime settings selected from the board's ``runtime.env`` file."""

    python_executable: str = sys.executable
    source: str = "0"
    width: int = 640
    height: int = 480
    target_fps: float = 0.0
    model_path: Path = PROJECT_ROOT / "models" / "vision" / "yolo11n.pt"
    emotion_model_path: Path = (
        PROJECT_ROOT / "models" / "vision" / "enet_b0_8_best_afew.onnx"
    )
    imgsz: int = 320
    object_confidence: float = 0.35
    object_every: int = 5
    object_interval_seconds: float = 1.0
    emotion_threshold: float = 0.60
    face_interval_seconds: float = 0.0
    emotion_interval_seconds: float = 300.0
    sadness_threshold: float = 0.45
    anger_threshold: float = 0.45
    happiness_threshold: float = 0.70
    no_objects: bool = False
    no_emotion: bool = False
    visualize: bool = False
    always_on_top: bool = False

    @classmethod
    def from_environment(
        cls,
        environ: dict[str, str] | None = None,
    ) -> "VisionRuntimeConfig":
        values = os.environ if environ is None else environ
        return cls(
            python_executable=str(
                values.get("XINGBAO_VISION_PYTHON") or sys.executable
            ).strip(),
            source=str(values.get("XINGBAO_VISION_SOURCE") or "0").strip(),
            width=_bounded_int(
                values.get("XINGBAO_VISION_WIDTH"), default=640, minimum=160, maximum=3840,
            ),
            height=_bounded_int(
                values.get("XINGBAO_VISION_HEIGHT"), default=480, minimum=120, maximum=2160,
            ),
            target_fps=_bounded_float(
                values.get("XINGBAO_VISION_TARGET_FPS"), default=0.0, minimum=0.0, maximum=60.0,
            ),
            model_path=_environment_path(
                values.get("XINGBAO_VISION_MODEL"),
                PROJECT_ROOT / "models" / "vision" / "yolo11n.pt",
            ),
            emotion_model_path=_environment_path(
                values.get("XINGBAO_VISION_EMOTION_MODEL"),
                PROJECT_ROOT / "models" / "vision" / "enet_b0_8_best_afew.onnx",
            ),
            imgsz=_bounded_int(
                values.get("XINGBAO_VISION_IMGSZ"),
                default=320,
                minimum=160,
                maximum=1280,
            ),
            object_confidence=_bounded_float(
                values.get("XINGBAO_VISION_OBJECT_CONFIDENCE"),
                default=0.35,
                minimum=0.0,
                maximum=1.0,
            ),
            object_every=_bounded_int(
                values.get("XINGBAO_VISION_OBJECT_EVERY"),
                default=5,
                minimum=1,
                maximum=120,
            ),
            object_interval_seconds=_bounded_float(
                values.get("XINGBAO_VISION_OBJECT_INTERVAL_SECONDS"),
                default=1.0,
                minimum=0.0,
                maximum=60.0,
            ),
            emotion_threshold=_bounded_float(
                values.get("XINGBAO_VISION_EMOTION_THRESHOLD"),
                default=0.60,
                minimum=0.0,
                maximum=1.0,
            ),
            face_interval_seconds=_bounded_float(
                values.get("XINGBAO_VISION_FACE_INTERVAL_SECONDS"), default=0.0, minimum=0.0, maximum=3600.0,
            ),
            emotion_interval_seconds=_bounded_float(
                values.get("XINGBAO_VISION_EMOTION_INTERVAL_SECONDS"), default=300.0, minimum=0.0, maximum=3600.0,
            ),
            sadness_threshold=_bounded_float(
                values.get("XINGBAO_VISION_SADNESS_THRESHOLD"),
                default=0.45,
                minimum=0.0,
                maximum=1.0,
            ),
            anger_threshold=_bounded_float(
                values.get("XINGBAO_VISION_ANGER_THRESHOLD"),
                default=0.45,
                minimum=0.0,
                maximum=1.0,
            ),
            happiness_threshold=_bounded_float(
                values.get("XINGBAO_VISION_HAPPINESS_THRESHOLD"),
                default=0.70,
                minimum=0.0,
                maximum=1.0,
            ),
            no_objects=_environment_bool(
                values.get("XINGBAO_VISION_NO_OBJECTS"),
                default=False,
            ),
            no_emotion=_environment_bool(
                values.get("XINGBAO_VISION_NO_EMOTION"),
                default=False,
            ),
            visualize=_environment_bool(
                values.get("XINGBAO_VISION_VISUALIZE"),
                default=False,
            ),
            always_on_top=_environment_bool(
                values.get("XINGBAO_VISION_ALWAYS_ON_TOP"),
                default=True,
            ),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.python_executable:
            errors.append("vision_python_missing")
        elif not Path(self.python_executable).exists() and not _command_on_path(
            self.python_executable
        ):
            errors.append(f"vision_python_not_found:{self.python_executable}")
        if not self.no_emotion and not self.emotion_model_path.is_file():
            errors.append(f"emotion_model_not_found:{self.emotion_model_path}")
        if not self.no_objects and not self.model_path.is_file():
            errors.append(f"object_model_not_found:{self.model_path}")
        if not (PROJECT_ROOT / "multimodal" / "vision_system" / "app.py").is_file():
            errors.append("vision_entrypoint_not_found")
        return errors

    def command(self) -> list[str]:
        command = [
            self.python_executable,
            "-u",
            "-m",
            "multimodal.vision_system.app",
            "--source",
            self.source,
            "--width",
            str(self.width),
            "--height",
            str(self.height),
            "--target-fps",
            str(self.target_fps),
            "--model",
            str(self.model_path),
            "--emotion-model",
            str(self.emotion_model_path),
            "--imgsz",
            str(self.imgsz),
            "--conf",
            str(self.object_confidence),
            "--object-every",
            str(self.object_every),
            "--object-interval-seconds",
            str(self.object_interval_seconds),
            "--emotion-threshold",
            str(self.emotion_threshold),
            "--face-interval-seconds",
            str(self.face_interval_seconds),
            "--emotion-interval-seconds",
            str(self.emotion_interval_seconds),
            "--sadness-threshold",
            str(self.sadness_threshold),
            "--anger-threshold",
            str(self.anger_threshold),
            "--happiness-threshold",
            str(self.happiness_threshold),
            "--xingbao-events",
        ]
        if not self.visualize:
            command.append("--headless")
        elif self.always_on_top:
            command.append("--always-on-top")
        if self.no_objects:
            command.append("--no-objects")
        if self.no_emotion:
            command.append("--no-emotion")
        return command


class VisionProcessBridge:
    """Own the vision process and deliver its high-level events in-process."""

    def __init__(
        self,
        event_handler: VisionEventHandler,
        *,
        config: VisionRuntimeConfig | None = None,
        log_handler: VisionLogHandler | None = None,
        restart_delay_seconds: float | None = None,
    ) -> None:
        self.event_handler = event_handler
        self.config = config or VisionRuntimeConfig.from_environment()
        self.log_handler = log_handler
        self.restart_delay_seconds = (
            None
            if restart_delay_seconds is None
            else max(0.1, float(restart_delay_seconds))
        )
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._recent_output: deque[str] = deque(maxlen=20)
        self._events_delivered = 0
        self._invalid_lines = 0
        self._handler_errors = 0
        self._rate_limited_events = 0
        self._restart_count = 0
        self._last_event_time: dict[str, float] = {}
        self._exit_code: int | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return {
                    "ok": True,
                    "already_running": True,
                    **self.status(),
                }
            errors = self.config.validate()
            if errors:
                return {
                    "ok": False,
                    "error": "invalid_vision_runtime_config",
                    "details": errors,
                    "command": self.config.command(),
                }
            self._stopping.clear()
            self._exit_code = None
            environment = os.environ.copy()
            environment["PYTHONUNBUFFERED"] = "1"
            if self.config.visualize:
                environment.setdefault("DISPLAY", ":0")
            try:
                self.process = subprocess.Popen(
                    self.config.command(),
                    cwd=str(PROJECT_ROOT),
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as exc:
                self.process = None
                return {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "command": self.config.command(),
                }
            self.thread = threading.Thread(
                target=self._consume,
                name="xingbao-vision-runtime",
                daemon=True,
            )
            self.thread.start()
            return {
                "ok": True,
                "pid": self.process.pid,
                "command": self.config.command(),
                "no_objects": self.config.no_objects,
                "emotion_enabled": not self.config.no_emotion,
            }

    def status(self) -> dict[str, Any]:
        process = self.process
        running = process is not None and process.poll() is None
        return {
            "running": running,
            "pid": process.pid if running and process is not None else None,
            "exit_code": self._exit_code,
            "events_delivered": self._events_delivered,
            "invalid_lines": self._invalid_lines,
            "handler_errors": self._handler_errors,
            "rate_limited_events": self._rate_limited_events,
            "restart_count": self._restart_count,
            "recent_output": list(self._recent_output),
        }

    def close(self) -> None:
        self._stopping.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _consume(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._invalid_lines += 1
                    self._record_output(line)
                    continue
                if not _is_high_level_vision_event(message):
                    self._invalid_lines += 1
                    self._record_output(line)
                    continue
                if not self._allow_event(message):
                    self._rate_limited_events += 1
                    continue
                payload = message.get("payload")
                safe_payload = payload if isinstance(payload, dict) else {}
                self._record_output(
                    "event_send state={} confidence={} distance_m={}".format(
                        safe_payload.get("state", ""),
                        safe_payload.get("confidence", ""),
                        safe_payload.get("distance_m", ""),
                    )
                )
                try:
                    self.event_handler(message)
                except Exception as exc:
                    self._handler_errors += 1
                    self._record_output(
                        f"event_handler_failed:{type(exc).__name__}:{exc}"
                    )
                    continue
                self._events_delivered += 1
        finally:
            self._exit_code = process.poll()
            if self._exit_code is None:
                self._exit_code = process.wait()
            if not self._stopping.is_set():
                self._record_output(f"vision_process_exited:{self._exit_code}")
                if (
                    self.restart_delay_seconds is not None
                    and not self._stopping.wait(self.restart_delay_seconds)
                ):
                    self._restart_count += 1
                    self._record_output(
                        f"vision_process_restarting:{self._restart_count}"
                    )
                    result = self.start()
                    if not result.get("ok"):
                        self._record_output(
                            "vision_restart_failed:{}".format(
                                json.dumps(
                                    result,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                )
                            )
                        )

    def _record_output(self, line: str) -> None:
        safe_line = str(line or "").strip()[-1000:]
        if not safe_line:
            return
        self._recent_output.append(safe_line)
        if self.log_handler is not None:
            self.log_handler(safe_line)

    def _allow_event(self, message: dict[str, Any]) -> bool:
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return False
        state = str(payload.get("state") or "")
        key = state
        minimum_interval = {
            "face_too_close": 30.0,
            "sitting_too_long": 300.0,
            "drink_water_reminder_due": 300.0,
            "drink_reminder_reset": 0.0,
            "child_emotion_detected": 15.0,
        }.get(state, 60.0)
        if state == "child_emotion_detected":
            key = f"{state}:{str(payload.get('emotion') or '')}"
        now = time.monotonic()
        previous = self._last_event_time.get(key, float("-inf"))
        if now - previous < minimum_interval:
            return False
        self._last_event_time[key] = now
        return True


def _is_high_level_vision_event(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("type") != "vision_state" or message.get("source") != "vision":
        return False
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return False
    state = str(payload.get("state") or "").strip()
    return state in {
        "face_too_close",
        "sitting_too_long",
        "drink_water_reminder_due",
        "drink_reminder_reset",
        "child_emotion_detected",
    }


def _environment_path(value: str | None, default: Path) -> Path:
    text = str(value or "").strip()
    path = Path(text).expanduser() if text else default
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _environment_bool(value: str | None, *, default: bool) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _bounded_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bounded_float(
    value: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _command_on_path(command: str) -> bool:
    from shutil import which

    return which(command) is not None
