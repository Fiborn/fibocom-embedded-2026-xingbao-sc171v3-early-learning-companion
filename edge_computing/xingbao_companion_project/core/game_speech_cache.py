from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MIN_CACHE_BYTES = 1000
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "config" / "game_speech_cache.json"


@dataclass(frozen=True)
class GameSpeechCacheEntry:
    entry_id: str
    text: str
    filename: str


class GameSpeechCache:
    """Resolve and inspect fixed and runtime game TTS cache files."""

    def __init__(
        self,
        cache_dir: str | Path = Path("work/cache"),
        manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
        voice_id: str = "default",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.manifest_path = Path(manifest_path)
        self.voice_id = str(voice_id).strip() or "default"
        self.entries = self._load_manifest()
        self._entries_by_text = {entry.text: entry for entry in self.entries}

    def _load_manifest(self) -> list[GameSpeechCacheEntry]:
        if not self.manifest_path.is_file():
            return []
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8-sig"))
        items = raw.get("phrases", [])
        entries: list[GameSpeechCacheEntry] = []
        for item in items:
            filename = str(item["filename"]).strip()
            if not filename or Path(filename).name != filename:
                raise ValueError(f"Invalid game speech cache filename: {filename!r}")
            entries.append(
                GameSpeechCacheEntry(
                    entry_id=str(item["id"]).strip(),
                    text=str(item["text"]).strip(),
                    filename=filename,
                )
            )
        return entries

    def fixed_files_by_text(self) -> dict[str, str]:
        return {entry.text: entry.filename for entry in self.entries}

    def path_for(self, text: str, voice_id: str) -> Path:
        normalized_text = " ".join(str(text).split())
        normalized_voice = str(voice_id).strip() or "default"
        digest = hashlib.sha256(
            f"{normalized_voice}\0{normalized_text}".encode("utf-8")
        ).hexdigest()[:24]
        return self.cache_dir / "game_tts" / f"{digest}.wav"

    def resolve_path(self, text: str, voice_id: str) -> Path:
        entry = self._entries_by_text.get(str(text).strip())
        if entry is not None:
            return (
                self.cache_dir
                / "game_tts"
                / self._voice_namespace(voice_id)
                / entry.filename
            )
        return self.path_for(text, voice_id)

    @staticmethod
    def _voice_namespace(voice_id: str) -> str:
        normalized = str(voice_id).strip() or "default"
        readable = re.sub(r"[^A-Za-z0-9_.-]+", "-", normalized).strip(".-")
        readable = readable[:32] or "voice"
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
        return f"{readable}-{digest}"

    @staticmethod
    def is_valid(path: str | Path) -> bool:
        candidate = Path(path)
        try:
            if not candidate.is_file() or candidate.stat().st_size <= MIN_CACHE_BYTES:
                return False
            with wave.open(str(candidate), "rb") as source:
                if source.getcomptype() != "NONE":
                    return False
                frame_size = source.getnchannels() * source.getsampwidth()
                declared_frames = source.getnframes()
                if frame_size <= 0 or declared_frames <= 0:
                    return False
                # Read exactly the declared amount.  A number of TTS downloads
                # contain a 2 GB placeholder data length even though the file
                # itself contains only a few seconds of PCM.
                # Never trust the header enough to request a multi-gigabyte
                # allocation: the file's physical size is the hard upper
                # bound for an uncompressed PCM payload.
                max_physical_frames = candidate.stat().st_size // frame_size
                if declared_frames > max_physical_frames:
                    return False
                payload = source.readframes(declared_frames)
                return len(payload) == declared_frames * frame_size
        except (OSError, EOFError, wave.Error):
            return False

    @staticmethod
    def normalize_wav_header(path: str | Path) -> bool:
        """Rewrite a PCM WAV header from the data physically present on disk.

        DashScope's downloaded WAVs can use an unknown-length placeholder in
        their header.  Rewriting only the container preserves the synthesized
        PCM while making duration and ALSA playback correct.
        """
        candidate = Path(path)
        try:
            with wave.open(str(candidate), "rb") as source:
                if source.getcomptype() != "NONE":
                    return False
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                frame_size = channels * sample_width
                if frame_size <= 0 or sample_rate <= 0:
                    return False
                max_physical_frames = candidate.stat().st_size // frame_size
                payload = source.readframes(
                    min(source.getnframes(), max_physical_frames)
                )
            if not payload or len(payload) % frame_size:
                return False
            actual_frames = len(payload) // frame_size
            # A correct header needs no write, which also avoids needless I/O.
            with wave.open(str(candidate), "rb") as source:
                if source.getnframes() == actual_frames:
                    return True
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{candidate.stem}.", suffix=".repair.wav", dir=candidate.parent
            )
            os.close(fd)
            try:
                with wave.open(temporary_name, "wb") as target:
                    target.setnchannels(channels)
                    target.setsampwidth(sample_width)
                    target.setframerate(sample_rate)
                    target.writeframes(payload)
                os.replace(temporary_name, candidate)
            finally:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
            return True
        except (OSError, EOFError, wave.Error):
            return False

    def inspect_manifest(self, voice_id: str | None = None) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        ready = 0
        missing = 0
        corrupt = 0
        active_voice = str(voice_id or self.voice_id)
        for entry in self.entries:
            path = self.resolve_path(entry.text, active_voice)
            if not path.exists():
                status = "missing"
                missing += 1
            elif self.is_valid(path):
                status = "ready"
                ready += 1
            else:
                status = "corrupt"
                corrupt += 1
            items.append(
                {
                    "id": entry.entry_id,
                    "text": entry.text,
                    "path": str(path),
                    "status": status,
                }
            )
        counts = {
            "total": len(items),
            "ready": ready,
            "missing": missing,
            "corrupt": corrupt,
        }
        return {
            "ok": bool(items) and missing == 0 and corrupt == 0,
            "voice_id": active_voice,
            "counts": counts,
            "items": items,
        }
