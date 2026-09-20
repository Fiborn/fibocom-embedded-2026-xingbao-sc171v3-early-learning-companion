"""Optional layout rectangle overlay for local debugging."""

from __future__ import annotations

import pygame

from . import theme
from .ui_components import draw_text


def draw_debug_overlay(surface, registry):
    for index, (key, rect) in enumerate(registry.items()):
        color = theme.WARNING if index % 2 else theme.ELECTRIC
        pygame.draw.rect(surface, color[:3], rect, width=1)
        label_rect = pygame.Rect(rect.x + 2, rect.y + 2, min(rect.w - 4, 190), 18)
        if label_rect.w > 20 and label_rect.h > 10:
            overlay = pygame.Surface(label_rect.size, pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 130))
            surface.blit(overlay, label_rect.topleft)
            draw_text(surface, key, label_rect.topleft, size=12, color=color)
