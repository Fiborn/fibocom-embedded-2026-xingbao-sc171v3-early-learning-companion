"""星宝 V5 特效层 — 竞赛级科技感渲染。

All effects use SRCALPHA surfaces, cached where possible.
Designed for SC171V3 performance (60fps target).
"""

import math
import random
from functools import lru_cache

import pygame
from . import theme


# ── helpers ────────────────────────────────────────────────────

def _alpha(color, a):
    return tuple(color[:3]) + (max(0, min(255, int(a))),)


# ═══════════════════════════════════════════════════════════════
#  BACKGROUND
# ═══════════════════════════════════════════════════════════════

@lru_cache(maxsize=4)
def _bg_surface(size):
    """Cached deep-space gradient."""
    w, h = size
    srf = pygame.Surface(size)
    stops = [
        (0.00, theme.SPACE_DEEP),
        (0.28, theme.SPACE_MID),
        (0.55, theme.SPACE_HIGH),
        (0.82, theme.SPACE_MID),
        (1.00, theme.SPACE_DEEP),
    ]
    for y in range(h):
        t = y / max(1, h - 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]; t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0) if t1 != t0 else 0
                clr = tuple(int(c0[c] + (c1[c] - c0[c]) * u) for c in range(3))
                pygame.draw.line(srf, clr, (0, y), (w, y))
                break
        else:
            pygame.draw.line(srf, stops[-1][1], (0, y), (w, y))
    return srf


def draw_space_background(screen, t):
    """Full background: gradient + nebula + aurora."""
    screen.blit(_bg_surface(screen.get_size()), (0, 0))
    w, h = screen.get_size()
    glow = pygame.Surface((w, h), pygame.SRCALPHA)
    ts = float(t) * 0.12

    # Cyan nebula (top-left)
    cx, cy = int(w * (0.22 + math.sin(ts) * 0.04)), int(h * 0.18)
    for i in range(6):
        pygame.draw.circle(glow, _alpha(theme.ELECTRIC, 12 - i * 2),
                           (cx, cy), int(min(w, h) * 0.35) + i * 16)

    # Purple nebula (right)
    cx2, cy2 = int(w * (0.78 + math.cos(ts * 1.3) * 0.05)), int(h * 0.70)
    for i in range(7):
        pygame.draw.circle(glow, _alpha(theme.CRYSTAL, 13 - i * 2),
                           (cx2, cy2), int(min(w, h) * 0.40) + i * 18)

    # Warm accent (bottom)
    for i in range(4):
        pygame.draw.circle(glow, _alpha(theme.WARNING, 9 - i * 2),
                           (int(w * 0.48), int(h * 0.88)),
                           int(min(w, h) * 0.18) + i * 10)

    # Aurora ribbon
    pts = []
    for x in range(0, w, 6):
        y = int(h * 0.52 + math.sin(x * 0.005 + ts * 0.7) * h * 0.10
                + math.sin(x * 0.013 + ts * 1.1) * h * 0.05)
        pts.append((x, y))
    for i in range(4):
        pygame.draw.lines(glow, _alpha(theme.ELECTRIC, 7 - i),
                          False, [(x, y + i * 6) for x, y in pts], width=3)
    screen.blit(glow, (0, 0))


# ═══════════════════════════════════════════════════════════════
#  STARFIELD
# ═══════════════════════════════════════════════════════════════

def init_starfield(width, height, count=110, seed=None):
    rng = random.Random(seed)
    colors = ((220, 240, 255), theme.ELECTRIC[:3], theme.CRYSTAL[:3],
              theme.STAR_GOLD[:3], theme.WARNING[:3])
    return [{
        "x": rng.uniform(0, width), "y": rng.uniform(0, height),
        "r": rng.choice((0.8, 1.0, 1.2, 1.8)),
        "spd": rng.uniform(1.2, 6.0),
        "alpha": rng.randint(55, 175),
        "phase": rng.uniform(0, math.tau),
        "freq": rng.uniform(0.7, 2.2),
        "color": rng.choice(colors),
    } for _ in range(max(0, int(count)))]


