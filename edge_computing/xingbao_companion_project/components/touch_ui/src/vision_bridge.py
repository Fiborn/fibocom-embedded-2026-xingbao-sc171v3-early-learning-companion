"""Run the released vision model and translate its JSON output for the desktop."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading

from .desktop_integrations import VisionStateAdapter


def vision_json_to_flags(payload):
    """return_code=1 means too close; drink_return_code=1 means drink reminder."""
    payload = dict(payload or {})
    return (
        1 if payload.get("return_code") == 1 else 0,
        1 if payload.get("drink_return_code") == 1 else 0,
    )


class VisionProcessBridge:
    def __init__(self, release_dir, status_file, source="0", python_executable=None,
                 imgsz=320, object_every=5, extra_args=None, project_root=None,
                 companion_settings_path=None):
        self.release_dir = Path(release_dir).resolve()
        self.project_root = Path(project_root or self.release_dir).resolve()
        self.companion_settings_path = Path(
            companion_settings_path
            or self.project_root / "components" / "touch_ui" / "saves" / "desktop_settings.json"
        ).resolve()
        self.adapter = VisionStateAdapter(status_file)
        self.source = str(source)
        self.python_executable = python_executable or sys.executable
        self.imgsz = int(imgsz)
        self.object_every = int(object_every)
        self.extra_args = list(extra_args or [])
        self.process = None
        self.thread = None
        self.last_error = None
        self.last_flags = None

    def command(self):
        command = [
            self.python_executable, "-m", "multimodal.vision_system.app",
            "--source", self.source,
            "--model", str(self.release_dir / "yolo11n.pt"),
            "--imgsz", str(self.imgsz),
            "--object-every", str(self.object_every),
            "--headless", "--json",
            "--companion-settings-file", str(self.companion_settings_path),
        ]
        if importlib.util.find_spec("ultralytics") is None:
            command.append("--no-objects")
        return [*command, *self.extra_args]

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return {"ok": True, "already_running": True}
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                self.command(), cwd=str(self.project_root), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=creationflags,
            )
        except OSError as exc:
            self.last_error = str(exc)
            self.adapter.write(0, 0)
            return {"ok": False, "error": self.last_error}
        self.thread = threading.Thread(target=self._consume, name="vision-json-bridge", daemon=True)
        self.thread.start()
        return {"ok": True, "pid": self.process.pid, "command": self.command()}

    def _consume(self):
        try:
            for line in self.process.stdout:
                try:
                    payload = json.loads(line)
                except (TypeError, ValueError):
                    continue
                flags = vision_json_to_flags(payload)
                if flags != self.last_flags:
                    self.adapter.write(*flags)
                    self.last_flags = flags
        finally:
            self.adapter.write(0, 0)

    def stop(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
