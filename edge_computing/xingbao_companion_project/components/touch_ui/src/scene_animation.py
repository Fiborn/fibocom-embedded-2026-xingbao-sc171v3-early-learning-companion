"""GIF scene playback for the Wayland touch desktop's Xingbao portrait."""

from __future__ import annotations

from pathlib import Path

import pygame


def fit_scene_size(width: int, height: int, target_height: int) -> tuple[int, int]:
    """Match the default portrait's height while preserving source aspect ratio."""
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    safe_target_height = max(1, int(target_height))
    return (max(1, round(safe_width * safe_target_height / safe_height)), safe_target_height)


class SceneAnimator:
    """Lazily decode, cache and loop one selected Xingbao GIF scene."""

    def __init__(self, asset_dir: Path) -> None:
        self.asset_dir = Path(asset_dir)
        self.active_scene_id = 0
        self._frames: list[tuple[pygame.Surface, int]] = []
        self._started_at_ms = 0
        self._scaled_frames: dict[tuple[int, int], list[pygame.Surface]] = {}
        self._failed_scene_ids: set[int] = set()

    def set_scene(self, scene_id: int, now_ms: int = 0) -> bool:
        """Select one valid GIF, or clear to the normal desktop animation."""
        if type(scene_id) is not int or not 0 <= scene_id <= 27:
            return False
        if scene_id == 0:
            self.clear_scene()
            return True
        if scene_id == self.active_scene_id and self._frames:
            return True
        frames = self._load_scene(scene_id)
        if not frames:
            self.clear_scene()
            return False
        self.active_scene_id = scene_id
        self._frames = frames
        self._started_at_ms = int(now_ms)
        return True

    def clear_scene(self) -> None:
        self.active_scene_id = 0
        self._frames = []
        self._started_at_ms = 0

    def draw(self, surface: pygame.Surface, rect: pygame.Rect, now_ms: int) -> bool:
        """Draw the current GIF frame centred in ``rect``; false means fallback."""
        if not self._frames or not self.active_scene_id:
            return False
        target_height = max(1, rect.h)
        cache_key = (self.active_scene_id, target_height)
        frames = self._scaled_frames.get(cache_key)
        if frames is None:
            frames = [
                pygame.transform.smoothscale(
                    frame,
                    fit_scene_size(frame.get_width(), frame.get_height(), target_height),
                )
                for frame, _ in self._frames
            ]
            self._scaled_frames[cache_key] = frames
        elapsed = max(0, int(now_ms) - self._started_at_ms)
        total = sum(duration for _, duration in self._frames)
        if total <= 0:
            return False
        offset = elapsed % total
        index = 0
        for frame_index, (_, duration) in enumerate(self._frames):
            if offset < duration:
                index = frame_index
                break
            offset -= duration
        surface.blit(frames[index], frames[index].get_rect(center=rect.center))
        return True

    def _load_scene(self, scene_id: int) -> list[tuple[pygame.Surface, int]]:
        path = self._scene_path(scene_id)
        if path is None:
            self._failed_scene_ids.add(scene_id)
            return []
        try:
            from PIL import Image

            frames: list[tuple[pygame.Surface, int]] = []
            with Image.open(str(path)) as image:
                frame_count = int(getattr(image, "n_frames", 1))
                for index in range(frame_count):
                    image.seek(index)
                    rgba = image.convert("RGBA")
                    frame = pygame.image.fromstring(rgba.tobytes(), rgba.size, "RGBA").convert_alpha()
                    duration = max(20, int(image.info.get("duration") or 100))
                    frames.append((frame, duration))
            return frames
        except Exception:
            self._failed_scene_ids.add(scene_id)
            return []

    def _scene_path(self, scene_id: int) -> Path | None:
        prefix = "{:02d}_".format(scene_id)
        matches = sorted(self.asset_dir.glob(prefix + "*.gif"))
        return matches[0] if len(matches) == 1 else None
