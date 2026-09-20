"""Runtime asset loader with alias resolution, cropping, caching, and text-PNG
priority fallback (clean → raw → font).

All PNGs load via .convert_alpha() for per-pixel transparency.
Scaled results are cached so nothing is re-loaded per frame.
Missing assets degrade gracefully — never crash.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pygame

from .assets_manifest import ASSETS, ASSET_META
from .text_assets_manifest import TEXT_ASSETS


class AssetLoader:
    """Load and cache UI + text images.  Missing assets degrade gracefully."""

    def __init__(
        self,
        base_path="assets",
        manifest=None,
        manifest_path=None,
        text_root=None,
        text_clean_root=None,
    ):
        self._base = Path(base_path).resolve()
        self._text_root = Path(text_root).resolve() if text_root else self._base / "xingbao_text"
        self._text_clean_root = (
            Path(text_clean_root).resolve()
            if text_clean_root
            else self._base / "xingbao_text_clean"
        )
        self._cache = {}
        self._manifest = dict(ASSETS)
        self._meta = dict(ASSET_META)
        if manifest:
            self._manifest.update(manifest)
        if manifest_path:
            loaded = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            self._manifest.update(loaded)

    # ── path resolution ─────────────────────────────────────────

    def resolve_key(self, key):
        return self._base / self._manifest.get(str(key), str(key))

    # ── raw loader ──────────────────────────────────────────────

    def _load_raw(self, path, alpha=True):
        image = pygame.image.load(str(path))
        return image.convert_alpha() if alpha else image.convert()

    def _apply_meta(self, key, image):
        meta = self._meta.get(str(key), {})
        crop = meta.get("crop")
        if crop:
            left, top, right, bottom = crop
            crop_rect = pygame.Rect(left, top, max(1, right - left), max(1, bottom - top))
            image = image.subsurface(crop_rect).copy()
        if meta.get("remove_dark_background"):
            image = self._remove_dark_background(image)
        return image

    @staticmethod
    def _remove_dark_background(image):
        """Convert a nearly uniform dark atlas background to soft transparency."""
        image = image.copy().convert_alpha()
        background = image.get_at((0, 0))
        br, bg, bb = background.r, background.g, background.b
        width, height = image.get_size()
        for y in range(height):
            for x in range(width):
                color = image.get_at((x, y))
                distance = max(abs(color.r - br), abs(color.g - bg), abs(color.b - bb))
                if distance < 28:
                    alpha = 0
                elif distance < 60:
                    alpha = min(color.a, int((distance - 28) * 255 / 32))
                else:
                    alpha = color.a
                image.set_at((x, y), (color.r, color.g, color.b, alpha))
        return image

    # ── generic image loader ────────────────────────────────────

    def image(self, key, size=None, alpha=True):
        cache_key = (str(key), tuple(size) if size else None, bool(alpha))
        if cache_key in self._cache:
            return self._cache[cache_key]

        path = self.resolve_key(key)
        if not path.exists():
            raise FileNotFoundError("Asset not found: {}".format(path))

        image = self._load_raw(path, alpha=alpha)
        image = self._apply_meta(key, image)
        if size:
            image = pygame.transform.smoothscale(image, tuple(size))
        self._cache[cache_key] = image
        return image

    def optional_image(self, key, size=None, fallback=None, alpha=True):
        try:
            return self.image(key, size=size, alpha=alpha)
        except (FileNotFoundError, pygame.error, ValueError):
            return fallback

    # ── convenience aliases ─────────────────────────────────────

    def load(self, rel_path, size=None, alpha=True):
        """Load an image at a relative path under the UI base."""
        path = self._base / rel_path
        if not path.exists():
            raise FileNotFoundError("Asset not found: {}".format(path))
        return self._load_raw(path, alpha=alpha)

    def load_ui(self, rel_path, size=None):
        """Load a UI image (xingbao_v3)."""
        return self.load(rel_path, size=size, alpha=True)

    def load_text(self, rel_path, size=None):
        """Load a text PNG directly by relative path inside the text root."""
        path = self._text_root / rel_path
        if not path.exists():
            raise FileNotFoundError("Text asset not found: {}".format(path))
        image = self._load_raw(path, alpha=True)
        if size:
            image = pygame.transform.smoothscale(image, tuple(size))
        return image

    def get_ui(self, key, size=None):
        """Get a UI image by manifest key."""
        return self.optional_image(key, size=size, fallback=None)

    def get_text(self, key, size=None):
        """Get a text PNG by manifest key."""
        return self.get_text_asset(key, size=size)

    # ── text PNG (with clean → raw → font fallback) ─────────────

    def get_text_asset(self, key, size=None):
        """Return a text PNG Surface for *key*, or None if unavailable.

        Priority:
          1. assets/xingbao_text_clean/  (transparent-background text)
          2. assets/xingbao_text/        (original split text PNGs)
          3. None → caller must fall back to pygame font rendering
        """
        relative = TEXT_ASSETS.get(str(key))
        if relative is None:
            return None

        cache_key = ("text", str(key), tuple(size) if size else None)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Priority 1: clean (transparent) version
        clean_path = self._text_clean_root / relative
        if clean_path.exists():
            path = clean_path
        else:
            # Priority 2: original text PNG
            path = self._text_root / relative
            if not path.exists():
                return None  # Priority 3: None → font fallback

        try:
            image = self._load_raw(path, alpha=True)
        except pygame.error:
            return None

        if size:
            image = pygame.transform.smoothscale(image, tuple(size))
        self._cache[cache_key] = image
        return image

    @staticmethod
    def is_asset_usable_for_dark_ui(surface):
        """Return False for text PNGs likely to show white/checker backgrounds."""
        if surface is None:
            return False
        w, h = surface.get_size()
        if w <= 0 or h <= 0 or w > 1800 or h > 600:
            return False
        sample = []
        for x in range(0, w, max(1, w // 12)):
            sample.append(surface.get_at((x, 0)))
            sample.append(surface.get_at((x, h - 1)))
        for y in range(0, h, max(1, h // 12)):
            sample.append(surface.get_at((0, y)))
            sample.append(surface.get_at((w - 1, y)))
        opaque_light = 0
        opaque = 0
        for color in sample:
            alpha = color.a if hasattr(color, "a") else color[3]
            if alpha > 220:
                opaque += 1
                if color.r > 210 and color.g > 210 and color.b > 210:
                    opaque_light += 1
        if not sample:
            return False
        return opaque_light / len(sample) < 0.18 and opaque / len(sample) < 0.92

    def draw_text_asset(self, surface, key, rect, mode="contain", alpha=255):
        """Draw a text PNG into *rect* using *mode* (contain/cover).

        Returns the blit rect on success, or None if the asset is missing.
        The caller should fall back to pygame font rendering when None is returned.
        """
        rect = pygame.Rect(rect)
        image = self.get_text_asset(key)
        if image is None or rect.width <= 0 or rect.height <= 0:
            return None
        if mode == "cover":
            return self.draw_cover(surface, image, rect, alpha=alpha)
        scale = min(rect.width / image.get_width(), rect.height / image.get_height())
        size = (
            max(1, round(image.get_width() * scale)),
            max(1, round(image.get_height() * scale)),
        )
        rendered = self.get_text_asset(key, size=size)
        if rendered is None:
            rendered = pygame.transform.smoothscale(image, size)
        target = rendered.get_rect(center=rect.center)
        return self._blit_scaled(surface, rendered, target, alpha=alpha)

    # ── render helpers ──────────────────────────────────────────

    def _blit_scaled(self, surface, image, target, alpha=255):
        if alpha >= 255:
            surface.blit(image, target)
        else:
            rendered = image.copy()
            rendered.set_alpha(max(0, min(255, int(alpha))))
            surface.blit(rendered, target)
        return target

    def draw_contain(self, surface, image, rect, alpha=255):
        """Scale *image* to fit inside *rect* preserving aspect ratio."""
        rect = pygame.Rect(rect)
        if image is None or rect.width <= 0 or rect.height <= 0:
            return None
        scale = min(rect.width / image.get_width(), rect.height / image.get_height())
        size = (
            max(1, round(image.get_width() * scale)),
            max(1, round(image.get_height() * scale)),
        )
        scaled = pygame.transform.smoothscale(image, size)
        target = scaled.get_rect(center=rect.center)
        return self._blit_scaled(surface, scaled, target, alpha=alpha)

    def draw_cover(self, surface, image, rect, alpha=255):
        """Scale *image* to fully cover *rect* (centered crop)."""
        rect = pygame.Rect(rect)
        if image is None or rect.width <= 0 or rect.height <= 0:
            return None
        scale = max(rect.width / image.get_width(), rect.height / image.get_height())
        size = (
            max(1, round(image.get_width() * scale)),
            max(1, round(image.get_height() * scale)),
        )
        scaled = pygame.transform.smoothscale(image, size)
        crop = pygame.Rect(
            (scaled.get_width() - rect.width) // 2,
            (scaled.get_height() - rect.height) // 2,
            rect.width,
            rect.height,
        )
        if alpha >= 255:
            surface.blit(scaled, rect, crop)
        else:
            rendered = scaled.copy()
            rendered.set_alpha(max(0, min(255, int(alpha))))
            surface.blit(rendered, rect, crop)
        return rect

    def draw_center(self, surface, image, center, size=None, alpha=255):
        if image is None:
            return None
        rendered = image if size is None else pygame.transform.smoothscale(image, tuple(size))
        target = rendered.get_rect(center=center)
        return self._blit_scaled(surface, rendered, target, alpha=alpha)

    # ── maintenance ─────────────────────────────────────────────

    def clear_cache(self):
        self._cache.clear()

    def list_assets(self):
        paths = []
        for root, _, files in os.walk(self._base):
            for name in files:
                if name.lower().endswith((".png", ".webp")):
                    full = Path(root) / name
                    paths.append(str(full.relative_to(self._base)).replace("\\", "/"))
        return sorted(paths)
