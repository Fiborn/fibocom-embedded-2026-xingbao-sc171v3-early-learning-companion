"""星宝 V5 — AI 星核伙伴角色。

Visual: glowing core + orbital ring + antenna + expressive eyes + floating animation.
States: normal, happy, thinking, encouraging.
"""

import math, pygame
from . import theme
from .effects import draw_glow_circle
from .ui_components import (
    draw_character_image, draw_wrapped_text, draw_glass_panel, get_font,
)


def _alpha(c, a):
    return tuple(c[:3]) + (max(0, min(255, int(a))),)


def _orbiting_star(surface, center, orbit_r, angle, color):
    x = int(center[0] + math.cos(angle) * orbit_r)
    y = int(center[1] + math.sin(angle) * orbit_r * 0.52)
    draw_glow_circle(surface, (x, y), 4, color, glow=5)
    pygame.draw.circle(surface, color, (x, y), 3)


def mouth_arc_angles(state):
    if state == "happy": return math.pi, math.pi * 2
    return 0, math.pi


def draw_xingbao(surface, rect, state="normal", speech=None, speech_rect=None,
                 font_size=22, t=0.0, level=1, energy=0, energy_max=100,
                 image=None):
    """Draw 星宝 centered in rect. Optionally display level + energy bar below."""
    rect = pygame.Rect(rect)
    if image is not None:
        sprite_rect = rect.inflate(-max(4, rect.w // 16), -max(4, rect.h // 16))
        draw_character_image(surface, image, sprite_rect)
        if level:
            lv_text = f"LV.{level}"
            lf = get_font(max(12, rect.h // 11), bold=True)
            ls = lf.render(lv_text, True, theme.STAR_GOLD)
            lv_pos = (rect.centerx - ls.get_width() // 2, min(rect.bottom - 26, sprite_rect.bottom - 4))
            surface.blit(ls, lv_pos)
            eb_w = max(48, min(rect.w - 36, int(rect.w * 0.56)))
            eb_h = max(4, rect.h // 18)
            eb_r = pygame.Rect(rect.centerx - eb_w // 2, lv_pos[1] + ls.get_height() + 2, eb_w, eb_h)
            pygame.draw.rect(surface, theme.SPACE_DEEP, eb_r, border_radius=2)
            pct = max(0.0, min(1.0, energy / max(1, energy_max)))
            if pct > 0:
                fill_r = pygame.Rect(eb_r.x, eb_r.y, int(eb_r.w * pct), eb_r.h)
                pygame.draw.rect(surface, theme.ELECTRIC, fill_r, border_radius=2)
            pygame.draw.rect(surface, _alpha(theme.ELECTRIC, 70), eb_r, width=1, border_radius=2)
        if speech and speech_rect:
            sr = pygame.Rect(speech_rect)
            draw_glass_panel(surface, sr, border=theme.ELECTRIC, radius=10, glow=7)
            draw_wrapped_text(surface, speech, sr.inflate(-16, -10),
                              size=font_size, color=theme.TEXT_MAIN,
                              align="center", valign="center", max_lines=4)
        return
    fy = int(math.sin(float(t) * theme.FLOAT_SPEED) * 4)
    center = (rect.centerx, rect.centery + fy)
    body_r = max(24, min(rect.w, rect.h) // 3)

    ring_color = theme.STAR_GOLD if state in ("happy", "encouraging") else theme.ELECTRIC

    # ── orbital ellipse (behind) ──
    orb_srf = pygame.Surface((body_r * 3, body_r * 3), pygame.SRCALPHA)
    pygame.draw.ellipse(orb_srf, _alpha(ring_color, 50),
                        pygame.Rect(body_r // 2, body_r // 4, body_r * 2, int(body_r * 2.5)),
                        width=2)
    surface.blit(orb_srf, (center[0] - body_r * 3 // 2, center[1] - body_r * 3 // 2))

    # ── outer glow ──
    draw_glow_circle(surface, center, body_r + 10, ring_color, glow=14 if state == "happy" else 10)

    # ── body sphere (layered for depth) ──
    pygame.draw.circle(surface, theme.SPACE_DEEP, center, body_r + 7)
    layers = [
        (body_r + 1, theme.CRYSTAL),
        (body_r,     (110, 80, 195)),
        (int(body_r * 0.72), (85, 65, 170)),
        (int(body_r * 0.35), (140, 110, 220)),
    ]
    for r, clr in layers:
        pygame.draw.circle(surface, clr, center, r)
    # Rim
    pygame.draw.circle(surface, theme.ELECTRIC, center, body_r, width=3)
    pygame.draw.circle(surface, _alpha((130, 170, 255), 100), center, body_r - 2, width=1)

    # ── antenna ──
    ant_top = (center[0] + int(math.sin(float(t) * 2.0) * 2), center[1] - body_r - 18)
    pygame.draw.line(surface, theme.ELECTRIC, (center[0], center[1] - body_r + 3), ant_top, width=3)
    draw_glow_circle(surface, ant_top, 6, theme.STAR_GOLD, glow=6)
    pygame.draw.circle(surface, theme.STAR_GOLD, ant_top, 5)
    pygame.draw.circle(surface, theme.TEXT_MAIN, (ant_top[0] - 1, ant_top[1] - 2), 2)

    # ── eyes ──
    eye_y = center[1] - body_r // 5
    eye_gap = body_r // 3
    le, re = (center[0] - eye_gap, eye_y), (center[0] + eye_gap, eye_y)

    if state == "encouraging":
        for ex in (le, re):
            pygame.draw.circle(surface, theme.TEXT_MAIN, ex, max(4, body_r // 9))
            sp = (ex[0] - body_r // 14, ex[1] - body_r // 14)
            pygame.draw.circle(surface, theme.WHITE, sp, max(2, body_r // 14))
    elif state == "happy":
        for ex in (le, re):
            arc_r = pygame.Rect(ex[0] - 7, ex[1] - 5, 14, 12)
            pygame.draw.arc(surface, theme.TEXT_MAIN, arc_r,
                           math.pi * 0.15, math.pi * 0.85, width=3)
    elif state == "thinking":
        for ex in (le, re):
            pygame.draw.ellipse(surface, theme.TEXT_MAIN,
                               pygame.Rect(ex[0] - 4, ex[1] - 3, 8, 7))
    else:
        for ex in (le, re):
            pygame.draw.circle(surface, theme.TEXT_MAIN, ex, max(4, body_r // 11))

    # ── blush (happy/encouraging) ──
    if state in ("happy", "encouraging"):
        blush_r = max(3, body_r // 11)
        for dx in (-1, 1):
            bc = (center[0] + dx * body_r // 2, eye_y + body_r // 6)
            bs = pygame.Surface((blush_r * 3, blush_r * 3), pygame.SRCALPHA)
            pygame.draw.circle(bs, _alpha(theme.SOFT_RED, 45),
                              (blush_r * 3 // 2, blush_r * 3 // 2), blush_r)
            surface.blit(bs, (bc[0] - blush_r * 3 // 2, bc[1] - blush_r * 3 // 2))

    # ── mouth ──
    mr = pygame.Rect(center[0] - body_r // 3, center[1] + body_r // 7,
                     body_r * 2 // 3, body_r // 2)
    if state == "thinking":
        pygame.draw.line(surface, theme.TEXT_MAIN, (mr.left, mr.centery),
                         (mr.right, mr.centery), width=3)
        for i in range(3):
            dp = (center[0] + body_r + i * 8, center[1] - body_r + i * 6)
            pygame.draw.circle(surface, theme.TEXT_SUB, dp, 2 + i)
    elif state in ("happy", "encouraging"):
        pygame.draw.arc(surface, theme.TEXT_MAIN, mr, math.pi * 0.05, math.pi * 0.95, width=4)
    else:
        pygame.draw.arc(surface, theme.TEXT_MAIN, mr, math.pi * 0.1, math.pi * 0.9, width=3)

    # ── arms ──
    hy = center[1] + body_r // 4
    if state == "encouraging": lift, aw = -15, 9
    elif state == "happy":     lift, aw = -9, 7
    else:                       lift, aw = 5, 6
    for dx in (-1, 1):
        sx = center[0] + dx * (body_r - 6)
        ex = center[0] + dx * (body_r + 16)
        pygame.draw.line(surface, theme.CRYSTAL, (sx, hy), (ex, hy + lift), width=aw)
        pygame.draw.circle(surface, theme.ELECTRIC, (ex, hy + lift), max(3, aw // 2))

    # ── orbiting companion stars ──
    orb_r = body_r + 18
    for idx, clr in enumerate((theme.ELECTRIC, theme.STAR_GOLD, theme.CRYSTAL)):
        ang = float(t) * (0.25 + idx * 0.06) + idx * math.tau / 3
        _orbiting_star(surface, center, orb_r, ang, clr)
    if state in ("happy", "encouraging"):
        _orbiting_star(surface, center, orb_r + 8, float(t) * -0.35, theme.SUCCESS)

    # ── level & energy display ──
    if level:
        lv_text = f"LV.{level}"
        lf = get_font(max(12, body_r // 4), bold=True)
        ls = lf.render(lv_text, True, theme.STAR_GOLD)
        surface.blit(ls, (center[0] - ls.get_width() // 2, center[1] + body_r + 10))

        # Mini energy bar
        eb_w = max(40, body_r * 2)
        eb_h = max(3, body_r // 10)
        eb_x = center[0] - eb_w // 2
        eb_y = center[1] + body_r + 10 + ls.get_height() + 2
        eb_r = pygame.Rect(eb_x, eb_y, eb_w, eb_h)
        # Track
        pygame.draw.rect(surface, theme.SPACE_DEEP, eb_r, border_radius=2)
        # Fill
        pct = max(0.0, min(1.0, energy / max(1, energy_max)))
        if pct > 0:
            fill_r = pygame.Rect(eb_x, eb_y, int(eb_w * pct), eb_h)
            pygame.draw.rect(surface, theme.ELECTRIC, fill_r, border_radius=2)
        pygame.draw.rect(surface, _alpha(theme.ELECTRIC, 70), eb_r, width=1, border_radius=2)

    # ── speech bubble ──
    if speech and speech_rect:
        sr = pygame.Rect(speech_rect)
        draw_glass_panel(surface, sr, border=theme.ELECTRIC, radius=10, glow=7)
        draw_wrapped_text(surface, speech, sr.inflate(-16, -10),
                          size=font_size, color=theme.TEXT_MAIN,
                          align="center", valign="center", max_lines=4)


def draw_glass_panel(surface, rect, border=None, radius=10, glow=6, fill=None):
    from .effects import draw_glass_panel as _gp
    _gp(surface, rect, border=border, radius=radius, glow=glow, fill=fill)
