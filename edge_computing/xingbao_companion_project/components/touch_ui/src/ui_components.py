"""星宝 V5 组件库 — GlassPanel, TechButton, GameTile, ShapeOptionCard,
ColorOptionCard, FeedbackPanel, DataCard, EnergyBar.

All layouts respect strict icon/label separation.
"""

import math, os
from functools import lru_cache
from pathlib import Path

import pygame

from . import theme
from .effects import (
    draw_glow_circle, draw_glow_rect, draw_soft_shadow,
    draw_energy_orb, draw_scan_sweep,
)


# ── font system ────────────────────────────────────────────────

# Use the user-selected font for every Pygame-rendered UI label. System fonts
# remain available only as a fallback when the file is unavailable.
UI_FONT_FILE = Path.home() / "fonts" / "2.ttf"
# Keep the selected UI font as the primary face. Pygame has no automatic
# fallback, so supply CJK and symbol faces explicitly for missing glyphs.
CJK_FALLBACK_FONT_FILE = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
SYMBOL_FALLBACK_FONT_FILE = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
# A modest global enlargement keeps touch-distance labels readable at the
# board's 1280×720 display. Small text gets a legibility floor and a slightly
# stronger weight without changing individual screen layouts.
UI_FONT_SCALE = 1.24
UI_MIN_RENDER_SIZE = 15

