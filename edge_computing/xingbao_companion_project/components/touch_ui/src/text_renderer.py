"""Unified pygame text rendering helpers.

These wrappers keep ordinary Chinese text on the FontManager path and away from
large-area text PNG overlays.
"""

import pygame

from . import theme
from .ui_components import draw_text, draw_wrapped_text, get_font, wrap_text


ROLE_SIZES = {
    "title": 34,
    "button": 24,
    "chip": 14,
    "body": 20,
    "small": 16,
}


def _fit_single_line(text, max_size, max_width, bold=False, min_size=12):
    size = int(max_size)
    while size > min_size and get_font(size, bold=bold).size(str(text))[0] > max_width:
        size -= 1
    font = get_font(size, bold=bold)
    value = str(text)
    if font.size(value)[0] <= max_width:
        return font, value
    suffix = "…"
    while value and font.size(value + suffix)[0] > max_width:
        value = value[:-1]
    return font, value + suffix if value else suffix


def draw_text_in_rect(surface, text, rect, role="body", color=None,
                      align="left", valign="center", max_lines=1, bold=False):
    """Draw text clipped inside rect and return the drawn bounding rect."""
    rect = pygame.Rect(rect)
    color = color or theme.TEXT_MAIN
    if rect.w <= 0 or rect.h <= 0:
        return pygame.Rect(rect)
    old_clip = surface.get_clip()
    surface.set_clip(rect)
    size = ROLE_SIZES.get(role, ROLE_SIZES["body"])
    if max_lines <= 1:
        font, value = _fit_single_line(text, size, rect.w, bold=bold)
        rendered = font.render(value, True, tuple(color[:3]))
        if align == "center":
            x = rect.centerx - rendered.get_width() // 2
        elif align == "right":
            x = rect.right - rendered.get_width()
        else:
            x = rect.x
        if valign == "center":
            y = rect.centery - rendered.get_height() // 2
        elif valign == "bottom":
            y = rect.bottom - rendered.get_height()
        else:
            y = rect.y
        drawn = surface.blit(rendered, (x, y))
    else:
        draw_wrapped_text(surface, text, rect, size=size, color=color, bold=bold,
                          align=align, valign=valign, max_lines=max_lines)
        drawn = rect.copy()
    surface.set_clip(old_clip)
    return drawn.clip(rect)


__all__ = ["draw_text", "draw_wrapped_text", "draw_text_in_rect", "wrap_text"]
