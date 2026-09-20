"""Per-frame registry for real clickable UI rectangles."""

from __future__ import annotations

import pygame


class UIRegistry:
    """Stores the currently rendered page's click targets.

    Rectangles are copied on write and read so callers cannot mutate registry
    state accidentally.
    """

    def __init__(self):
        self.rects = {}

    def register(self, key: str, rect):
        if key and rect is not None:
            self.rects[str(key)] = pygame.Rect(rect).copy()

    def get(self, key: str):
        rect = self.rects.get(str(key))
        return rect.copy() if rect is not None else None

    def clear_page(self):
        self.rects.clear()

    def items(self):
        for key, rect in self.rects.items():
            yield key, rect.copy()
