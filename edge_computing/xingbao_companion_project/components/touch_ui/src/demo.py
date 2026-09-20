"""星宝 V5 演示模式指针 — 发光引导光标 + 点击涟漪。"""

import pygame
from . import theme
from .effects import draw_click_ripple, draw_glow_circle, draw_glow_rect

POINTER_TIP_OFFSET = (12, 8)


def draw_demo_pointer(surface, target_rect, stage, remaining, press_duration,
                      scale=1.0, position=None, image=None):
    """Polished demo pointer.

    stage='move': cyan cursor with trail dots toward target.
    stage='press': yellow target highlight + expanding ripple.
    """
    if stage not in ("move", "press"): return
    target_rect = pygame.Rect(target_rect)
    x, y = position or target_rect.center
    radius = max(12, int(18 * scale))

    if stage == "press":
        progress = 1.0 - max(0.0, float(remaining)) / max(0.001, float(press_duration))
        draw_glow_rect(surface, target_rect.inflate(8, 8), theme.STAR_GOLD,
                        radius=10, glow=max(4, int(8 * scale)))
        draw_click_ripple(surface, (x, y), progress, theme.STAR_GOLD)
        ptr_color = theme.STAR_GOLD
    else:
        ptr_color = theme.ELECTRIC

    if image is not None:
        size = max(44, int(66 * scale))
        iw, ih = image.get_size()
        ratio = min(size / max(1, iw), size / max(1, ih))
        rendered = pygame.transform.smoothscale(
            image, (max(1, int(iw * ratio)), max(1, int(ih * ratio))))
        ox = int(POINTER_TIP_OFFSET[0] * scale)
        oy = int(POINTER_TIP_OFFSET[1] * scale)
        target = rendered.get_rect(topleft=(x - ox, y - oy))
        surface.blit(rendered, target)
        return

    draw_glow_circle(surface, (x, y), radius, ptr_color, glow=max(5, int(10 * scale)))
    pygame.draw.circle(surface, theme.TEXT_MAIN, (x, y), max(2, radius // 3))

    layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    trail = [(x + 28, y + 34), (x + 20, y + 26), (x + 12, y + 16)]
    for idx, pt in enumerate(trail):
        a = 35 + idx * 35
        pygame.draw.circle(layer, (55, 232, 255, a), pt, max(2, radius // 4))

    pts = [
        (x + 14, y + 16),
        (x + 30, y + 32),
        (x + 24, y + 34),
        (x + 12, y + 24),
        (x + 10, y + 20),
    ]
    pygame.draw.polygon(layer, (255, 225, 181, 230), pts)
    surface.blit(layer, (0, 0))