SYSTEM_FONT_DIRS = [
    Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
    Path("/usr/share/fonts/opentype/noto"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/truetype/wqy"),
    Path("/usr/share/fonts/truetype/arphic"),
    Path("/usr/local/share/fonts"),
]

FONT_FILES = {
    False: ["msyh.ttc", "NotoSansSC-VF.ttf", "NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf",
            "simhei.ttf", "simsun.ttc", "Deng.ttf", "wqy-zenhei.ttc"],
    True:  ["msyhbd.ttc", "NotoSansSC-VF.ttf", "NotoSansCJK-Bold.ttc", "NotoSansCJKsc-Bold.otf",
            "simhei.ttf", "Dengb.ttf", "wqy-zenhei.ttc"],
}

@lru_cache(maxsize=2)
def find_chinese_font_file(bold=False):
    if UI_FONT_FILE.is_file():
        return UI_FONT_FILE
    for name in FONT_FILES[bool(bold)] + FONT_FILES[False]:
        for d in SYSTEM_FONT_DIRS:
            if (d / name).exists():
                return d / name
    return None

_FONT_CACHE = {}
_FONT_DISP = None


class _FallbackFont:
    """Font proxy that preserves the chosen font except for missing glyphs.

    Pygame does not perform font fallback itself.  This selected font uses the
    same tofu glyph for unavailable symbols such as ``✓`` and ``●``.  Keeping
    fallback at the font boundary fixes those symbols (and ASCII ``~``) in
    labels, wrapped text, sizing and game UI without replacing the Chinese
    primary font.
    """

    def __init__(self, primary, fallbacks):
        self._primary = primary
        self._fonts = (primary, *fallbacks)
        self._missing_metrics = [font.metrics("\ufffd")[0] for font in self._fonts]
        self._font_cache = {}

    def _font_index_for(self, character):
        cached = self._font_cache.get(character)
        if cached is not None:
            return cached
        for index, font in enumerate(self._fonts):
            try:
                metric = font.metrics(character)[0]
            except (IndexError, TypeError):
                metric = None
            if metric is not None and metric != self._missing_metrics[index]:
                self._font_cache[character] = index
                return index
        # Preserve the character even if no installed font supports it.
        self._font_cache[character] = 0
        return 0

    def render(self, text, antialias, color, background=None):
        value = str(text)
        if all(self._font_index_for(character) == 0 for character in value):
            return self._primary.render(value, antialias, color, background)

        segments = []
        current = []
        font_index = None
        for character in value:
            character_font_index = self._font_index_for(character)
            if current and character_font_index != font_index:
                segments.append(("".join(current), font_index))
                current = []
            current.append(character)
            font_index = character_font_index
        if current:
            segments.append(("".join(current), font_index))
        pieces = [
            self._fonts[index].render(
                segment, antialias, color, background
            )
            for segment, index in segments
        ]

        width = sum(piece.get_width() for piece in pieces)
        height = max(piece.get_height() for piece in pieces)
        flags = pygame.SRCALPHA if background is None else 0
        combined = pygame.Surface((max(1, width), max(1, height)), flags)
        if background is not None:
            combined.fill(background)
        x = 0
        for piece in pieces:
            combined.blit(piece, (x, (height - piece.get_height()) // 2))
            x += piece.get_width()
        return combined

    def size(self, text):
        value = str(text)
        if all(self._font_index_for(character) == 0 for character in value):
            return self._primary.size(value)
        rendered = self.render(value, True, (255, 255, 255))
        return rendered.get_size()

    def __getattr__(self, name):
        return getattr(self._primary, name)

def get_font(size, bold=False):
    global _FONT_DISP
    if not pygame.font.get_init():
        pygame.font.init(); _FONT_CACHE.clear()
    srf = pygame.display.get_surface()
    if srf is not _FONT_DISP:
        _FONT_CACHE.clear(); _FONT_DISP = srf
    render_size = max(UI_MIN_RENDER_SIZE, round(float(size) * UI_FONT_SCALE))
    ff = find_chinese_font_file(bold=bold)
    fallback_files = tuple(
        path for path in (CJK_FALLBACK_FONT_FILE, SYMBOL_FALLBACK_FONT_FILE)
        if path.is_file()
    )
    key = (render_size, False, str(ff) if ff else None, tuple(map(str, fallback_files)))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    if ff:
        f = pygame.font.Font(str(ff), render_size)
        f.set_bold(False)
        fallbacks = []
        for fallback_file in fallback_files:
            fallback = pygame.font.Font(str(fallback_file), render_size)
            # Match the primary line height so fallback symbols do not make
            # surrounding text jump vertically.
            fallback_size = max(
                1,
                round(render_size * f.get_height() / max(1, fallback.get_height())),
            )
            if fallback_size != render_size:
                fallback = pygame.font.Font(str(fallback_file), fallback_size)
            fallbacks.append(fallback)
        if fallbacks:
            f = _FallbackFont(f, fallbacks)
        _FONT_CACHE[key] = f; return f
    for n in ("Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "Arial Unicode MS", None):
        try:
            f = pygame.font.SysFont(n, render_size, bold=False)
            if f: _FONT_CACHE[key] = f; return f
        except Exception: continue
    f = pygame.font.Font(None, render_size)
    _FONT_CACHE[key] = f; return f

def fit_font(text, max_size, max_width, bold=False, min_size=14):
    size = int(max_size)
    while size > min_size and get_font(size, bold).size(str(text))[0] > max_width:
        size -= 2
    return get_font(size, bold)


# ── helpers ────────────────────────────────────────────────────

def _rgba(color, default_alpha=215):
    return tuple(color[:3]) + ((color[3] if len(color) > 3 else default_alpha),)


def blit_cover(surface, image, rect):
    """Scale and center-crop an image so the destination is fully covered."""
    rect = pygame.Rect(rect)
    if image is None or rect.width <= 0 or rect.height <= 0:
        return None
    scale = max(rect.width / image.get_width(), rect.height / image.get_height())
    size = (max(1, round(image.get_width() * scale)),
            max(1, round(image.get_height() * scale)))
    scaled = pygame.transform.smoothscale(image, size)
    crop = pygame.Rect((scaled.get_width() - rect.width) // 2,
                       (scaled.get_height() - rect.height) // 2,
                       rect.width, rect.height)
    surface.blit(scaled, rect, crop)
    return rect


def blit_contain(surface, image, rect, padding=0):
    """Scale an image into a destination while preserving its aspect ratio."""
    rect = pygame.Rect(rect).inflate(-padding * 2, -padding * 2)
    if image is None or rect.width <= 0 or rect.height <= 0:
        return None
    scale = min(rect.width / image.get_width(), rect.height / image.get_height())
    size = (max(1, round(image.get_width() * scale)),
            max(1, round(image.get_height() * scale)))
    scaled = pygame.transform.smoothscale(image, size)
    target = scaled.get_rect(center=rect.center)
    surface.blit(scaled, target)
    return target


def draw_character_image(surface, image, rect):
    """Render a transparent character sprite without leaving its region."""
    return blit_contain(surface, image, rect)


def draw_image_layer(surface, image, rect, mode="cover", alpha=255, padding=0):
    rect = pygame.Rect(rect)
    if image is None or rect.width <= 0 or rect.height <= 0:
        return None
    target_surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    if mode == "contain":
        blit_contain(target_surface, image, target_surface.get_rect(), padding=padding)
    else:
        blit_cover(target_surface, image, target_surface.get_rect())
    if alpha < 255:
        target_surface.set_alpha(max(0, min(255, int(alpha))))
    surface.blit(target_surface, rect.topleft)
    return rect


# ── basic draws ────────────────────────────────────────────────

def draw_panel(surface, rect, fill=theme.PANEL_BG, border=theme.BORDER_DIM,
               radius=8, shadow=True, glow=5):
    """Legacy glass panel — delegates to draw_glass_panel."""
    from .effects import draw_glass_panel
    r = pygame.Rect(rect)
    draw_glass_panel(surface, r, border=border, radius=radius, glow=glow, fill=fill)

def draw_text(surface, text, pos, size=34, color=theme.TEXT_MAIN, bold=False, center=False):
    rendered = get_font(size, bold=bold).render(str(text), True, tuple(color[:3]))
    r = rendered.get_rect()
    if center: r.center = pos
    else: r.topleft = pos
    surface.blit(rendered, r)
    return r

def wrap_text(text, font, max_width):
    lines = []; line = ""
    for ch in str(text):
        c = line + ch
        if line and font.size(c)[0] > max_width:
            lines.append(line); line = ch
        else: line = c
    if line: lines.append(line)
    return lines or [""]

def draw_wrapped_text(surface, text, rect, size=30, color=theme.TEXT_MAIN,
                      line_gap=6, bold=False, align="left", valign="top", max_lines=None):
    r = pygame.Rect(rect)
    f = get_font(size, bold=bold)
    lines = wrap_text(text, f, r.width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and f.size(last + "…")[0] > r.width: last = last[:-1]
        lines[-1] = last + "…"
    lh = f.get_linesize()
    th = len(lines) * lh + max(0, len(lines) - 1) * line_gap
    y = r.y if valign == "top" else r.centery - th // 2
    drawn = []
    for line in lines:
        rd = f.render(line, True, tuple(color[:3]))
        if align == "center": x = r.centerx - rd.get_width() // 2
        elif align == "right": x = r.right - rd.get_width()
        else: x = r.x
        drawn.append(surface.blit(rd, (x, y)))
        y += lh + line_gap
        if y > r.bottom: break
    return drawn


# ═══════════════════════════════════════════════════════════════
#  SHAPE DRAWING (strict bounding-box constrained)
# ═══════════════════════════════════════════════════════════════

SHAPE_SCALES = {
    "circle":   0.28,
    "square":   0.52,
    "triangle": 0.34,
    "star":     0.32,
    "heart":    0.28,
    "rectangle": 0.30,
    "ellipse": 0.30,
}

def draw_shape_icon(surface, shape_id, icon_rect, color, glow=True):
    """Draw one shape strictly within icon_rect.  ZERO overflow guarantee."""
    ir = pygame.Rect(icon_rect)
    m = max(4, min(ir.w, ir.h) // 12)
    inner = ir.inflate(-m * 2, -m * 2)
    cx, cy = inner.center
    scale = SHAPE_SCALES.get(shape_id, 0.30)
    base = min(inner.w, inner.h) * scale
    r = max(10, int(base))
    lw = max(2, r // 7)

    if glow:
        draw_glow_circle(surface, (cx, cy), max(4, r - 2), color, glow=6)

    if shape_id == "circle":
        pygame.draw.circle(surface, color, (cx, cy), r, width=lw)

    elif shape_id == "triangle":
        h = int(r * 1.55)
        hw = int(r * 1.35)
        pts = [(cx, cy - h // 2), (cx - hw, cy + h // 2), (cx + hw, cy + h // 2)]
        pygame.draw.polygon(surface, color, pts, width=lw)

    elif shape_id == "square":
        side = int(r * 1.35)
        half = side // 2
        sq = pygame.Rect(cx - half, cy - half, side, side)
        pygame.draw.rect(surface, color, sq, width=lw, border_radius=max(2, r // 5))

    elif shape_id == "rectangle":
        shape_rect = pygame.Rect(cx - int(r * 1.35), cy - int(r * 0.72),
                                 int(r * 2.7), int(r * 1.44))
        pygame.draw.rect(surface, color, shape_rect, width=lw,
                         border_radius=max(2, r // 5))

    elif shape_id == "ellipse":
        shape_rect = pygame.Rect(cx - int(r * 1.35), cy - int(r * 0.82),
                                 int(r * 2.7), int(r * 1.64))
        pygame.draw.ellipse(surface, color, shape_rect, width=lw)

    elif shape_id == "heart":
        # Heart drawn on a temp surface, then blitted centered
        hs = r * 3
        hsrf = pygame.Surface((hs, hs), pygame.SRCALPHA)
        hc = (hs // 2, hs // 2)
        lobe_r = int(r * 0.62)
        l_lobe = (hc[0] - int(r * 0.72), hc[1] - int(r * 0.18))
        r_lobe = (hc[0] + int(r * 0.72), hc[1] - int(r * 0.18))
        pygame.draw.circle(hsrf, color, l_lobe, lobe_r)
        pygame.draw.circle(hsrf, color, r_lobe, lobe_r)
        tri = [(hc[0] - int(r * 1.30), hc[1] + int(r * 0.10)),
               (hc[0] + int(r * 1.30), hc[1] + int(r * 0.10)),
               (hc[0], hc[1] + int(r * 1.30))]
        pygame.draw.polygon(hsrf, color, tri)
        # outlines
        pygame.draw.circle(hsrf, color, l_lobe, lobe_r, width=lw)
        pygame.draw.circle(hsrf, color, r_lobe, lobe_r, width=lw)
        pygame.draw.polygon(hsrf, color, tri, width=lw)
        surface.blit(hsrf, (cx - hs // 2, cy - hs // 2))

    elif shape_id == "star":
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            pr = r if i % 2 == 0 else int(r * 0.42)
            pts.append((cx + int(math.cos(a) * pr), cy + int(math.sin(a) * pr)))
        pygame.draw.polygon(surface, color, pts, width=lw)

    else:  # diamond fallback
        h = r
        pts = [(cx, cy - h), (cx + h, cy), (cx, cy + h), (cx - h, cy)]
        pygame.draw.polygon(surface, color, pts, width=lw)


# Legacy alias
def draw_shape(surface, rect, shape_id, color):
    draw_shape_icon(surface, shape_id, rect, color)


def draw_game_icon(surface, rect, icon_type):
    """GameTile icon — constrained within rect."""
    rect = pygame.Rect(rect)
    m = max(4, min(rect.w, rect.h) // 8)
    inner = rect.inflate(-m, -m)
    if icon_type == "color":
        colors = (theme.SOFT_RED, theme.STAR_GOLD, theme.ELECTRIC, theme.SUCCESS)
        mr = min(inner.w // 9, inner.h // 3)
        r = max(8, mr)
        gap = r * 2 + 8
        start_x = inner.centerx - gap * 3 // 2
        for idx, clr in enumerate(colors):
            c = (start_x + idx * gap, inner.centery)
            draw_glow_circle(surface, c, r, clr, glow=5)
            pygame.draw.circle(surface, clr, c, r)
            pygame.draw.circle(surface, theme.TEXT_MAIN, c, r, width=1)
    elif icon_type == "shape":
        for idx, (sid, clr) in enumerate(zip(
            ("circle", "triangle", "square"),
            (theme.ELECTRIC, theme.STAR_GOLD, theme.SUCCESS))):
            sr = pygame.Rect(inner.x + idx * inner.w // 3, inner.y, inner.w // 3, inner.h)
            draw_shape_icon(surface, sid, sr, clr)
    elif icon_type == "counting":
        dot_r = max(5, inner.h // 10)
        for index in range(5):
            x = inner.centerx + (index - 2) * dot_r * 3
            y = inner.centery + (index % 2) * dot_r - dot_r // 2
            draw_glow_circle(surface, (x, y), dot_r, theme.STAR_GOLD, glow=5)
            pygame.draw.circle(surface, theme.STAR_GOLD, (x, y), dot_r)
    elif icon_type == "habit":
        cx, cy = inner.center
        rr = max(16, min(inner.w, inner.h) // 4)
        draw_glow_circle(surface, (cx, cy), rr, theme.SUCCESS, glow=6)
        pygame.draw.circle(surface, theme.SUCCESS, (cx, cy), rr, width=max(3, rr // 5))
        pygame.draw.line(surface, theme.TEXT_MAIN, (cx - rr // 2, cy),
                         (cx - rr // 8, cy + rr // 3), width=max(3, rr // 6))
        pygame.draw.line(surface, theme.TEXT_MAIN, (cx - rr // 8, cy + rr // 3),
                         (cx + rr // 2, cy - rr // 3), width=max(3, rr // 6))
    elif icon_type == "english":
        draw_text(surface, "A", (inner.centerx - inner.w // 7, inner.centery),
                  size=max(24, inner.h // 2), color=theme.CRYSTAL, bold=True, center=True)
        draw_text(surface, "中", (inner.centerx + inner.w // 7, inner.centery),
                  size=max(20, inner.h // 3), color=theme.STAR_GOLD, bold=True, center=True)
    elif icon_type == "skill":
        cx, cy = inner.center
        rr = max(14, min(inner.w, inner.h) // 4)
        for radius in (rr, max(5, rr // 2)):
            pygame.draw.circle(surface, theme.CRYSTAL, (cx, cy), radius,
                               width=max(2, rr // 7))
        pygame.draw.line(surface, theme.STAR_GOLD, (cx, cy + rr),
                         (cx, cy - rr - rr // 2), width=max(3, rr // 6))
        pygame.draw.polygon(surface, theme.STAR_GOLD,
                            [(cx, cy - rr - rr // 2), (cx - rr // 3, cy - rr),
                             (cx + rr // 3, cy - rr)])
    else:  # memory
        pts = [(int(inner.x + inner.w * x), int(inner.y + inner.h * y))
               for x, y in ((0.25, 0.3), (0.75, 0.3), (0.25, 0.72), (0.75, 0.72))]
        for a, b in ((0, 1), (0, 2), (1, 3), (2, 3)):
            pygame.draw.line(surface, _alpha(theme.ELECTRIC, 50), pts[a], pts[b], width=2)
        dot_r = max(5, inner.h // 13)
        for idx, c in enumerate(pts):
            clr = theme.STAR_GOLD if idx < 3 else theme.ELECTRIC
            draw_glow_circle(surface, c, dot_r, clr, glow=5)
            pygame.draw.circle(surface, clr, c, dot_r)

def _alpha(c, a):
    return tuple(c[:3]) + (max(0, min(255, int(a))),)


def draw_arcade_button(surface, rect, pressed=False, hovered=False):
    """Draw the warm, chunky game-button treatment used by the home screen."""
    r = pygame.Rect(rect)
    if r.width < 8 or r.height < 8:
        return r
    if pressed:
        r = r.inflate(-4, -4)
        r.y += 3
    radius = max(8, min(r.width, r.height) // 5)
    pygame.draw.rect(surface, (104, 53, 36), r, border_radius=radius)
    rim = r.inflate(-max(3, r.width // 38) * 2, -max(3, r.height // 13) * 2)
    pygame.draw.rect(surface, (158, 82, 48), rim, border_radius=max(6, radius - 3))
    pygame.draw.rect(surface, (213, 131, 60), rim, width=max(2, r.height // 26),
                     border_radius=max(6, radius - 3))
    face = rim.inflate(-max(5, r.width // 20) * 2, -max(5, r.height // 7) * 2)
    pygame.draw.rect(surface, (255, 192, 82), face, border_radius=max(5, radius - 7))
    inner = face.inflate(-max(2, r.width // 55) * 2, -max(2, r.height // 18) * 2)
    pygame.draw.rect(surface, (255, 211, 112), inner, border_radius=max(4, radius - 10))
    pygame.draw.rect(surface, (193, 111, 43), face, width=max(1, r.height // 32),
                     border_radius=max(5, radius - 7))
    highlight = pygame.Rect(inner.x + inner.width // 12, inner.y + max(2, inner.height // 11),
                            inner.width * 5 // 6, max(2, inner.height // 8))
    pygame.draw.rect(surface, (255, 231, 157), highlight,
                     border_radius=max(2, highlight.height // 2))
    if r.width > 80:
        band_w = max(4, r.width // 42)
        for x in (r.x + band_w * 2, r.right - band_w * 3):
            pygame.draw.rect(surface, (125, 62, 39),
                             pygame.Rect(x, r.y + r.height // 5, band_w, r.height * 3 // 5),
                             border_radius=band_w // 2)
    if hovered and not pressed:
        pygame.draw.rect(surface, (255, 244, 194), inner, width=max(1, r.height // 36),
                         border_radius=max(4, radius - 10))
    return r


def draw_arcade_text(surface, text, font, center, color=(255, 250, 224)):
    shadow = font.render(str(text), True, (122, 70, 30))
    foreground = font.render(str(text), True, color)
    shadow_rect = shadow.get_rect(center=(center[0] + 2, center[1] + 2))
    surface.blit(shadow, shadow_rect)
    rect = foreground.get_rect(center=center)
    surface.blit(foreground, rect)
    return rect


# ═══════════════════════════════════════════════════════════════
#  COMPONENTS
# ═══════════════════════════════════════════════════════════════

class Button:
    """Basic touch button with hover/press/selected states."""
    def __init__(self, rect, text, bg=theme.PANEL_GLASS, fg=theme.TEXT_MAIN,
                 event_key=None, subtitle=None, border=None,
                 image=None, active_image=None, arcade_style=False):
        self.rect = pygame.Rect(rect)
        self.text = text; self.bg = bg; self.fg = fg
        self.event_key = event_key or text
        self.subtitle = subtitle
        self.border = border or theme.ELECTRIC
        self.image = image
        self.active_image = active_image
        self.arcade_style = arcade_style
        self.hovered = False; self.pressed = False; self.selected = False
        self.title_rect = pygame.Rect(0, 0, 0, 0)
        self.subtitle_rect = pygame.Rect(0, 0, 0, 0)

    def contains(self, pos):
        return self.rect.collidepoint(pos)

    def _sync_pointer_state(self):
        if pygame.display.get_surface() is None: return
        mp = pygame.mouse.get_pos()
        self.hovered = self.hovered or self.rect.collidepoint(mp)
        self.pressed = self.pressed or (self.hovered and bool(pygame.mouse.get_pressed()[0]))

    def draw(self, surface, font=None):
        self._sync_pointer_state()
        if self.arcade_style:
            r = draw_arcade_button(surface, self.rect, pressed=self.pressed, hovered=self.hovered)
            ts = font.get_height() if font else 30
            tf = fit_font(self.text, ts, r.width - 30, bold=True)
            if self.subtitle:
                title = tf.render(self.text, True, (116, 65, 25))
                sf = fit_font(self.subtitle, max(14, ts - 9), r.width - 30)
                subtitle = sf.render(self.subtitle, True, (139, 82, 31))
                gap = max(4, min(12, int(r.h * 0.05)))
                top = r.centery - (title.get_height() + gap + subtitle.get_height()) // 2
                self.title_rect = title.get_rect(midtop=(r.centerx, top))
                self.subtitle_rect = subtitle.get_rect(midtop=(r.centerx, self.title_rect.bottom + gap))
                surface.blit(title, self.title_rect)
                surface.blit(subtitle, self.subtitle_rect)
            else:
                self.title_rect = draw_arcade_text(surface, self.text, tf, r.center)
                self.subtitle_rect = pygame.Rect(0, 0, 0, 0)
            return
        r = self.rect.inflate(-4, -3) if self.pressed else self.rect
        bd = theme.STAR_GOLD if self.selected or self.pressed else self.border
        fa = 235 if self.hovered else 200
        fill = _rgba(self.bg, fa)
        if self.hovered and not self.pressed:
            fill = tuple(min(255, v + 8) for v in fill[:3]) + (fill[3],)
        gw = 9 if self.selected else (7 if self.hovered else 3)
        bg_image = self.active_image if (self.selected or self.pressed or self.hovered) and self.active_image else self.image
        if bg_image is not None:
            draw_image_layer(surface, bg_image, r, alpha=220 if self.hovered else 198)
        draw_glass_panel(surface, r, border=bd, radius=10, glow=gw, fill=fill)
        ts = font.get_height() if font else 30
        tf = fit_font(self.text, ts, r.width - 20, bold=True)
        if self.subtitle:
            s1 = tf.render(self.text, True, tuple(self.fg[:3]))
            sf = fit_font(self.subtitle, max(14, ts - 8), r.width - 20)
            s2 = sf.render(self.subtitle, True, theme.TEXT_SUB)
            gap = max(6, min(16, int(r.h * 0.04)))
            group_height = s1.get_height() + gap + s2.get_height()
            top = r.centery - group_height // 2 + (2 if self.pressed else 0)
            self.title_rect = s1.get_rect(midtop=(r.centerx, top))
            self.subtitle_rect = s2.get_rect(
                midtop=(r.centerx, self.title_rect.bottom + gap))
            surface.blit(s1, self.title_rect)
            surface.blit(s2, self.subtitle_rect)
        else:
            s = tf.render(self.text, True, tuple(self.fg[:3]))
            tr = s.get_rect(center=r.center)
            if self.pressed: tr.y += 2
            self.title_rect = tr
            self.subtitle_rect = pygame.Rect(0, 0, 0, 0)
            surface.blit(s, tr)

# Alias
TechButton = Button


class GameTile(Button):
    """Home-screen game entry — like a sci-fi terminal function module."""
    def __init__(self, rect, index, title, description, bg, event_key, icon_type,
                 image=None, card_image=None, active_card_image=None, difficulty="启蒙"):
        super().__init__(rect, title, bg=bg, fg=theme.TEXT_MAIN,
                         event_key=event_key, subtitle=description,
                         border=theme.ELECTRIC, image=card_image, active_image=active_card_image)
        self.index = index; self.icon_type = icon_type; self.icon_image = image
        self.difficulty = difficulty

    def draw(self, surface, font=None):
        self._sync_pointer_state()
        if self.arcade_style:
            r = draw_arcade_button(surface, self.rect, pressed=self.pressed, hovered=self.hovered)
            pad = max(12, r.w // 12)
            num_font = get_font(max(14, r.height // 10), bold=True)
            num_srf = num_font.render(f"{self.index:02d}", True, (143, 82, 31))
            surface.blit(num_srf, (r.x + pad, r.y + max(8, r.height // 12)))
            icon_h = int(r.h * 0.31)
            icon_r = pygame.Rect(r.x + pad, r.y + r.h // 6, r.w - pad * 2, icon_h)
            if self.icon_image:
                blit_contain(surface, self.icon_image, icon_r, padding=max(2, pad // 4))
            else:
                draw_game_icon(surface, icon_r, self.icon_type)
            title_y = icon_r.bottom + 2
            title_font = fit_font(self.text, max(18, int(r.h * 0.105)), r.w - pad * 2, bold=True)
            title_rect = draw_arcade_text(surface, self.text, title_font, (r.centerx, title_y + title_font.get_height() // 2))
            desc_r = pygame.Rect(r.x + pad, title_rect.bottom + 1, r.w - pad * 2,
                                 r.bottom - title_rect.bottom - max(6, r.h // 14))
            draw_wrapped_text(surface, self.subtitle, desc_r,
                              size=max(13, int(r.h * 0.082)), color=(128, 74, 29),
                              align="center", valign="center", max_lines=2)
            return
        r = self.rect.inflate(-6, -4) if self.pressed else self.rect
        bd = theme.STAR_GOLD if self.selected or self.pressed else theme.ELECTRIC
        gw = 9 if self.selected else (7 if self.hovered else 4)
        bg_image = self.active_image if (self.selected or self.pressed or self.hovered) and self.active_image else self.image
        if bg_image is not None:
            draw_image_layer(surface, bg_image, r, alpha=214 if self.hovered else 190)
        draw_glass_panel(surface, r, border=bd, radius=10, glow=gw, fill=self.bg)

        # Module number (top-left)
        num_font = get_font(max(14, r.height // 10), bold=True)
        num_srf = num_font.render(f"{self.index:02d}", True, _alpha(theme.ELECTRIC, 140))
        surface.blit(num_srf, (r.x + 12, r.y + 8))

        # Status badge (top-right)
        st_font = get_font(max(12, r.height // 14))
        st_srf = st_font.render(self.difficulty, True, theme.SUCCESS)
        st_r = st_srf.get_rect(topright=(r.right - 12, r.y + 10))
        surface.blit(st_srf, st_r)

        # Icon area (center-top)
        pad = max(8, r.w // 12)
        icon_h = int(r.h * 0.38)
        icon_r = pygame.Rect(r.x + pad, r.y + r.h // 6, r.w - pad * 2, icon_h)
        if self.icon_image:
            blit_contain(surface, self.icon_image, icon_r, padding=max(2, pad // 4))
        else:
            draw_game_icon(surface, icon_r, self.icon_type)

        # Title
        title_y = icon_r.bottom + 4
        title_sz = max(24, int(r.h * 0.14))
        title_font = fit_font(self.text, title_sz, r.w - pad * 2, bold=True)
        title_surface = title_font.render(self.text, True, theme.TEXT_MAIN)
        surface.blit(title_surface, title_surface.get_rect(
            midtop=(r.centerx, title_y)))

        # Description
        if self.subtitle:
            desc_y = title_y + title_sz + 4
            desc_r = pygame.Rect(r.x + pad, desc_y, r.w - pad * 2, r.bottom - desc_y - pad)
            draw_wrapped_text(surface, self.subtitle, desc_r,
                              size=max(14, int(r.h * 0.09)), color=theme.TEXT_SUB,
                              align="center", valign="center", max_lines=2)


# Legacy GameCard alias
class GameCard(GameTile):
    def __init__(self, rect, title, description, bg, event_key, icon_type):
        super().__init__(rect, 0, title, description, bg, event_key, icon_type)
    def draw(self, surface, font=None):
        super().draw(surface, font)


class ShapeOptionCard(Button):
    """Shape game option with strict icon/label separation.

    Layout:
      icon_rect  — 58% height, shape drawn ONLY here
      label_rect — 30% height, text ONLY here
      gap        — 12% spacing between them
    """
    def __init__(self, rect, item, event_key, image=None, card_image=None, active_card_image=None):
        super().__init__(rect, item["label"], bg=theme.CARD_BG,
                         fg=theme.TEXT_MAIN, event_key=event_key,
                         border=theme.CRYSTAL, image=card_image, active_image=active_card_image)
        self.shape_id = item["id"]
        self.icon_image = image

    def draw(self, surface, font=None):
        self._sync_pointer_state()
        r = self.rect.inflate(-4, -3) if self.pressed else self.rect
        bd = theme.STAR_GOLD if self.selected or self.pressed else self.border
        gw = 9 if self.selected else (6 if self.hovered else 3)

        bg_image = self.active_image if (self.selected or self.pressed or self.hovered) and self.active_image else self.image
        if bg_image is not None:
            draw_image_layer(surface, bg_image, r, alpha=214 if self.hovered else 188)
        draw_glass_panel(surface, r, border=bd, radius=10, glow=gw, fill=theme.CARD_BG)

        pad = max(12, min(r.w // 18, r.h // 8))
        compact = r.w < 360
        icon_size = max(64, min(82 if compact else 96, r.h - pad * 2))
        self.icon_rect = pygame.Rect(r.x + pad, r.centery - icon_size // 2, icon_size, icon_size)
        if compact and self.shape_id in ("rectangle", "ellipse"):
            wide_width = min(112, int(r.w * 0.38))
            wide_height = min(72, r.h - pad * 2)
            self.icon_rect = pygame.Rect(
                r.x + pad, r.centery - wide_height // 2, wide_width, wide_height)
        label_right = r.right - pad if compact else r.right - pad * 2 - 74
        self.label_rect = pygame.Rect(self.icon_rect.right + pad, r.y + pad + 2,
                                      max(48, label_right - self.icon_rect.right - pad), 38)
        self.sublabel_rect = pygame.Rect(self.label_rect.x, self.label_rect.bottom + 6, self.label_rect.w, 24)
        chip_width, chip_height = ((92, 34) if compact else (74, 28))
        chip_y = r.bottom - pad - chip_height if compact else r.centery - 14
        self.chip_rect = pygame.Rect(
            r.right - pad - chip_width, chip_y, chip_width, chip_height)

        # Shape color
        shape_colors = {
            "circle": theme.ELECTRIC, "triangle": theme.STAR_GOLD,
            "square": theme.SUCCESS, "star": theme.STAR_GOLD,
            "heart": theme.SOFT_RED,
        }
        clr = shape_colors.get(self.shape_id, theme.ELECTRIC)
        if self.icon_image:
            blit_contain(surface, self.icon_image, self.icon_rect, padding=2)
        else:
            draw_shape_icon(surface, self.shape_id, self.icon_rect, clr)

        lf = fit_font(self.text, 30, self.label_rect.w, bold=True)
        rd = lf.render(self.text, True, theme.TEXT_MAIN)
        surface.blit(rd, rd.get_rect(midleft=(self.label_rect.x, self.label_rect.centery)))
        if not compact:
            sublabel = f"{self.shape_id.upper()} SIGNAL"
            sf = fit_font(sublabel, 14, self.sublabel_rect.w)
            sd = sf.render(sublabel, True, theme.TEXT_SUB)
            surface.blit(sd, sd.get_rect(midleft=(self.sublabel_rect.x, self.sublabel_rect.centery)))
        draw_glass_panel(surface, self.chip_rect, border=theme.CRYSTAL, radius=8, glow=3,
                         fill=(25, 58, 90, 185))
        draw_text(surface, "点一下" if compact else "选择", self.chip_rect.center,
                  size=16 if compact else 14,
                  color=theme.TEXT_MAIN, bold=True, center=True)

# Legacy alias
ShapeCard = ShapeOptionCard


class ColorOptionCard(Button):
    """Color game option — energy orb + label, with strict separation."""
    def __init__(self, rect, item, event_key, image=None, card_image=None, active_card_image=None,
                 hover_image=None, selected_image=None, chip_image=None):
        super().__init__(rect, item["label"], bg=theme.CARD_BG,
                         fg=theme.TEXT_MAIN, event_key=event_key,
                         border=item["rgb"], image=card_image, active_image=active_card_image)
        self.color_rgb = item["rgb"]
        self.color_id = item["id"]
        self.orb_image = image
        self.en_label = item.get("en", f"{self.color_id.upper()} ENERGY")
        self.hover_image = hover_image
        self.selected_image = selected_image
        self.chip_image = chip_image

    def draw(self, surface, font=None, t=0.0):
        self._sync_pointer_state()
        r = self.rect.inflate(-4, -3) if self.pressed else self.rect
        bd = theme.STAR_GOLD if self.selected or self.pressed else self.border
        gw = 9 if self.selected else (6 if self.hovered else 3)
        bg_image = self.image
        if self.hovered and self.hover_image is not None:
            bg_image = self.hover_image
        if (self.selected or self.pressed) and self.selected_image is not None:
            bg_image = self.selected_image
        elif (self.selected or self.pressed) and self.active_image is not None:
            bg_image = self.active_image
        if bg_image is not None:
            draw_image_layer(surface, bg_image, r, alpha=214 if self.hovered else 188)
        draw_glass_panel(surface, r, border=bd, radius=10, glow=gw, fill=theme.CARD_BG)

        pad = max(12, min(r.w // 18, r.h // 8))
        compact = r.w < 360
        icon_size = max(64, min(82 if compact else 96, r.h - pad * 2))
        self.icon_rect = pygame.Rect(r.x + pad, r.centery - icon_size // 2, icon_size, icon_size)
        label_right = r.right - pad if compact else r.right - pad * 2 - 74
        self.label_rect = pygame.Rect(self.icon_rect.right + pad, r.y + pad + 2,
                                      max(48, label_right - self.icon_rect.right - pad), 40)
        self.sublabel_rect = pygame.Rect(self.label_rect.x, self.label_rect.bottom + 8, self.label_rect.w, 24)
        chip_width, chip_height = ((92, 34) if compact else (74, 28))
        chip_y = r.bottom - pad - chip_height if compact else r.centery - 14
        self.chip_rect = pygame.Rect(
            r.right - pad - chip_width, chip_y, chip_width, chip_height)

        # Energy orb
        if self.orb_image:
            blit_contain(surface, self.orb_image, self.icon_rect, padding=2)
        else:
            max_r = min(self.icon_rect.w, self.icon_rect.h) // 2 - 4
            orb_r = max(14, int(max_r * 0.70))
            draw_energy_orb(surface, self.icon_rect.center, orb_r, self.color_rgb, t)

        lf = fit_font(self.text, 30, self.label_rect.w, bold=True)
        rd = lf.render(self.text, True, theme.TEXT_MAIN)
        surface.blit(rd, rd.get_rect(midleft=(self.label_rect.x, self.label_rect.centery)))
        if not compact:
            sublabel = self.en_label
            sf = fit_font(sublabel, 14, self.sublabel_rect.w)
            sd = sf.render(sublabel, True, theme.TEXT_SUB)
            surface.blit(sd, sd.get_rect(midleft=(self.sublabel_rect.x, self.sublabel_rect.centery)))
        if self.chip_image is not None:
            draw_image_layer(surface, self.chip_image, self.chip_rect, mode="contain")
        else:
            draw_glass_panel(surface, self.chip_rect, border=self.border, radius=8, glow=3,
                             fill=(25, 58, 90, 185))
            draw_text(surface, "点一下" if compact else "选择", self.chip_rect.center,
                      size=16 if compact else 14,
                      color=theme.TEXT_MAIN, bold=True, center=True)


class FeedbackPanel:
    """Feedback indicator — success / warning / info."""
    STYLES = {
        "success": {"border": theme.SUCCESS, "glow": theme.SUCCESS,
                    "icon": "✓", "fill": (20, 70, 60, 200)},
        "warning": {"border": theme.WARNING, "glow": theme.WARNING,
                    "icon": "!", "fill": (80, 50, 55, 200)},
        "info":    {"border": theme.ELECTRIC, "glow": theme.ELECTRIC,
                    "icon": "●", "fill": (25, 60, 100, 200)},
    }

    def __init__(self, rect, text, success=True, status=None, decoration=None):
        self.rect = pygame.Rect(rect); self.text = text
        self.status = status or ("success" if success else "warning")
        self.decoration = decoration
        self.text_rect = self.rect.inflate(-72, -18)

    def draw(self, surface, font_size=28):
        st = self.STYLES.get(self.status, self.STYLES["info"])
        if self.decoration is not None:
            draw_image_layer(surface, self.decoration, self.rect, alpha=210)
        draw_glass_panel(surface, self.rect, border=st["border"], radius=10, glow=9, fill=st["fill"])
        isz = max(20, font_size - 4)
        ir = get_font(isz, bold=True).render(st["icon"], True, st["glow"])
        ix = self.rect.x + 22
        iy = self.rect.centery - ir.get_height() // 2
        surface.blit(ir, (ix, iy))
        self.text_rect = pygame.Rect(ix + ir.get_width() + 18, self.rect.y + 6,
                                     self.rect.w - ir.get_width() - 50, self.rect.h - 12)
        draw_wrapped_text(surface, self.text, self.text_rect, size=font_size,
                          color=theme.TEXT_MAIN, bold=True, align="center",
                          valign="center", max_lines=3)

# Legacy alias
FeedbackBox = FeedbackPanel


class CompanionPanel:
    """Reusable left companion status panel for home/game/report pages."""

    def __init__(self, rect, title, hint_text, level, energy, energy_max, star_count,
                 level_title="星核稳定", is_max_level=False,
                 avatar_image=None, panel_image=None, chip_labels=None,
                 reward_image=None, status_bar_image=None, chip_images=None,
                 skill_level=0, skill_bonus=0, skill_max_level=20, skill_summary=None):
        self.rect = pygame.Rect(rect)
        self.title = title
        self.hint_text = hint_text
        self.level = level
        self.energy = energy
        self.energy_max = max(1, energy_max)
        self.level_title = level_title
        self.is_max_level = bool(is_max_level)
        self.star_count = star_count
        self.avatar_image = avatar_image
        self.panel_image = panel_image
        self.chip_labels = chip_labels or ("LOCAL", "TOUCH", "SAFE")
        self.reward_image = reward_image
        self.status_bar_image = status_bar_image
        self.chip_images = chip_images or ()
        self.skill_level = max(0, int(skill_level))
        self.skill_bonus = max(0, int(skill_bonus))
        self.skill_max_level = max(1, int(skill_max_level))
        self.skill_summary = skill_summary
        self.avatar_rect = pygame.Rect(rect)
        self.level_rect = pygame.Rect(rect)
        self.energy_rect = pygame.Rect(rect)
        self.hint_rect = pygame.Rect(rect)
        self.status_chip_rects = []
        self.skill_card_rect = pygame.Rect(rect)

    def draw(self, surface):
        if self.panel_image is not None:
            draw_image_layer(surface, self.panel_image, self.rect, alpha=184)
        draw_glass_panel(surface, self.rect, border=theme.ELECTRIC, radius=12, glow=6,
                         fill=(20, 34, 70, 196))
        pad = max(18, min(self.rect.w // 10, self.rect.h // 18))
        draw_text(surface, self.title, (self.rect.x + pad, self.rect.y + pad - 2),
                  size=16, color=theme.CRYSTAL, bold=True)

        avatar_size = min(self.rect.w - pad * 2, int(self.rect.h * 0.33))
        self.avatar_rect = pygame.Rect(self.rect.centerx - avatar_size // 2,
                                       self.rect.y + pad + 28, avatar_size, avatar_size)
        if self.avatar_image is not None:
            draw_character_image(surface, self.avatar_image, self.avatar_rect)
        else:
            draw_glow_circle(surface, self.avatar_rect.center, avatar_size // 3, theme.ELECTRIC, glow=10)

        self.level_rect = pygame.Rect(self.rect.x + pad, self.avatar_rect.bottom + 12,
                                      self.rect.w - pad * 2, 28)
        level_text = f"LV.{self.level} · {self.level_title}"
        level_font = fit_font(level_text, 18, self.level_rect.w, bold=True)
        surface.blit(level_font.render(level_text, True, theme.TEXT_MAIN), self.level_rect.topleft)

        self.energy_rect = pygame.Rect(self.rect.x + pad, self.level_rect.bottom + 16,
                                       self.rect.w - pad * 2, 18)
        value_width = max(62, min(82, int(self.energy_rect.w * 0.28)))
        track_rect = pygame.Rect(
            self.energy_rect.x, self.energy_rect.y,
            self.energy_rect.w - value_width - 8, self.energy_rect.h)
        value_rect = pygame.Rect(
            track_rect.right + 8, self.energy_rect.y - 4,
            value_width, self.energy_rect.h + 8)
        EnergyBar(track_rect, self.energy, self.energy_max, color=theme.ELECTRIC).draw(surface)
        energy_text = "MAX" if self.is_max_level else f"{int(self.energy)}/{int(self.energy_max)}"
        draw_glass_panel(surface, value_rect, border=theme.ELECTRIC, radius=4, glow=2,
                         fill=(8, 24, 52, 235))
        energy_font = fit_font(energy_text, 14, value_rect.w - 8)
        energy_surface = energy_font.render(energy_text, True, theme.TEXT_SUB)
        surface.blit(energy_surface, energy_surface.get_rect(center=value_rect.center))

        star_row = pygame.Rect(self.rect.x + pad, self.energy_rect.bottom + 18,
                               self.rect.w - pad * 2, 24)
        if self.reward_image is not None:
            icon_rect = pygame.Rect(star_row.x, star_row.y - 4, 24, 24)
            draw_image_layer(surface, self.reward_image, icon_rect, mode="contain", alpha=220)
        draw_text(surface, f"累计星星 {self.star_count}", (star_row.x + 32, star_row.y - 2),
                  size=18, color=theme.TEXT_MAIN)

        chip_y = star_row.bottom + 18
        self.skill_card_rect = pygame.Rect(
            self.rect.x + pad, chip_y, self.rect.w - pad * 2, 38)
        self.status_chip_rects = [self.skill_card_rect]
        draw_glass_panel(surface, self.skill_card_rect, border=theme.STAR_GOLD,
                         radius=8, glow=5, fill=(46, 42, 92, 220))
        draw_text(surface, "升级舱", (self.skill_card_rect.x + 12, self.skill_card_rect.y + 10),
                  size=15, color=theme.STAR_GOLD, bold=True, center=False)
        skill_text = self.skill_summary or "LV.{}/{}  星运{}".format(
            self.skill_level, self.skill_max_level, self.skill_bonus)
        sf = fit_font(skill_text, 14, self.skill_card_rect.w // 2, bold=True)
        ss = sf.render(skill_text, True, theme.TEXT_MAIN)
        surface.blit(ss, ss.get_rect(midright=(self.skill_card_rect.right - 10,
                                               self.skill_card_rect.centery)))

        hint_top = self.skill_card_rect.bottom + 12
        self.hint_rect = pygame.Rect(self.rect.x + pad, hint_top, self.rect.w - pad * 2,
                                     max(0, self.rect.bottom - hint_top - pad))
        hint_size = 18
        max_lines = None
        for candidate_size in range(18, 11, -1):
            candidate_font = get_font(candidate_size)
            lines = wrap_text(self.hint_text, candidate_font, self.hint_rect.w)
            required_height = (len(lines) * candidate_font.get_linesize()
                               + max(0, len(lines) - 1) * 4)
            if required_height <= self.hint_rect.h:
                hint_size = candidate_size
                break
        else:
            hint_size = 12
            line_height = get_font(hint_size).get_linesize() + 4
            max_lines = max(1, self.hint_rect.h // max(1, line_height))
        draw_wrapped_text(surface, self.hint_text, self.hint_rect,
                          size=hint_size, color=theme.TEXT_SUB, line_gap=4,
                          align="center", valign="top", max_lines=max_lines)


class DataCard:
    """Small metric card for records/summary pages."""
    def __init__(self, rect, label, value, icon="●", border=None):
        self.rect = pygame.Rect(rect); self.label = label
        self.value = str(value); self.icon = icon
        self.border = border or theme.ELECTRIC

    def draw(self, surface, val_size=34, lab_size=20):
        draw_glass_panel(surface, self.rect, border=self.border, radius=10, glow=5, fill=theme.CARD_BG)
        # Icon
        ic = get_font(val_size).render(self.icon, True, self.border[:3])
        surface.blit(ic, (self.rect.x + 14, self.rect.y + 10))
        # Value
        draw_text(surface, self.value, (self.rect.centerx, self.rect.centery - 4),
                  size=val_size, color=theme.STAR_GOLD, bold=True, center=True)
        # Label
        draw_text(surface, self.label, (self.rect.centerx, self.rect.bottom - 20),
                  size=lab_size, color=theme.TEXT_SUB, center=True)


class EnergyBar:
    """Horizontal energy / progress bar."""
    def __init__(self, rect, value, maximum=100, color=None):
        self.rect = pygame.Rect(rect); self.value = max(0, float(value))
        self.maximum = max(1, float(maximum)); self.color = color or theme.ELECTRIC

    def draw(self, surface):
        r = self.rect
        # Background track
        pygame.draw.rect(surface, theme.SPACE_DEEP, r, border_radius=4)
        # Fill
        p = max(0.0, min(1.0, self.value / self.maximum))
        fw = int(r.w * p)
        if fw > 0:
            fill_r = pygame.Rect(r.x, r.y, fw, r.h)
            pygame.draw.rect(surface, self.color[:3], fill_r, border_radius=4)
            draw_glow_rect(surface, fill_r, self.color, radius=4, glow=4)
        # Rim
        pygame.draw.rect(surface, _alpha(self.color, 90), r, width=1, border_radius=4)


class TechPanel:
    """Legacy summary/records panel — redesigned as DataCard grid."""
    def __init__(self, rect, title, metrics, note=None, border=None,
                 decoration=None, header_icon=None):
        self.rect = pygame.Rect(rect); self.title = title
        self.metrics = list(metrics); self.note = note
        self.border = border or theme.ELECTRIC
        self.decoration = decoration
        self.header_icon = header_icon

    def draw(self, surface, title_size=30, value_size=34, label_size=20):
        if self.decoration is not None:
            draw_image_layer(surface, self.decoration,
                             pygame.Rect(self.rect.x + 12, self.rect.bottom - 86, self.rect.w - 24, 70),
                             mode="contain", alpha=118)
        draw_glass_panel(surface, self.rect, border=self.border, radius=10, glow=7, fill=theme.PANEL_BG)
        pad = 20
        icon_size = 42 if self.header_icon is not None else 0
        tr = pygame.Rect(self.rect.x + pad + icon_size + (10 if icon_size else 0), self.rect.y + 8,
                         self.rect.w - pad * 2 - icon_size, 40)
        if self.header_icon is not None:
            draw_image_layer(surface, self.header_icon,
                             pygame.Rect(self.rect.x + pad, self.rect.y + 8, 42, 42),
                             mode="contain", alpha=220)
        draw_text(surface, self.title, tr.topleft, size=title_size, color=theme.TEXT_MAIN, bold=True)
        # Underline
        pygame.draw.line(surface, _alpha(self.border, 70),
                         (tr.x, tr.bottom + 4), (tr.x + min(120, tr.w // 2), tr.bottom + 4), width=2)
        # Grid
        grid_top = tr.bottom + 14
        nh = 68 if self.note else 10
        gr = pygame.Rect(self.rect.x + pad, grid_top, self.rect.w - pad * 2,
                         self.rect.bottom - grid_top - nh - 8)
        columns = 3 if len(self.metrics) > 4 else 2
        rows = 2
        cw = gr.w // columns
        ch = gr.h // rows
        for column in range(1, columns):
            lx = gr.x + column * cw
            pygame.draw.line(surface, _alpha(self.border, 35),
                             (lx, gr.y + 8), (lx, gr.bottom - 8))
        pygame.draw.line(surface, _alpha(self.border, 35),
                         (gr.x + 8, gr.centery), (gr.right - 8, gr.centery))
        for idx, (label, value) in enumerate(self.metrics[:columns * rows]):
            row, col = divmod(idx, columns)
            cell = pygame.Rect(gr.x + col * cw, gr.y + row * ch, cw, ch)
            draw_text(surface, str(value), (cell.centerx, cell.centery - 6),
                      size=value_size, color=theme.STAR_GOLD, bold=True, center=True)
            draw_text(surface, label, (cell.centerx, cell.bottom - 18),
                      size=label_size, color=theme.TEXT_SUB, center=True)
        if self.note:
            nr = pygame.Rect(self.rect.x + pad, self.rect.bottom - nh + 6,
                             self.rect.w - pad * 2, nh - 18)
            draw_wrapped_text(surface, self.note, nr, size=label_size,
                              color=theme.TEXT_SUB, valign="center", max_lines=2)


class ProgressDots:
    def __init__(self, rect, total, current):
        self.rect = pygame.Rect(rect); self.total = total; self.current = current
    def draw(self, surface):
        r = max(4, min(7, self.rect.h // 3))
        gap = r * 3
        start = self.rect.centerx - (self.total - 1) * gap // 2
        for i in range(self.total):
            c = (start + i * gap, self.rect.centery)
            clr = theme.ELECTRIC if i < self.current else theme.TEXT_MUTED
            if i < self.current: draw_glow_circle(surface, c, r, clr, glow=4)
            pygame.draw.circle(surface, clr, c, r)


class ProgressBar:
    def __init__(self, rect, progress):
        self.rect = pygame.Rect(rect)
        self.progress = max(0.0, min(1.0, float(progress)))
    def draw(self, surface):
        r = self.rect
        pygame.draw.rect(surface, theme.SPACE_DEEP, r, border_radius=4)
        fw = int(r.w * self.progress)
        if fw > 0:
            fr = pygame.Rect(r.x, r.y, fw, r.h)
            pygame.draw.rect(surface, theme.ELECTRIC, fr, border_radius=4)
            draw_glow_rect(surface, fr, theme.ELECTRIC, radius=4, glow=3)


def proportional_rect(width, height, x, y, w, h):
    return int(width * x), int(height * y), int(width * w), int(height * h)

def draw_glass_panel(surface, rect, border=None, radius=10, glow=6, fill=None):
    """Direct glass panel render (used by components)."""
    from .effects import draw_glass_panel as _gp
    _gp(surface, rect, border=border, radius=radius, glow=glow, fill=fill)