def draw_starfield(screen, stars, t):
    w, h = screen.get_size()
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    for s in stars:
        y = (s["y"] + float(t) * s["spd"]) % max(1, h)
        x = (s["x"] + math.sin(float(t) * 0.5 + s["phase"]) * 10) % max(1, w)
        a = s["alpha"] + math.sin(float(t) * s["freq"] + s["phase"]) * 50
        a = max(18, min(200, int(a)))
        rr = max(0.5, s["r"] * (0.7 + 0.3 * math.sin(float(t) * s["freq"])))
        pygame.draw.circle(layer, _alpha(s["color"], a), (int(x), int(y)), max(1, int(rr)))
        if rr >= 1.5:
            pygame.draw.circle(layer, _alpha(s["color"], a // 4),
                              (int(x), int(y)), int(rr + 2))
    screen.blit(layer, (0, 0))


# Alias for compatibility
def init_particles(width, height, count=90, seed=None):
    return init_starfield(width, height, count, seed)

def draw_star_particles(screen, particles, t):
    draw_starfield(screen, particles, t)


# ═══════════════════════════════════════════════════════════════
#  HUD GRID
# ═══════════════════════════════════════════════════════════════

def draw_hud_grid(screen, t):
    w, h = screen.get_size()
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    sp = max(50, int(min(w, h) * 0.10))
    ox = int(float(t) * 2.2) % sp
    oy = int(float(t) * 1.0) % sp
    for x in range(-sp + ox, w + sp, sp):
        pulse = 0.5 + 0.5 * math.sin(float(t) * 0.25 + x * 0.01)
        pygame.draw.line(layer, _alpha(theme.ELECTRIC, int(7 + 5 * pulse)),
                         (x, 0), (x, h), width=1)
    for y in range(-sp + oy, h + sp, sp):
        pygame.draw.line(layer, _alpha(theme.ELECTRIC, int(5 + 3 * math.sin(float(t) * 0.2 + y * 0.008))),
                         (0, y), (w, y), width=1)
    screen.blit(layer, (0, 0))

# Alias
def draw_tech_grid(screen, t):
    draw_hud_grid(screen, t)


# ═══════════════════════════════════════════════════════════════
#  SCAN SWEEP / SCANLINE
# ═══════════════════════════════════════════════════════════════

def draw_scan_sweep(screen, rect, t):
    """Very faint horizontal sweep across a rect."""
    rect = pygame.Rect(rect)
    y = int((float(t) * 40) % max(1, rect.height))
    layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    for row in range(6):
        dist = abs(row - 3) / 3.0
        alpha = int(20 * (1.0 - dist))
        pygame.draw.line(layer, _alpha(theme.ELECTRIC, alpha),
                         (rect.x, rect.y + y + row),
                         (rect.right, rect.y + y + row), width=1)
    screen.blit(layer, (0, 0))


def draw_scanline(screen, t):
    """Full-screen faint scanline."""
    w, h = screen.get_size()
    y = int((float(t) * 18) % max(1, h))
    layer = pygame.Surface((w, 16), pygame.SRCALPHA)
    for row in range(16):
        dist = abs(row - 8) / 8.0
        pygame.draw.line(layer, _alpha(theme.ELECTRIC, int(8 * (1.0 - dist))),
                         (0, row), (w, row))
    screen.blit(layer, (0, y - 8))


# ═══════════════════════════════════════════════════════════════
#  ENERGY ORB
# ═══════════════════════════════════════════════════════════════

def draw_energy_orb(screen, center, radius, color, t):
    """Multi-layer glowing energy sphere."""
    cx, cy = center
    r = max(6, int(radius))
    # Outer glow layers
    for i, (spread, alpha) in enumerate(((r, 8), (r // 2, 16), (r // 4, 32))):
        draw_glow_circle(screen, (cx, cy), r + spread, color, glow=spread // 2)
    # Main orb
    orb = pygame.Surface((r * 3, r * 3), pygame.SRCALPHA)
    oc = (r * 3 // 2, r * 3 // 2)
    pygame.draw.circle(orb, color, oc, r)
    # Inner highlight
    hl_r = max(3, r // 3)
    hl_pos = (oc[0] - r // 3, oc[1] - r // 3)
    pygame.draw.circle(orb, _alpha((255, 255, 255), 70), hl_pos, hl_r)
    # Rim
    pygame.draw.circle(orb, theme.TEXT_MAIN, oc, r, width=max(2, r // 10))
    screen.blit(orb, (cx - r * 3 // 2, cy - r * 3 // 2))


# ═══════════════════════════════════════════════════════════════
#  GLASS PANEL
# ═══════════════════════════════════════════════════════════════

def draw_glass_panel(screen, rect, border=None, radius=10, glow=6, fill=None):
    """Glass-morphism panel with top highlight and soft glow."""
    rect = pygame.Rect(rect)
    border = border or theme.ELECTRIC
    fill = fill or theme.PANEL_GLASS
    # Shadow
    draw_soft_shadow(screen, rect, max(4, glow))
    # Body
    layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(layer, _alpha(fill, fill[3] if len(fill) > 3 else 195),
                     rect, border_radius=radius)
    # Top highlight line
    hl_rect = pygame.Rect(rect.x + 6, rect.y + 2, rect.width - 12, 3)
    pygame.draw.rect(layer, _alpha((255, 255, 255), 25), hl_rect, border_radius=2)
    # Border
    pygame.draw.rect(layer, _alpha(border, 130), rect, width=1, border_radius=radius)
    screen.blit(layer, (0, 0))
    # Glow
    draw_glow_rect(screen, rect, border, radius=radius, glow=glow)


# ═══════════════════════════════════════════════════════════════
#  NEON LINE
# ═══════════════════════════════════════════════════════════════

def draw_neon_line(screen, start, end, color=None, alpha=60):
    color = color or theme.ELECTRIC
    layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    for i in range(3):
        a = alpha - i * 14
        if a <= 0:
            break
        pygame.draw.line(layer, _alpha(color, a), start, end, width=1 + i)
    screen.blit(layer, (0, 0))


# ═══════════════════════════════════════════════════════════════
#  CLICK RIPPLE
# ═══════════════════════════════════════════════════════════════

def draw_click_ripple(screen, pos, progress, color=None):
    """Expanding ring on click/tap."""
    color = color or theme.STAR_GOLD
    p = max(0.0, min(1.0, float(progress)))
    r = int(14 + 38 * p)
    alpha = int(230 * (1.0 - p))
    w = max(1, int(4 * (1.0 - p)))
    pad = r + 6
    layer = pygame.Surface((pad * 2, pad * 2), pygame.SRCALPHA)
    pygame.draw.circle(layer, _alpha(color, alpha), (pad, pad), r, width=w)
    screen.blit(layer, (pos[0] - pad, pos[1] - pad))


# ═══════════════════════════════════════════════════════════════
#  GLOW PRIMITIVES
# ═══════════════════════════════════════════════════════════════

def draw_glow_rect(screen, rect, color, radius=24, glow=8):
    rect = pygame.Rect(rect)
    pad = max(3, int(glow))
    layer = pygame.Surface((rect.w + pad * 2, rect.h + pad * 2), pygame.SRCALPHA)
    local = pygame.Rect(pad, pad, rect.w, rect.h)
    steps = [(pad, 6), (int(pad * 0.7), 14), (int(pad * 0.4), 30), (int(pad * 0.15), 55)]
    for sp, a in steps:
        pygame.draw.rect(layer, _alpha(color, a),
                         local.inflate(sp * 2, sp * 2),
                         width=max(2, sp // 2), border_radius=radius + sp)
    pygame.draw.rect(layer, _alpha(color, 190), local, width=2, border_radius=radius)
    screen.blit(layer, (rect.x - pad, rect.y - pad))


def draw_glow_circle(screen, center, radius, color, glow=12):
    pad = max(3, int(glow))
    size = (radius + pad) * 2
    layer = pygame.Surface((size, size), pygame.SRCALPHA)
    lc = (size // 2, size // 2)
    steps = [(pad, 8), (int(pad * 0.7), 18), (int(pad * 0.4), 38), (int(pad * 0.15), 65)]
    for sp, a in steps:
        pygame.draw.circle(layer, _alpha(color, a), lc, radius + sp)
    pygame.draw.circle(layer, _alpha(color, 210), lc, radius, width=2)
    screen.blit(layer, (center[0] - size // 2, center[1] - size // 2))


def draw_soft_shadow(surface, rect, radius):
    rect = pygame.Rect(rect)
    pad = max(4, int(radius))
    layer = pygame.Surface((rect.w + pad * 2, rect.h + pad * 2), pygame.SRCALPHA)
    loc = pygame.Rect(pad, pad + 4, rect.w, rect.h)
    pygame.draw.rect(layer, theme.PANEL_SHADOW, loc, border_radius=min(24, pad))
    surface.blit(layer, (rect.x - pad, rect.y - pad))


def draw_click_ring(screen, position, progress, color):
    """Legacy alias — use draw_click_ripple."""
    draw_click_ripple(screen, position, progress, color)

# Alias for old gradient background
def draw_gradient_background(screen, t):
    draw_space_background(screen, t)
