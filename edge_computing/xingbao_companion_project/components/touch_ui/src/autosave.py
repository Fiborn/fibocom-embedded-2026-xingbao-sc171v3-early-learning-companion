"""Atomic local persistence for device-level growth and game records."""

from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path


class AutoSaveManager:
    def __init__(self, save_dir="saves", interval=12.0, logger=None):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.latest_path = self.save_dir / "latest_save.json"
        self.backup_path = self.save_dir / "autosave_backup.json"
        self.temp_path = self.save_dir / "latest_save.tmp"
        self.interval = max(1.0, float(interval))
        self.logger = logger
        self.dirty = False
        self.elapsed = 0.0
        self.last_saved_at = None
        self.last_error = None

    @staticmethod
    def _valid(data):
        return isinstance(data, dict) and all(isinstance(data.get(key), dict) for key in ("growth", "records", "settings"))

    def load_latest(self):
        for path in (self.latest_path, self.backup_path):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if self._valid(data):
                    self.last_saved_at = data.get("updated_at")
                    self.last_error = None
                    return data
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                self.last_error = str(exc)
        return None

    def save_now(self, state, reason="manual"):
        payload = deepcopy(dict(state))
        payload["version"] = "1.0"
        payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        payload["save_reason"] = str(reason)
        try:
            with self.temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if self.latest_path.exists():
                try:
                    previous = json.loads(self.latest_path.read_text(encoding="utf-8"))
                    if self._valid(previous):
                        shutil.copy2(self.latest_path, self.backup_path)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    pass
            os.replace(self.temp_path, self.latest_path)
            self.last_saved_at = payload["updated_at"]
            self.last_error = None
            self.dirty = False
            self.elapsed = 0.0
            return self.latest_path
        except (OSError, TypeError, ValueError) as exc:
            self.last_error = str(exc)
            try:
                self.temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def mark_dirty(self):
        self.dirty = True

    def update(self, dt, state):
        if not self.dirty:
            return False
        self.elapsed += max(0.0, float(dt))
        if self.elapsed < self.interval:
            return False
        return self.save_now(state, reason="interval") is not None

    def clear_save(self, default_state):
        """Archive existing save files and write a clean default state.

        Logs are intentionally untouched.  The method returns the state it tried
        to save so callers can immediately refresh UI state.
        """
        self.save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for path in (self.latest_path, self.backup_path):
            if not path.exists():
                continue
            archive = path.with_name("{}.cleared_{}.json".format(path.stem, stamp))
            try:
                path.replace(archive)
            except OSError as exc:
                self.last_error = str(exc)
        self.save_now(default_state, reason="clear_save")
        return deepcopy(dict(default_state))

    def export_summary(self):
        return {
            "path": str(self.latest_path),
            "last_saved_at": self.last_saved_at,
            "dirty": self.dirty,
            "last_error": self.last_error,
        }
