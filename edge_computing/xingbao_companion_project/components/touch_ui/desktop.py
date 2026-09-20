"""星宝学习桌面启动器。

主桌面保持轻量，只负责基础交互和启动现有pygame游戏中心。
在SC171V3上可直接全屏运行，实体按键可映射为键盘G键。
"""

import argparse
import base64
import binascii
import io
import math
import os
import random
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pygame

from src.app import XingbaoApp
from src.desktop_services import DesktopStore, battery_status, network_status
from src.desktop_integrations import (
    AgentPreferencesBackend,
    AudioPreferencesBackend,
    ConversationHistoryBackend,
    IntegrationConfig,
    MemoryBackend,
    ParentSummaryBackend,
    VisionStateAdapter,
    load_json_object,
)
from src.font_manager import get_font
from src.board_adapter import runtime as board_runtime
from src.central_speech_client import CentralSpeechClient
from src.scene_animation import SceneAnimator
from src.vision_bridge import VisionProcessBridge
from src.wayland_minimize import minimize_window


ROOT = Path(__file__).resolve().parent
PARENT_LOCK_SECONDS = 60
WEATHER_CITIES = ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "贵阳")
DEFAULT_BACKGROUND = ROOT / "assets" / "desktop" / "xingbao_desktop_clean.png"
LOBSTER_ASSET_DIR = ROOT / "assets" / "desktop" / "lobster"
SCENE_ASSET_DIR = ROOT / "assets" / "scenes"
CAMERA_SNAPSHOT_MAX_BYTES = 1024 * 1024
TRACE_LOG = Path("/tmp/xingbao_desktop_trace.log")
READ_ALOUD_LOG = ROOT / "logs" / "memory-read-aloud.log"
DISPLAY_TIMEZONE = timezone(timedelta(hours=8))
WIDGET_ICON_FILES = {
    "goal": Path("/home/fibo/files/1.png"),
    "reward": Path("/home/fibo/files/2.png"),
    "mood": Path("/home/fibo/files/3.png"),
    "today": Path("/home/fibo/files/4.png"),
    "tasks": Path("/home/fibo/files/5.png"),
    "quick_game": Path("/home/fibo/files/6.png"),
    "quick_focus": Path("/home/fibo/files/7.png"),
    "quick_draw": Path("/home/fibo/files/8.png"),
    "quick_gallery": Path("/home/fibo/files/9.png"),
}
SEARCH_STATUS_ICON_FILE = Path("/home/fibo/icons/search.png")
CAMERA_RECOGNIZE_ICON_FILE = Path("/home/fibo/icons/img_recognize.png")
EMOTION_RECOGNIZE_ICON_FILE = Path("/home/fibo/icons/emotion_recognize.png")
TOP_STATUS_ASSET_DIR = ROOT / "assets" / "desktop" / "top_status"
# These were cut from the supplied desktop wallpaper at its native resolution.
# The wallpaper still provides the scene, while this list lets the status bar be
# painted independently of its old, baked-in values.
TOP_STATUS_ASSET_FILES = {
    "left_divider": ("left_divider.png", (287, 18)),
    "health_icon": ("health_icon.png", (307, 18)),
    "brand": ("brand.png", (726, 14)),
    "wifi": ("wifi.png", (1144, 20)),
    "volume": ("volume.png", (1218, 20)),
    "battery_text": ("battery_text.png", (1290, 24)),
    "battery": ("battery.png", (1348, 20)),
    "lock": ("lock.png", (1430, 18)),
    "parent_icon": ("parent_icon.png", (1514, 18)),
    "parent_text": ("parent_text.png", (1558, 23)),
    "divider": ("divider.png", (1487, 18)),
}
TOP_STATUS_SOURCE_SIZE = (1672, 941)


def _target_fps(env_name, default):
    try:
        value = int(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        value = int(default)
    return max(5, min(30, value))


def format_memory_timestamp(value):
    """Format persisted UTC memory timestamps for the UTC+8 touch display."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(DISPLAY_TIMEZONE).strftime("%-m月%-d日 %H:%M")
    except ValueError:
        return raw[5:16].replace("T", " ")


def format_gallery_date(value):
    """Show artwork timestamps as an UTC+8 calendar date."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(DISPLAY_TIMEZONE).strftime("%Y年%-m月%-d日")
    except ValueError:
        return raw[:10].replace("-", "年", 1).replace("-", "月", 1) + "日"


def trace(message):
    try:
        with TRACE_LOG.open("a", encoding="utf-8") as handle:
            handle.write("{} {}\n".format(datetime.now().isoformat(timespec="seconds"), message))
    except OSError:
        pass


def read_aloud_trace(message):
    """Keep memory-book read-aloud diagnostics in a small, separate log."""
    try:
        READ_ALOUD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with READ_ALOUD_LOG.open("a", encoding="utf-8") as handle:
            handle.write(
                "{} {}\n".format(
                    datetime.now().isoformat(timespec="milliseconds"), message
                )
            )
    except OSError:
        pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="星宝学习桌面")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--window", action="store_true", help="兼容旧命令；正式界面仍保持全屏")
    mode.add_argument("--fullscreen", action="store_true", help="板卡全屏模式")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--low-effects", action="store_true")
    parser.add_argument("--snapshot", action="store_true", help="保存主桌面截图后退出")
    parser.add_argument("--no-central-bridge", action="store_true",
                        help="disable the 127.0.0.1:8765 NDJSON bridge")
    parser.add_argument("--no-game-speech", action="store_true",
                        help="disable game speech_request delivery to central")
    parser.add_argument("--game-speech-host", default="127.0.0.1")
    parser.add_argument("--game-speech-port", type=int, default=8766)
    parser.add_argument("--no-vision", action="store_true", help="disable released vision model")
    parser.add_argument("--camera-source", default="0", help="OpenCV camera index or video path")
    return parser.parse_args(argv)


def font(size, bold=False):
    return get_font(size, bold=bold)


def rounded_panel(surface, rect, fill, border=(164, 108, 62), radius=22, width=3):
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    pygame.draw.rect(surface, border, rect, width=width, border_radius=radius)


def draw_text(surface, text, center, size, color=(91, 55, 31), bold=False):
    image = font(size, bold).render(text, True, color)
    surface.blit(image, image.get_rect(center=center))


def is_loading_status_text(text):
    """Whether a central-tool subtitle should receive the loading sheen."""
    normalized = str(text or "").strip()
    return normalized in {"让我看一看", "正在识别中"} or normalized.startswith("[[SEARCH]] ")


def loading_status_shine_rect(text_rect, size, *, now_ms=None):
    """Return the moving highlight band for a loading subtitle's text bounds."""
    rect = pygame.Rect(text_rect)
    band_width = max(16, int(size * 0.9))
    elapsed_ms = pygame.time.get_ticks() if now_ms is None else int(now_ms)
    progress = (elapsed_ms % 1400) / 1400.0
    left = rect.left + int((rect.width + band_width) * progress) - band_width
    return pygame.Rect(left, rect.top, band_width, rect.height)


def draw_loading_status_text(surface, text, center, size, color=(91, 55, 31), bold=False):
    """Draw a normal subtitle with a clipped left-to-right loading sheen."""
    image = font(size, bold).render(text, True, color)
    text_rect = image.get_rect(center=center)
    surface.blit(image, text_rect)
    highlight_rect = loading_status_shine_rect(text_rect, size)
    if highlight_rect.colliderect(text_rect):
        previous_clip = surface.get_clip()
        surface.set_clip(highlight_rect.clip(text_rect))
        highlight = font(size, bold).render(text, True, (255, 255, 255))
        surface.blit(highlight, text_rect)
        surface.set_clip(previous_clip)
    return highlight_rect


def draw_wrapped_text(
    surface,
    text,
    rect,
    *,
    size,
    color=(91, 55, 31),
    line_gap=2,
    bold=False,
    max_lines=None,
):
    """Draw compact Chinese text using the desktop's known-good font path."""
    target = pygame.Rect(rect)
    selected_font = font(size, bold)
    lines = []
    line = ""
    for character in str(text):
        candidate = line + character
        if line and selected_font.size(candidate)[0] > target.width:
            lines.append(line)
            line = character
        else:
            line = candidate
    if line:
        lines.append(line)
    lines = lines or [""]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        final_line = lines[-1]
        while final_line and selected_font.size(final_line + "…")[0] > target.width:
            final_line = final_line[:-1]
        lines[-1] = final_line + "…"
    y = target.y
    for line_text in lines:
        image = selected_font.render(line_text, True, color)
        surface.blit(image, (target.x, y))
        y += selected_font.get_linesize() + line_gap
        if y > target.bottom:
            break


class DesktopLauncher:
    def __init__(
        self,
        fullscreen=True,
        size=(1280, 720),
        on_speech_request=None,
        low_effects=False,
    ):
        pygame.init()
        flags = pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode((0, 0) if fullscreen else size, flags)
        pygame.display.set_caption("星宝学习桌面")
        self.clock = pygame.time.Clock()
        self.low_effects = bool(low_effects)
        self.target_fps = _target_fps(
            "XINGBAO_UI_FPS",
            7 if self.low_effects else 30,
        )
        self.event_fps = 30
        self.on_speech_request = on_speech_request
        self.fullscreen = fullscreen
        self.running = True
        self.active = False
        self.next_action = None
        self.drawer_open = False
        self.modal = None
        self.notice = ""
        self.notice_until = 0
        self.camera_snapshot_surface = None
        self.camera_snapshot_size = None
        # While a voice session is active, dialogue text owns the single
        # subtitle strip.  Local button/read-aloud hints are intentionally
        # lower priority and must not overwrite it.
        self.dialogue_subtitle_active = False
        self.scene_animator = SceneAnimator(SCENE_ASSET_DIR)
        self.store = DesktopStore(ROOT)
        self.integration_config = IntegrationConfig(ROOT)
        vision_path = self.integration_config.resolve("vision_status_file") or ROOT / "saves" / "vision_status.json"
        memory_path = self.integration_config.resolve("memory_file") or ROOT / "saves" / "xingbao_memory.json"
        history_path = (
            self.integration_config.preferred_shared_path("conversation_history_file")
            or ROOT / "saves" / "conversation_history.json"
        )
        parent_summary_path = (
            self.integration_config.preferred_shared_path("parent_summary_file")
            or ROOT / "saves" / "parent_summaries.json"
        )
        self.companion_memory_path = (
            self.integration_config.preferred_shared_path("companion_memory_file")
            or ROOT / "saves" / "companion_memory.json"
        )
        audio_preferences_path = (
            self.integration_config.preferred_shared_path("audio_preferences_file")
            or ROOT / "saves" / "audio_preferences.json"
        )
        agent_preferences_path = (
            self.integration_config.preferred_shared_path("agent_preferences_file")
            or ROOT / "saves" / "agent_preferences.json"
        )
        self.vision_adapter = VisionStateAdapter(vision_path)
        self.memory_backend = MemoryBackend(memory_path)
        self.conversation_history_backend = ConversationHistoryBackend(
            history_path,
            limit=0,
            fallback_paths=self.integration_config.candidate_paths(
                "conversation_history_file"
            ),
        )
        self.parent_summary_backend = ParentSummaryBackend(parent_summary_path)
        self.audio_preferences_backend = AudioPreferencesBackend(audio_preferences_path)
        self.agent_preferences_backend = AgentPreferencesBackend(agent_preferences_path)
        self.weather_city = self.agent_preferences_backend.load_city()
        self.vision_state = self.vision_adapter.read()
        self.last_vision_poll = 0.0
        self.xingbao_override = None
        self.xingbao_override_until = 0.0
        self.xingbao_click_index = 0
        self.last_user_activity = time.monotonic()
        # A physical touch can also emit a synthetic mouse-button event.  Keep
        # one short-lived tap record so a start button is not immediately
        # interpreted as a second, pause button press.
        self.last_control_tap_at = 0.0
        self.last_control_tap_pos = None
        self.volume = self.audio_preferences_backend.load(
            default=self.store.data["volume"]
        )
        self.parent_answer = ""
        self.parent_verified = False
        self.parent_failed_attempts = 0
        self.parent_locked_until = 0.0
        self.parent_question = None
        self.new_parent_question()
        self.rest_started_at = None
        self.active_companion = self.store.data["active_companion"]
        self.locked = False
        self.lock_slider_progress = 0.0
        self.lock_slider_dragging = False
        self.drawer_focus = 1
        self.pomodoro_started_at = None
        self.pomodoro_duration = 5 * 60
        self.pomodoro_paused_remaining = self.pomodoro_duration
        self.focus_rewarded = False
        self.pending_focus_memory = False
        self.drawing = False
        self.drawing_surface = None
        self.last_draw_pos = None
        self.drawing_has_content = False
        self.drawing_rewarded = False
        self.drawing_clear_at = None
        self.eye_rest_recorded = False
        self.selected_artwork = None
        self.selected_memory = None
        self.memory_tab = "chat"
        self.memory_scroll = 0
        self.memory_scroll_render = 0.0
        self.memory_scroll_started_at = 0.0
        self.parent_summary_scroll = 0
        self.parent_summary_scroll_render = 0.0
        self.parent_summary_scroll_started_at = 0.0
        self.scroll_touch_start = None
        self.scroll_touch_last = None
        self.scroll_touch_remainder = 0.0
        self.scroll_touch_dragged = False
        self.scroll_touch_source = None
        self.memory_chat_cache = []
        self.memory_chat_cache_at = 0.0
        self.memory_growth_cache = []
        self.memory_growth_cache_at = 0.0
        self.artwork_cache = {}
        self.animation_overlay = None
        self.animation_overlay_size = None
        self.read_targets = []
        self.last_read_text = ""
        self.last_read_at = 0.0
        self.game_summary = self.store.game_summary()
        self.refresh_parent_summaries()
        read_aloud_trace("ui_ready speech_client={}".format(bool(self.on_speech_request)))
        game_points = self.store.sync_game_stars(self.game_summary["stars"])
        self.network = network_status()
        self.battery = battery_status()
        self.background_source = pygame.image.load(str(DEFAULT_BACKGROUND)).convert()
        self.background = None
        self.scaled_size = None
        self.widget_icons = {}
        self.scaled_widget_icons = {}
        self.top_status_assets = {}
        self.scaled_top_status_assets = {}
        self.search_status_icon = None
        self.scaled_search_status_icons = {}
        self.status_recognize_icons = {}
        self.scaled_status_recognize_icons = {}
        for key, path in WIDGET_ICON_FILES.items():
            try:
                self.widget_icons[key] = pygame.image.load(str(path)).convert_alpha()
            except (pygame.error, OSError):
                trace("widget_icon_unavailable {}".format(path))
        try:
            self.search_status_icon = pygame.image.load(
                str(SEARCH_STATUS_ICON_FILE)
            ).convert_alpha()
        except (pygame.error, OSError):
            trace("search_status_icon_unavailable {}".format(SEARCH_STATUS_ICON_FILE))
        for key, path in {
            "camera": CAMERA_RECOGNIZE_ICON_FILE,
            "emotion": EMOTION_RECOGNIZE_ICON_FILE,
        }.items():
            try:
                self.status_recognize_icons[key] = pygame.image.load(str(path)).convert_alpha()
            except (pygame.error, OSError):
                trace("recognize_status_icon_unavailable {}".format(path))
        for key, (filename, _position) in TOP_STATUS_ASSET_FILES.items():
            path = TOP_STATUS_ASSET_DIR / filename
            try:
                self.top_status_assets[key] = pygame.image.load(str(path)).convert_alpha()
            except (pygame.error, OSError):
                trace("top_status_asset_unavailable {}".format(path))
        self.xingbao_frames = {}
        frames_dir = ROOT / "assets" / "desktop" / "xingbao_frames"
        for state in ("idle", "yawn", "thinking", "celebrate"):
            self.xingbao_frames[state] = [
                pygame.image.load(str(frames_dir / "{}_{}.png".format(state, index))).convert_alpha()
                for index in range(4)
            ]
        self.scaled_xingbao_frames = {}
        self.lobster_sprites = self._load_lobster_sprites()
        self.scaled_lobster_sprites = {}
        if game_points:
            self.show_notice("星星变成{}积分啦！".format(game_points), seconds=3.2)

    def layout(self):
        w, h = self.screen.get_size()
        return {
            "drawer": pygame.Rect(0, int(h * 0.85), int(w * 0.19), int(h * 0.13)),
            "memory": pygame.Rect(int(w * 0.945), int(h * 0.48), int(w * 0.055), int(h * 0.30)),
            "pet": pygame.Rect(int(w * 0.41), int(h * 0.43), int(w * 0.20), int(h * 0.32)),
            "health": pygame.Rect(int(w * 0.18), 0, int(w * 0.28), int(h * 0.09)),
            "wifi": pygame.Rect(int(w * 0.68), 0, int(w * 0.055), int(h * 0.09)),
            "volume": pygame.Rect(int(w * 0.735), 0, int(w * 0.055), int(h * 0.09)),
            "battery": pygame.Rect(int(w * 0.79), 0, int(w * 0.075), int(h * 0.09)),
            "lock": pygame.Rect(int(w * 0.855), 0, int(w * 0.055), int(h * 0.09)),
            "parent": pygame.Rect(int(w * 0.91), 0, int(w * 0.09), int(h * 0.09)),
        }

    def _load_lobster_sprites(self):
        """Load the supplied transparent lobster poses from the 2×2 sticker sheet."""
        try:
            wave = pygame.image.load(str(LOBSTER_ASSET_DIR / "wave.png")).convert_alpha()
            sheet = pygame.image.load(str(LOBSTER_ASSET_DIR / "stickers.png")).convert_alpha()
        except (pygame.error, OSError) as exc:
            trace("lobster_assets_unavailable {}".format(exc))
            return {}

        sprites = {"wave": wave}
        tile_w, tile_h = sheet.get_width() // 2, sheet.get_height() // 2
        for name, column, row in (("laptop", 1, 0), ("thinking", 0, 1), ("celebrate", 1, 1)):
            tile = sheet.subsurface(pygame.Rect(column * tile_w, row * tile_h, tile_w, tile_h)).copy()
            bounds = tile.get_bounding_rect(min_alpha=1)
            if bounds.width and bounds.height:
                tile = tile.subsurface(bounds).copy()
            sprites[name] = tile
        return sprites

    def drawer_buttons(self):
        w, h = self.screen.get_size()
        return {
            "toolbox": pygame.Rect(int(w * 0.055), int(h * 0.67), int(w * 0.155), int(h * 0.085)),
            "game": pygame.Rect(int(w * 0.225), int(h * 0.67), int(w * 0.155), int(h * 0.085)),
            "rest": pygame.Rect(int(w * 0.055), int(h * 0.79), int(w * 0.155), int(h * 0.085)),
            "companion": pygame.Rect(int(w * 0.225), int(h * 0.79), int(w * 0.155), int(h * 0.085)),
        }

    def widget_layout(self):
        w, h = self.screen.get_size()
        return {
            "today": pygame.Rect(int(w * 0.025), int(h * 0.14), int(w * 0.18), int(h * 0.15)),
            "goal": pygame.Rect(int(w * 0.79), int(h * 0.34), int(w * 0.16), int(h * 0.13)),
            "reward": pygame.Rect(int(w * 0.77), int(h * 0.50), int(w * 0.16), int(h * 0.13)),
            "tasks": pygame.Rect(int(w * 0.025), int(h * 0.34), int(w * 0.18), int(h * 0.20)),
            "mood": pygame.Rect(int(w * 0.77), int(h * 0.67), int(w * 0.16), int(h * 0.10)),
            "quick_game": pygame.Rect(int(w * 0.36), int(h * 0.88), int(w * 0.09), int(h * 0.075)),
            "quick_focus": pygame.Rect(int(w * 0.455), int(h * 0.88), int(w * 0.09), int(h * 0.075)),
            "quick_draw": pygame.Rect(int(w * 0.55), int(h * 0.88), int(w * 0.09), int(h * 0.075)),
            "quick_gallery": pygame.Rect(int(w * 0.645), int(h * 0.88), int(w * 0.09), int(h * 0.075)),
        }

    def new_parent_question(self):
        left = random.randint(150, 360)
        right = random.randint(80, 260)
        answer = left + right
        offsets = random.sample([-40, -30, -20, -10, 10, 20, 30, 40], 2)
        choices = [answer, answer + offsets[0], answer + offsets[1]]
        random.shuffle(choices)
        self.parent_question = {
            "text": "{}+{}=?".format(left, right),
            "answer": answer,
            "choices": choices,
        }

    def parent_lock_remaining(self, now=None):
        now = time.monotonic() if now is None else float(now)
        remaining = max(0.0, float(self.parent_locked_until) - now)
        if remaining <= 0 and self.parent_locked_until:
            self.parent_locked_until = 0.0
            self.parent_failed_attempts = 0
        return int(math.ceil(remaining))

    def set_xingbao_state(self, state, seconds=4.0):
        self.xingbao_override = state
        self.xingbao_override_until = time.monotonic() + float(seconds)

    def set_xingbao_scene(self, scene_id):
        """Set a GIF scene from the central UI bridge on the Pygame thread."""
        selected = self.scene_animator.set_scene(int(scene_id), pygame.time.get_ticks())
        trace("xingbao_scene id={} selected={}".format(scene_id, selected))
        return selected

    def mark_user_activity(self):
        self.last_user_activity = time.monotonic()

    def xingbao_state(self):
        if self.vision_state.get("distance_too_close") or self.vision_state.get("needs_water"):
            return "alert"
        if self.xingbao_override and time.monotonic() < self.xingbao_override_until:
            return self.xingbao_override
        self.xingbao_override = None
        if self.modal or self.drawer_open:
            return "idle"
        idle_seconds = max(0.0, time.monotonic() - self.last_user_activity)
        if idle_seconds < 7.0:
            return "idle"
        phase = (idle_seconds - 7.0) % 25.0
        if 0.0 <= phase < 3.5:
            return "thinking"
        if 13.0 <= phase < 16.5:
            return "yawn"
        if 8.0 <= phase < 8.22 or 20.0 <= phase < 20.22:
            return "blink"
        return "idle"

    def modal_geometry(self):
        w, h = self.screen.get_size()
        if self.modal == "memory":
            panel = pygame.Rect(int(w * 0.28), int(h * 0.13), int(w * 0.44), int(h * 0.72))
        elif self.modal == "parent_center":
            # Leave room for the parent-only minimize control without letting
            # it overlap the desktop launcher controls below the dialog.
            panel = pygame.Rect(int(w * 0.25), int(h * 0.12), int(w * 0.50), int(h * 0.75))
        else:
            panel = pygame.Rect(int(w * 0.25), int(h * 0.16), int(w * 0.50), int(h * 0.64))
        close = pygame.Rect(panel.right - int(w * 0.075), panel.y + int(h * 0.025), int(w * 0.055), int(h * 0.07))
        action = pygame.Rect(int(w * 0.39), int(h * 0.66), int(w * 0.22), int(h * 0.085))
        return panel, close, action

    def companion_toggle_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(int(w * 0.455), int(h * 0.47), int(w * 0.09), int(h * 0.06))

    def _scaled_background(self):
        size = self.screen.get_size()
        if self.background is None or self.scaled_size != size:
            self.background = pygame.transform.smoothscale(self.background_source, size)
            self.scaled_size = size
        return self.background

    def draw_widget_icon(self, key, rect):
        """Draw a supplied transparent icon, cached at its display size."""
        source = self.widget_icons.get(key)
        target = pygame.Rect(rect)
        if source is None or target.width <= 0 or target.height <= 0:
            return None
        scale = min(target.width / source.get_width(), target.height / source.get_height())
        size = (max(1, round(source.get_width() * scale)), max(1, round(source.get_height() * scale)))
        cache_key = (key, size)
        image = self.scaled_widget_icons.get(cache_key)
        if image is None:
            image = pygame.transform.smoothscale(source, size)
            self.scaled_widget_icons[cache_key] = image
        icon_rect = image.get_rect(center=target.center)
        self.screen.blit(image, icon_rect)
        return icon_rect

    def draw_top_status_asset(self, key, *, topleft=None):
        """Draw one extracted wallpaper status-bar asset at its original place."""
        source = self.top_status_assets.get(key)
        item = TOP_STATUS_ASSET_FILES.get(key)
        if source is None or item is None:
            return None
        w, h = self.screen.get_size()
        source_w, source_h = TOP_STATUS_SOURCE_SIZE
        scale_x, scale_y = w / source_w, h / source_h
        size = (
            max(1, round(source.get_width() * scale_x)),
            max(1, round(source.get_height() * scale_y)),
        )
        cache_key = (key, size)
        image = self.scaled_top_status_assets.get(cache_key)
        if image is None:
            image = pygame.transform.smoothscale(source, size)
            self.scaled_top_status_assets[cache_key] = image
        x, y = item[1]
        position = topleft or (round(x * scale_x), round(y * scale_y))
        rect = image.get_rect(topleft=position)
        self.screen.blit(image, rect)
        return rect

    def show_notice(self, text, seconds=2.2, priority="external"):
        """Display a subtitle unless it would cover an active dialogue line."""
        is_dialogue = str(priority or "external").strip().casefold() == "dialogue"
        if bool(getattr(self, "dialogue_subtitle_active", False)) and not is_dialogue:
            trace("notice_suppressed priority={} text={!r}".format(priority, str(text)[:80]))
            return False
        self.notice = text
        self.notice_until = pygame.time.get_ticks() + int(seconds * 1000)
        return True

    def set_camera_snapshot(self, data_uri, width, height, *, mirror=True):
        """Decode a bounded camera JPEG without replacing a valid preview on error."""
        prefix = "data:image/jpeg;base64,"
        if (
            not isinstance(data_uri, str)
            or not data_uri.startswith(prefix)
            or type(width) is not int
            or type(height) is not int
            or width <= 0
            or height <= 0
        ):
            return False
        encoded = data_uri[len(prefix):]
        maximum_encoded_bytes = ((CAMERA_SNAPSHOT_MAX_BYTES + 2) // 3) * 4
        if not encoded or len(encoded) > maximum_encoded_bytes:
            return False
        try:
            decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            return False
        if (
            len(decoded) > CAMERA_SNAPSHOT_MAX_BYTES
            or not decoded.startswith(b"\xff\xd8\xff")
            or not decoded.endswith(b"\xff\xd9")
        ):
            return False
        try:
            surface = pygame.image.load(io.BytesIO(decoded), "snapshot.jpg").convert()
        except (pygame.error, OSError, ValueError):
            return False
        if surface.get_size() != (width, height):
            return False
        # Mirror only the local UI preview, matching the front-facing touch
        # display.  The original JPEG remains unchanged for multimodal LLM
        # analysis.
        self.camera_snapshot_surface = pygame.transform.flip(surface, True, False) if mirror else surface
        self.camera_snapshot_size = (width, height)
        return True

    def clear_camera_snapshot(self):
        """Clear the transient camera preview; repeated clears are harmless."""
        self.camera_snapshot_surface = None
        self.camera_snapshot_size = None
        return True

    def camera_snapshot_rect(self):
        """Return the fitted preview rectangle above the reserved subtitle strip."""
        if self.camera_snapshot_surface is None or self.camera_snapshot_size is None:
            return None
        screen_width, screen_height = self.screen.get_size()
        source_width, source_height = self.camera_snapshot_size
        scale = min(
            (screen_width * 0.62) / source_width,
            (screen_height * 0.58) / source_height,
        )
        image_width = max(1, int(source_width * scale))
        image_height = max(1, int(source_height * scale))
        padding = max(6, int(screen_height * 0.012))
        image_rect = pygame.Rect(0, 0, image_width, image_height)
        image_rect.midbottom = (
            screen_width // 2,
            int(screen_height * 0.77) - padding,
        )
        return image_rect

    def draw_camera_snapshot_overlay(self):
        """Paint the decoded camera preview while leaving the subtitle layer visible."""
        image_rect = self.camera_snapshot_rect()
        if image_rect is None:
            return
        screen_height = self.screen.get_height()
        padding = max(6, int(screen_height * 0.012))
        panel = image_rect.inflate(padding * 2, padding * 2)
        radius = max(10, int(screen_height * 0.022))
        border_width = max(1, int(screen_height * 0.0025))
        shade = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(
            shade,
            (12, 28, 45, 222),
            shade.get_rect(),
            border_radius=radius,
        )
        self.screen.blit(shade, panel.topleft)

        scaled = pygame.transform.smoothscale(
            self.camera_snapshot_surface, image_rect.size
        )
        clipped = pygame.Surface(image_rect.size, pygame.SRCALPHA)
        clipped.blit(scaled, (0, 0))
        mask = pygame.Surface(image_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(
            mask,
            (255, 255, 255, 255),
            mask.get_rect(),
            border_radius=max(6, radius - padding),
        )
        clipped.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(clipped, image_rect.topleft)
        pygame.draw.rect(
            self.screen,
            (137, 211, 244),
            panel,
            width=border_width,
            border_radius=radius,
        )

    def speak_readable(
        self,
        text,
        page=None,
        *,
        interrupt=True,
        pause_conversation=False,
        show_notice=True,
    ):
        speech = " ".join(str(text or "").replace("·", "，").split())
        if not speech:
            read_aloud_trace("skip empty_text page={}".format(page or self.modal))
            return False
        now = time.monotonic()
        if speech == self.last_read_text and now - self.last_read_at < 0.8:
            read_aloud_trace("skip duplicate page={} text={!r}".format(page or self.modal, speech[:80]))
            return False
        self.last_read_text = speech
        self.last_read_at = now
        if show_notice:
            self.show_notice(speech[:22] + ("…" if len(speech) > 22 else ""), seconds=1.6)
        read_aloud_trace(
            "submit page={} interrupt={} volume={} chars={} text={!r}".format(
                page or self.modal or "desktop",
                bool(interrupt),
                self.volume,
                len(speech),
                speech[:120],
            )
        )
        if self.on_speech_request:
            self.on_speech_request({
                "type": "speech_request",
                "text": speech,
                "scene": "desktop",
                "page": page or self.modal or "desktop",
                "source": "xingbao_desktop_read_aloud",
                "priority": "read_aloud",
                "interrupt": bool(interrupt),
                "pause_conversation": bool(pause_conversation),
                "latency_mode": "fast",
                "volume": self.volume,
                "on_status": self._on_read_aloud_status,
            })
        else:
            read_aloud_trace("failed no_speech_client")
        return True

    @staticmethod
    def _on_read_aloud_status(status):
        payload = status.get("payload") if isinstance(status, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        read_aloud_trace(
            "central_status ok={} status={} error={} message={!r}".format(
                bool(status.get("ok")) if isinstance(status, dict) else False,
                payload.get("status", ""),
                payload.get("error", ""),
                str(payload.get("message", ""))[:160],
            )
        )

    def begin_read_targets(self):
        self.read_targets = []

    def register_read_target(self, rect, text, page=None):
        speech = " ".join(str(text or "").split())
        if not speech:
            return
        self.read_targets.append({
            "rect": pygame.Rect(rect),
            "text": speech,
            "page": page or self.modal or "desktop",
        })

    def read_target_at(self, pos):
        for target in reversed(self.read_targets):
            if target["rect"].collidepoint(pos):
                return self.speak_readable(target["text"], page=target["page"])
        return False

    def save_preferences(self):
        self.store.save(volume=self.volume, active_companion=self.active_companion)
        try:
            self.volume = self.audio_preferences_backend.save(self.volume)
        except OSError:
            pass

    def poll_integrations(self):
        # Vision state is pushed directly from the vision process to the UI
        # bridge, then applied on this Pygame thread by update_vision_state.
        # Do not poll the shared status file here: it is only retained for a
        # safe startup snapshot and compatibility with older deployments.
        return None

    def update_vision_state(self, distance_too_close, needs_water, hold_seconds=1.0):
        """Direct callback for an in-process OpenCV loop with two return values."""
        self.vision_state = VisionStateAdapter.normalize([distance_too_close, needs_water])
        self.last_vision_poll = time.monotonic() + max(0.0, float(hold_seconds))
        return dict(self.vision_state)

    def remember(self, memory_type, title, summary, source, media_path=None):
        try:
            return self.memory_backend.add(
                memory_type, title, summary, source=source, media_path=media_path)
        except (OSError, ValueError, TypeError):
            return None

    @staticmethod
    def child_memory_title(entry):
        if entry.get("type") == "artwork":
            return "我画好一幅画"
        return str(entry.get("title") or "星宝记住的小事")

    @staticmethod
    def child_memory_summary(entry):
        summary = str(entry.get("summary") or "")
        lower = summary.lower()
        if entry.get("type") == "artwork" and (
            "/" in summary or "\\" in summary or lower.endswith((".png", ".jpg", ".jpeg"))
        ):
            return "这幅画已经放进小小展板啦"
        return summary or "这是一件开心的小事"

    def grant_reward(self, reason, amount, counter=None):
        awarded = self.store.award_points(reason, amount)
        if counter:
            self.store.save(**{counter: int(self.store.data.get(counter, 0)) + 1})
        if awarded:
            self.show_notice("{}啦！得到{}积分".format(reason, awarded), seconds=3.0)
            self.set_xingbao_state("celebrate", seconds=4.0)
        return awarded

    def pomodoro_remaining(self):
        if self.pomodoro_started_at is None:
            return self.pomodoro_paused_remaining
        remaining = max(0, self.pomodoro_paused_remaining - int(time.monotonic() - self.pomodoro_started_at))
        if remaining == 0:
            self.pomodoro_started_at = None
            self.pomodoro_paused_remaining = 0
            if not self.focus_rewarded:
                self.focus_rewarded = True
                self.grant_reward("专心5分钟", 50, counter="focus_completed")
                self.store.record_activity("focus", "专心5分钟", "得到了50积分")
                self.pending_focus_memory = True
        return remaining

    def toggle_pomodoro(self):
        if self.pomodoro_started_at is None:
            if self.pomodoro_paused_remaining <= 0:
                self.pomodoro_paused_remaining = self.pomodoro_duration
                self.focus_rewarded = False
            self.pomodoro_started_at = time.monotonic()
        else:
            self.pomodoro_paused_remaining = self.pomodoro_remaining()
            self.pomodoro_started_at = None

    def reset_pomodoro(self):
        self.pomodoro_started_at = None
        self.pomodoro_paused_remaining = self.pomodoro_duration
        self.focus_rewarded = False

    def drawing_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(int(w * 0.29), int(h * 0.31), int(w * 0.42), int(h * 0.38))

    def ensure_drawing_surface(self):
        rect = self.drawing_rect()
        if self.drawing_surface is None or self.drawing_surface.get_size() != rect.size:
            self.drawing_surface = pygame.Surface(rect.size)
            self.drawing_surface.fill((255, 253, 244))
        return self.drawing_surface

    def recent_artworks(self):
        artworks = list(self.store.data.get("artworks", []))
        artworks.sort(key=lambda entry: str(entry.get("time") or ""), reverse=True)
        return artworks[0:3]

    def gallery_artwork_rects(self):
        w, h = self.screen.get_size()
        return [pygame.Rect(int(w * x), int(h * 0.34), int(w * 0.12), int(h * 0.22)) for x in (0.29, 0.44, 0.59)]

    def memory_entry_rects(self):
        w, h = self.screen.get_size()
        return [pygame.Rect(int(w * 0.31), int(h * y), int(w * 0.38), int(h * 0.10)) for y in (0.315, 0.425, 0.535, 0.645)]

    def memory_tab_rects(self):
        w, h = self.screen.get_size()
        return {
            "chat": pygame.Rect(int(w * 0.33), int(h * 0.235), int(w * 0.16), int(h * 0.052)),
            "growth": pygame.Rect(int(w * 0.51), int(h * 0.235), int(w * 0.16), int(h * 0.052)),
        }

    def memory_footer_rect(self):
        """Hit area for the record-count hint at the bottom of the memory book."""
        _, h = self.screen.get_size()
        panel, _, _ = self.modal_geometry()
        return pygame.Rect(panel.x, panel.bottom - int(h * 0.065), panel.w, int(h * 0.060))

    def memory_footer_text(self):
        return self.modal_read_text()

    def chat_record_rects(self):
        w, h = self.screen.get_size()
        return [
            pygame.Rect(int(w * 0.302), int(h * y), int(w * 0.396), int(h * 0.078))
            for y in (0.330, 0.420, 0.510, 0.600, 0.690)
        ]

    def chat_bubble_rect(self, entry, row):
        w, h = self.screen.get_size()
        content = " ".join(str(entry.get("content", "")).split())
        bubble_width = min(
            int(row.w * 0.76),
            max(int(row.w * 0.28), int(w * (0.055 + min(len(content), 30) * 0.0082))),
        )
        bubble_height = int(h * 0.057)
        bubble_y = row.y + int(h * 0.016)
        if entry.get("role") == "child":
            bubble_right = row.right - int(w * 0.042)
            return pygame.Rect(
                bubble_right - bubble_width,
                bubble_y,
                bubble_width,
                bubble_height,
            )
        return pygame.Rect(
            row.x + int(w * 0.042),
            bubble_y,
            bubble_width,
            bubble_height,
        )

    def visible_chat_records(self):
        records = self.memory_chat_records()
        # Chat records are chronological, with the newest entry at the bottom.
        return records[self.memory_scroll:self.memory_scroll + 5]

    def memory_chat_records(self, force=False):
        """Avoid re-reading the history file for every animation frame."""
        now = time.monotonic()
        if force or now - self.memory_chat_cache_at >= 0.5:
            was_at_bottom = self.memory_scroll >= max(0, len(self.memory_chat_cache) - 5)
            self.memory_chat_cache = self.conversation_history_backend.recent()
            self.memory_chat_cache_at = now
            # Keep an open chat pinned to the newest message as new turns
            # arrive, without pulling a reader away from older entries.
            if self.modal == "memory" and self.memory_tab == "chat" and was_at_bottom:
                self.memory_scroll = max(0, len(self.memory_chat_cache) - 5)
                self.memory_scroll_render = float(self.memory_scroll)
                self.memory_scroll_started_at = now
        return self.memory_chat_cache

    def memory_growth_records(self, force=False):
        """Cache growth records while their cards animate during touch scroll."""
        now = time.monotonic()
        if force or now - self.memory_growth_cache_at >= 0.5:
            self.memory_growth_cache = self.memory_backend.recent(100)
            self.memory_growth_cache_at = now
        return self.memory_growth_cache

    def reset_memory_book_position(self, tab="chat"):
        """Open chats at their latest message while retaining chronological order."""
        self.memory_tab = tab
        self.memory_scroll = 0
        self.memory_scroll_render = 0.0
        self.memory_scroll_started_at = 0.0
        if tab == "growth":
            self.memory_growth_records(force=True)
        else:
            records = self.memory_chat_records(force=True)
            self.memory_scroll = max(0, len(records) - 5)
            self.memory_scroll_render = float(self.memory_scroll)

    def parent_summary_rects(self):
        w, h = self.screen.get_size()
        return [
            pygame.Rect(int(w * 0.285), int(h * y), int(w * 0.43), int(h * 0.078))
            for y in (0.36, 0.438, 0.516, 0.594)
        ]

    def weather_city_rects(self):
        w, h = self.screen.get_size()
        return {
            city: pygame.Rect(
                int(w * (0.295 + (index % 3) * 0.14)),
                int(h * (0.350 + (index // 3) * 0.090)),
                int(w * 0.13),
                int(h * 0.060),
            )
            for index, city in enumerate(WEATHER_CITIES)
        }

    @staticmethod
    def summary_delete_rect(card):
        return pygame.Rect(
            card.right - int(card.w * 0.115),
            card.y + int(card.h * 0.24),
            int(card.w * 0.095),
            int(card.h * 0.52),
        )

    def parent_report_entries(self):
        category_order = {
            "memories": 0,
            "interests": 1,
            "preferences": 2,
            "chat_habits": 3,
            "conversation_style": 4,
            "answer_performance": 5,
            "play_time": 6,
            "recent_change": 7,
        }
        return sorted(
            self.parent_summary_backend.load(),
            key=lambda item: (
                category_order.get(str(item.get("category", "")), 99),
                str(item.get("updated_at", "")),
                str(item.get("title", "")),
            ),
        )

    def refresh_parent_summaries(self):
        memory = load_json_object(self.companion_memory_path)
        self.game_summary = self.store.game_summary()
        try:
            return self.parent_summary_backend.refresh(
                memory,
                self.game_summary,
                self.conversation_history_backend.load(),
            )
        except OSError:
            return self.parent_summary_backend.load()

    def scroll_current_modal(self, delta):
        step = int(delta)
        if not step:
            return
        if self.modal == "memory":
            total = (
                len(self.memory_chat_records())
                if self.memory_tab == "chat"
                else len(self.memory_growth_records())
            )
            page_size = 5 if self.memory_tab == "chat" else 4
            next_scroll = max(
                0,
                min(max(0, total - page_size), self.memory_scroll + step),
            )
            if next_scroll != self.memory_scroll:
                self.memory_scroll_render = self.current_memory_scroll_render()
                self.memory_scroll = next_scroll
                self.memory_scroll_started_at = time.monotonic()
        elif self.modal == "parent_summaries":
            total = len(self.parent_report_entries())
            next_scroll = max(
                0,
                min(max(0, total - 4), self.parent_summary_scroll + step),
            )
            if next_scroll != self.parent_summary_scroll:
                self.parent_summary_scroll_render = (
                    self.current_parent_summary_scroll_render()
                )
                self.parent_summary_scroll = next_scroll
                self.parent_summary_scroll_started_at = time.monotonic()

    def current_memory_scroll_render(self):
        """Return the eased list position used to draw the memory book."""
        start = float(self.memory_scroll_render)
        target = float(self.memory_scroll)
        if abs(target - start) < 0.001:
            self.memory_scroll_render = target
            return target
        progress = min(1.0, (time.monotonic() - self.memory_scroll_started_at) / 0.12)
        eased = 1.0 - (1.0 - progress) ** 3
        position = start + (target - start) * eased
        if progress >= 1.0:
            self.memory_scroll_render = target
        return position

    def current_parent_summary_scroll_render(self):
        """Return the eased card offset for the parent growth report."""
        start = float(self.parent_summary_scroll_render)
        target = float(self.parent_summary_scroll)
        if abs(target - start) < 0.001:
            self.parent_summary_scroll_render = target
            return target
        progress = min(
            1.0,
            (time.monotonic() - self.parent_summary_scroll_started_at) / 0.10,
        )
        eased = 1.0 - (1.0 - progress) ** 3
        position = start + (target - start) * eased
        if progress >= 1.0:
            self.parent_summary_scroll_render = target
        return position

    def begin_memory_scroll_touch(self, pos, source):
        """Start one touch drag and merge synthetic mouse/finger events."""
        if self.scroll_touch_source == "finger" and source == "mouse":
            return
        if self.scroll_touch_start is not None:
            # Some SDL touch drivers emit a mouse down first and the native
            # finger down immediately after it.  They are one gesture, not a
            # second drag; retain the original coordinates and upgrade the
            # source used to decide which release finishes the gesture.
            if source == "finger":
                self.scroll_touch_source = "finger"
            return
        self.scroll_touch_start = pos
        self.scroll_touch_last = pos
        self.scroll_touch_remainder = 0.0
        self.scroll_touch_dragged = False
        self.scroll_touch_source = source
        trace("memory_scroll_begin source={} modal={} tab={} pos={}".format(
            source, self.modal, self.memory_tab, tuple(int(value) for value in pos)
        ))

    def update_memory_scroll_touch(self, pos, source):
        if self.scroll_touch_start is None:
            return
        # Movement may arrive through the counterpart of the event stream that
        # started the gesture (FINGERDOWN + MOUSEMOTION, or the reverse).
        # Treat both as one sequence; duplicate coordinates add a zero delta.
        delta_y = pos[1] - self.scroll_touch_last[1]
        self.scroll_touch_last = pos
        # Both memory tabs use normal direct manipulation: swipe up to reveal
        # later entries, swipe down to return to earlier ones.
        self.scroll_touch_remainder -= delta_y
        w, h = self.screen.get_size()
        # Cards are taller than chat bubbles.  A short gesture threshold keeps
        # both memory tabs visually attached to the finger instead of waiting
        # for a full card-height before the next transition starts.
        step_pixels = (
            max(8, int(h * 0.012))
            if self.modal == "parent_summaries"
            else max(12, int(h * 0.018))
        )
        while abs(self.scroll_touch_remainder) >= step_pixels:
            direction = 1 if self.scroll_touch_remainder > 0 else -1
            before = (
                self.memory_scroll
                if self.modal == "memory"
                else self.parent_summary_scroll
            )
            self.scroll_current_modal(direction)
            self.scroll_touch_remainder -= direction * step_pixels
            after = (
                self.memory_scroll
                if self.modal == "memory"
                else self.parent_summary_scroll
            )
            if before == after:
                self.scroll_touch_remainder = 0.0
                break
            self.scroll_touch_dragged = True

    def finish_memory_scroll_touch(self, pos, source):
        if self.scroll_touch_start is None or self.scroll_touch_source != source:
            return False
        dragged = self.scroll_touch_dragged or abs(pos[1] - self.scroll_touch_start[1]) >= 12
        self.scroll_touch_start = None
        self.scroll_touch_last = None
        self.scroll_touch_remainder = 0.0
        self.scroll_touch_dragged = False
        self.scroll_touch_source = None
        trace("memory_scroll_finish source={} dragged={} offset={}".format(
            source,
            dragged,
            self.memory_scroll if self.modal == "memory" else self.parent_summary_scroll,
        ))
        return dragged

    def chat_records_for_render(self, rendered_scroll):
        """Return a continuous, finger-direction-correct chat list transition."""
        records = self.memory_chat_records()
        target = float(self.memory_scroll)
        if rendered_scroll < target - 0.001:
            base = int(rendered_scroll)
            return records[base:base + 6], 0, base - rendered_scroll
        if rendered_scroll > target + 0.001:
            base = int(rendered_scroll + 0.999)
            start = max(0, base - 1)
            return records[start:base + 5], start - base, base - rendered_scroll
        base = int(target)
        return records[base:base + 5], 0, 0.0

    def growth_records_for_render(self, rendered_scroll):
        """Return continuous growth-card positions for the current gesture."""
        records = self.memory_growth_records()
        target = float(self.memory_scroll)
        if rendered_scroll < target - 0.001:
            base = int(rendered_scroll)
            return records[base:base + 5], 0, base - rendered_scroll
        if rendered_scroll > target + 0.001:
            base = int(rendered_scroll + 0.999)
            start = max(0, base - 1)
            return records[start:base + 4], start - base, base - rendered_scroll
        base = int(target)
        return records[base:base + 4], 0, 0.0

    def parent_summaries_for_render(self, rendered_scroll):
        """Return enough report cards to animate smoothly into either direction."""
        summaries = self.parent_report_entries()
        target = float(self.parent_summary_scroll)
        if rendered_scroll < target - 0.001:
            base = int(rendered_scroll)
            return summaries[base:base + 5], base - rendered_scroll
        if rendered_scroll > target + 0.001:
            base = int(rendered_scroll + 0.999)
            start = max(0, base - 1)
            return summaries[start:base + 4], base - rendered_scroll
        base = int(target)
        return summaries[base:base + 4], 0.0

    def artwork_image(self, entry, size):
        path = self.store.root / entry.get("path", "")
        key = (str(path), tuple(size))
        if key in self.artwork_cache:
            return self.artwork_cache[key]
        try:
            image = pygame.image.load(str(path)).convert()
            image = pygame.transform.smoothscale(image, size)
        except (OSError, pygame.error):
            image = pygame.Surface(size)
            image.fill((244, 236, 215))
        self.artwork_cache[key] = image
        return image

    def memory_thumbnail(self, entry, size):
        media_path = entry.get("media_path")
        if not media_path and entry.get("type") == "artwork":
            old_summary = str(entry.get("summary") or "")
            if "/" in old_summary or "\\" in old_summary:
                media_path = old_summary
        path = Path(str(media_path or ""))
        if media_path and not path.is_absolute():
            path = self.store.root / path
        key = ("memory", str(path), tuple(size), entry.get("type"))
        if key in self.artwork_cache:
            return self.artwork_cache[key]
        try:
            image = pygame.image.load(str(path)).convert()
            image = pygame.transform.smoothscale(image, size)
        except (OSError, pygame.error):
            image = pygame.Surface(size)
            image.fill((250, 235, 196))
            colors = {
                "game": (102, 174, 190), "artwork": (239, 158, 94),
                "health": (121, 177, 119), "learning": (160, 142, 199),
            }
            color = colors.get(entry.get("type"), (232, 181, 91))
            center = (size[0] // 2, size[1] // 2)
            pygame.draw.circle(image, color, center, max(5, min(size) // 4))
            pygame.draw.circle(image, (255, 247, 221), center, max(3, min(size) // 8))
        self.artwork_cache[key] = image
        return image

    def save_memory_snapshot(self, kind):
        folder = self.store.root / "saves" / "memory_shots"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / "{}_{}.png".format(
            kind, datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        try:
            pygame.image.save(self.screen, str(destination))
            return destination.relative_to(self.store.root).as_posix()
        except (OSError, pygame.error, ValueError):
            return None

    def handle_draw_point(self, pos, start=False):
        self.mark_user_activity()
        self.prepare_next_drawing_if_due()
        if self.drawing_clear_at is not None:
            return
        canvas = self.drawing_rect()
        if not canvas.collidepoint(pos):
            self.last_draw_pos = None
            return
        local = (pos[0] - canvas.x, pos[1] - canvas.y)
        surface = self.ensure_drawing_surface()
        color = (66, 118, 145)
        width = max(4, int(self.screen.get_height() * 0.009))
        if start or self.last_draw_pos is None:
            pygame.draw.circle(surface, color, local, width // 2)
        else:
            pygame.draw.line(surface, color, self.last_draw_pos, local, width)
        self.last_draw_pos = local
        self.drawing_has_content = True

    def complete_drawing(self):
        self.prepare_next_drawing_if_due()
        if self.drawing_clear_at is not None:
            return False
        if not self.drawing_has_content:
            self.show_notice("先画一点东西吧")
            return False
        artwork_dir = self.store.root / "saves" / "artworks"
        artwork_dir.mkdir(parents=True, exist_ok=True)
        filename = "artwork_{}.png".format(datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        destination = artwork_dir / filename
        try:
            pygame.image.save(self.ensure_drawing_surface(), str(destination))
        except (OSError, pygame.error):
            self.show_notice("这幅画没有放好，请再试一次")
            return False
        relative = destination.relative_to(self.store.root).as_posix()
        self.store.record_artwork(relative, "星宝画作{}".format(len(self.store.data.get("artworks", [])) + 1))
        self.remember(
            "artwork", "我画好一幅画", "这幅画已经放进小小展板啦",
            "drawing_board", media_path=relative)
        self.grant_reward("画好一幅画", 30, counter="drawings_completed")
        # Keep the finished picture visible briefly, then start a fresh canvas.
        self.drawing_clear_at = time.monotonic() + 3.0
        self.drawing_rewarded = True
        return True

    def prepare_next_drawing_if_due(self):
        if self.drawing_clear_at is None or time.monotonic() < self.drawing_clear_at:
            return False
        self.drawing_surface = None
        self.last_draw_pos = None
        self.drawing_has_content = False
        self.drawing_rewarded = False
        self.selected_artwork = None
        self.drawing_clear_at = None
        return True

    def open_game(self):
        self.save_preferences()
        self.next_action = "game"
        self.running = False
        return "game"

    def minimize_program(self):
        """Ask the Wayland compositor to minimize without changing the UI surface."""
        try:
            video_driver = pygame.display.get_driver()
            accepted = minimize_window(
                os.getpid(),
                video_driver=video_driver,
                iconify=pygame.display.iconify,
            )
        except pygame.error as exc:
            accepted = False
            trace("minimize_failed error={!r}".format(exc))
        else:
            trace("minimize_sent backend={} accepted={!r} fullscreen={} size={}".format(
                video_driver, accepted, self.fullscreen, self.screen.get_size()
            ))
        if accepted is False:
            self.show_notice("当前桌面不支持最小化", seconds=2.8)
            return False
        self.speak_readable("程序已最小化", page="parent_center")
        return True

    def reactivate_display(self):
        """Reuse the loaded desktop after returning from the game window."""
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode(
            (0, 0) if self.fullscreen else self.screen.get_size(),
            flags,
        )
        self.clock = pygame.time.Clock()
        self.running = True
        self.next_action = None
        self.drawer_open = False
        self.modal = None
        self.drawing = False
        self.last_draw_pos = None

    def handle_key(self, key):
        self.mark_user_activity()
        if self.locked:
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self.locked = False
                self.modal = None
                self.reset_lock_slider()
                self.show_notice("欢迎回来")
            return None
        if (
            self.modal == "parent"
            and pygame.K_0 <= key <= pygame.K_9
            and self.parent_lock_remaining() == 0
        ):
            if len(self.parent_answer) < 4:
                self.parent_answer += str(key - pygame.K_0)
            return None
        if (
            self.modal == "parent"
            and key == pygame.K_BACKSPACE
            and self.parent_lock_remaining() == 0
        ):
            self.parent_answer = self.parent_answer[:-1]
            return None
        if self.modal == "parent" and key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.verify_parent_answer(self.parent_answer)
            return None
        if self.modal:
            if self.modal in ("memory", "parent_summaries") and key in (
                pygame.K_UP, pygame.K_PAGEUP,
            ):
                self.scroll_current_modal(-1)
                return None
            if self.modal in ("memory", "parent_summaries") and key in (
                pygame.K_DOWN, pygame.K_PAGEDOWN,
            ):
                self.scroll_current_modal(1)
                return None
            if self.modal == "drawing" and key == pygame.K_c:
                self.drawing_surface = None
                self.drawing_has_content = False
                self.drawing_rewarded = False
                self.show_notice("画板已清空")
                return None
            if self.modal == "pomodoro" and key == pygame.K_SPACE:
                self.toggle_pomodoro()
                return None
            if key == pygame.K_ESCAPE:
                self._close_modal()
            return None
        if self.drawer_open:
            if key in (pygame.K_LEFT, pygame.K_RIGHT):
                self.drawer_focus = self.drawer_focus ^ 1
                return None
            if key in (pygame.K_UP, pygame.K_DOWN):
                self.drawer_focus = (self.drawer_focus + 2) % 4
                return None
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                actions = ("toolbox", "game", "rest", "companion")
                selected = actions[self.drawer_focus]
                if selected == "game":
                    return self.open_game()
                self.modal = selected
                if selected == "rest":
                    self.rest_started_at = None
                    self.eye_rest_recorded = False
                return None
        if key in (pygame.K_g, pygame.K_RETURN, pygame.K_SPACE):
            return self.open_game()
        if key == pygame.K_d:
            self.drawer_open = not self.drawer_open
        elif key == pygame.K_ESCAPE:
            if self.drawer_open:
                self.drawer_open = False
            else:
                self.running = False
        return None

    def verify_parent_answer(self, value):
        remaining = self.parent_lock_remaining()
        if remaining > 0:
            self.parent_answer = ""
            self.show_notice("连续两次回答错误，请{}秒后再试".format(remaining))
            return False
        try:
            correct = int(value) == int(self.parent_question["answer"])
        except (TypeError, ValueError):
            correct = False
        if correct:
            self.parent_verified = True
            self.parent_failed_attempts = 0
            self.parent_locked_until = 0.0
            self.parent_answer = ""
            self.refresh_parent_summaries()
            self.modal = "parent_center"
            self.show_notice("验证通过")
            return True
        self.parent_answer = ""
        self.parent_failed_attempts += 1
        if self.parent_failed_attempts >= 2:
            self.parent_locked_until = time.monotonic() + PARENT_LOCK_SECONDS
            self.show_notice("连续两次回答错误，请60秒后再试")
            return False
        self.new_parent_question()
        self.show_notice("答案不对，还可以再试一次")
        return False

    def _close_modal(self):
        self.modal = None
        self.parent_answer = ""
        self.drawing = False
        self.last_draw_pos = None
        self.save_preferences()

    def _handle_modal_touch(self, pos):
        w, h = self.screen.get_size()
        _, close, action = self.modal_geometry()
        if close.collidepoint(pos):
            self.speak_readable("关闭", page=self.modal)
            self._close_modal()
            return None

        if self.modal == "parent":
            remaining = self.parent_lock_remaining()
            if remaining > 0:
                self.show_notice("连续两次回答错误，请{}秒后再试".format(remaining))
                return None
            choices = [
                (str(value), pygame.Rect(int(w * rx), int(h * 0.50), int(w * 0.10), int(h * 0.10)))
                for value, rx in zip(self.parent_question["choices"], (0.32, 0.45, 0.58))
            ]
            for value, rect in choices:
                if rect.collidepoint(pos):
                    self.parent_answer = value
                    self.verify_parent_answer(value)
                    return None
        elif self.modal == "parent_center":
            minus = pygame.Rect(int(w * 0.36), int(h * 0.53), int(w * 0.08), int(h * 0.09))
            plus = pygame.Rect(int(w * 0.56), int(h * 0.53), int(w * 0.08), int(h * 0.09))
            city = pygame.Rect(int(w * 0.38), int(h * 0.65), int(w * 0.24), int(h * 0.06))
            summaries = pygame.Rect(int(w * 0.38), int(h * 0.72), int(w * 0.24), int(h * 0.06))
            minimize = pygame.Rect(int(w * 0.38), int(h * 0.80), int(w * 0.24), int(h * 0.06))
            if minus.collidepoint(pos):
                self.volume = max(0, self.volume - 10)
                self.save_preferences()
                self.speak_readable("音量减小", page="parent_center")
            elif plus.collidepoint(pos):
                self.volume = min(100, self.volume + 10)
                self.save_preferences()
                self.speak_readable("音量增大", page="parent_center")
            elif city.collidepoint(pos):
                self.speak_readable("设置天气城市", page="parent_center")
                self.modal = "weather_city"
            elif summaries.collidepoint(pos):
                self.speak_readable("打开孩子近况", page="parent_center")
                self.refresh_parent_summaries()
                self.parent_summary_scroll = 0
                self.parent_summary_scroll_render = 0.0
                self.parent_summary_scroll_started_at = 0.0
                self.modal = "parent_summaries"
            elif minimize.collidepoint(pos):
                # Minimize only the UI window.  The central voice, vision and
                # service processes stay running and can be restored normally.
                self.minimize_program()
            self.save_preferences()
            return None
        elif self.modal == "weather_city":
            for city, box in self.weather_city_rects().items():
                if box.collidepoint(pos):
                    self.weather_city = self.agent_preferences_backend.save_city(city)
                    self.modal = "parent_center"
                    self.show_notice("天气城市已设为{}".format(city))
                    self.speak_readable("天气城市已设为{}".format(city), page="weather_city")
                    return None
        elif self.modal == "parent_summaries":
            visible = self.parent_report_entries()[
                self.parent_summary_scroll:self.parent_summary_scroll + 4
            ]
            for entry, card in zip(visible, self.parent_summary_rects()):
                if self.summary_delete_rect(card).collidepoint(pos):
                    if self.parent_summary_backend.delete(entry.get("id", "")):
                        self.speak_readable("这条总结已删除", page="parent_summaries")
                        self.show_notice("已删除，不再用于后续对话")
                        total = len(self.parent_report_entries())
                        self.parent_summary_scroll = min(
                            self.parent_summary_scroll,
                            max(0, total - 4),
                        )
                        self.parent_summary_scroll_render = float(
                            self.parent_summary_scroll
                        )
                    return None
                if card.collidepoint(pos):
                    self.speak_readable(
                        "{}。{}".format(entry.get("title", "孩子近况"), entry.get("content", "")),
                        page="parent_summaries",
                    )
                    return None
        elif self.modal == "volume":
            minus = pygame.Rect(int(w * 0.35), int(h * 0.48), int(w * 0.10), int(h * 0.11))
            plus = pygame.Rect(int(w * 0.55), int(h * 0.48), int(w * 0.10), int(h * 0.11))
            if minus.collidepoint(pos):
                self.volume = max(0, self.volume - 10)
                self.save_preferences()
                self.speak_readable("音量减小", page="volume")
            elif plus.collidepoint(pos):
                self.volume = min(100, self.volume + 10)
                self.save_preferences()
                self.speak_readable("音量增大", page="volume")
            return None
        elif self.modal in ("health", "rest") and action.collidepoint(pos):
            self.speak_readable("开始二十秒护眼休息", page="rest")
            self.modal = "rest"
            self.rest_started_at = time.monotonic()
            self.eye_rest_recorded = False
            return None
        elif self.modal == "memory":
            if self.memory_footer_rect().collidepoint(pos):
                self.speak_readable(
                    self.memory_footer_text(),
                    page="memory",
                    show_notice=False,
                )
                return None
            for tab, box in self.memory_tab_rects().items():
                if box.collidepoint(pos):
                    self.reset_memory_book_position(tab)
                    self.speak_readable(
                        "聊天记录" if tab == "chat" else "成长记录",
                        page="memory",
                    )
                    return None
            if self.memory_tab == "chat":
                visible = self.visible_chat_records()
                read_aloud_trace(
                    "memory_chat_tap pos={} offset={} visible={}".format(
                        tuple(int(value) for value in pos),
                        self.memory_scroll,
                        len(visible),
                    )
                )
                for entry, row in zip(visible, self.chat_record_rects()):
                    bubble = self.chat_bubble_rect(entry, row)
                    if bubble.collidepoint(pos):
                        speaker = "我说：" if entry.get("role") == "child" else "星宝说："
                        text = "{}{}".format(speaker, entry.get("content", ""))
                        read_aloud_trace(
                            "memory_chat_hit role={} bubble={} text={!r}".format(
                                entry.get("role", ""), tuple(bubble), text[:120]
                            )
                        )
                        self.speak_readable(
                            text,
                            page="memory",
                            pause_conversation=True,
                            show_notice=False,
                        )
                        return None
                read_aloud_trace("memory_chat_tap_miss")
            else:
                visible = self.memory_growth_records()[
                    self.memory_scroll:self.memory_scroll + 4
                ]
                for entry, box in zip(visible, self.memory_entry_rects()):
                    if box.collidepoint(pos):
                        self.speak_readable(
                            "{}。{}".format(self.child_memory_title(entry), self.child_memory_summary(entry)),
                            page="memory",
                        )
                        self.selected_memory = entry
                        self.modal = "memory_detail"
                        return None
        elif self.modal == "memory_detail" and action.collidepoint(pos):
            self.speak_readable("返回回忆本", page="memory_detail")
            self.modal = "memory"
            self.selected_memory = None
            return None
        elif self.modal == "toolbox":
            tools = [
                ("专心小钟", pygame.Rect(int(w * 0.31), int(h * 0.43), int(w * 0.17), int(h * 0.10))),
                ("画板", pygame.Rect(int(w * 0.52), int(h * 0.43), int(w * 0.17), int(h * 0.10))),
            ]
            for label, rect in tools:
                if rect.collidepoint(pos):
                    self.speak_readable(label, page="toolbox")
                    self.modal = "pomodoro" if label == "专心小钟" else "drawing"
                    return None
        elif self.modal == "pomodoro":
            start = pygame.Rect(int(w * 0.34), int(h * 0.64), int(w * 0.14), int(h * 0.075))
            reset = pygame.Rect(int(w * 0.52), int(h * 0.64), int(w * 0.14), int(h * 0.075))
            if start.collidepoint(pos):
                self.speak_readable("专心小钟开始或暂停", page="pomodoro")
                self.toggle_pomodoro()
                return None
            elif reset.collidepoint(pos):
                self.speak_readable("专心小钟重新开始", page="pomodoro")
                self.reset_pomodoro()
                return None
        elif self.modal == "drawing":
            finish = pygame.Rect(int(w * 0.49), int(h * 0.70), int(w * 0.10), int(h * 0.055))
            clear = pygame.Rect(int(w * 0.60), int(h * 0.70), int(w * 0.09), int(h * 0.055))
            if finish.collidepoint(pos):
                self.speak_readable("画好啦", page="drawing")
                if self.complete_drawing():
                    self.speak_readable(
                        "哇，画得真棒！星宝已经把你的新作品放进小小展板啦！",
                        page="drawing",
                    )
                return None
            elif clear.collidepoint(pos):
                self.drawing_clear_at = None
                self.speak_readable("清空画板", page="drawing")
                self.drawing_surface = None
                self.drawing_has_content = False
                self.drawing_rewarded = False
                self.show_notice("画板已清空")
                return None
        elif self.modal == "gallery":
            for entry, box in zip(self.recent_artworks(), self.gallery_artwork_rects()):
                if box.collidepoint(pos):
                    self.speak_readable(entry.get("title", "星宝画作"), page="gallery")
                    self.selected_artwork = entry
                    self.modal = "artwork_view"
                    return None
        elif self.modal == "companion" and self.companion_toggle_rect().collidepoint(pos):
            self.active_companion = not self.active_companion
            self.save_preferences()
            state = "已开启" if self.active_companion else "已关闭"
            self.show_notice("Kimi场景识别{}".format(state))
            self.speak_readable("Kimi场景识别{}".format(state), page="companion")
            return None
        elif self.modal == "lock_confirm" and action.collidepoint(pos):
            self.speak_readable("星宝休息中，向右滑动可以唤醒", page="lock_confirm")
            self.locked = True
            self.modal = "locked"
            self.reset_lock_slider()
            return None
        self.read_target_at(pos)
        return None

    def _is_duplicate_control_tap(self, pos):
        """Ignore the mouse event synthesized from the same touch release."""
        now = time.monotonic()
        point = (int(pos[0]), int(pos[1]))
        previous = self.last_control_tap_pos
        duplicate = (
            previous is not None
            and now - self.last_control_tap_at < 0.25
            and abs(point[0] - previous[0]) <= 24
            and abs(point[1] - previous[1]) <= 24
        )
        self.last_control_tap_at = now
        self.last_control_tap_pos = point
        return duplicate

    def handle_touch(self, pos):
        if self._is_duplicate_control_tap(pos):
            return None
        self.mark_user_activity()
        if self.locked:
            # Locked-screen taps do not wake the desktop. Only the dedicated
            # rightward slider gesture (or the hardware keyboard fallback)
            # may unlock it.
            return None
        if self.modal:
            return self._handle_modal_touch(pos)

        if self.drawer_open:
            w, h = self.screen.get_size()
            panel = pygame.Rect(int(w * 0.03), int(h * 0.56), int(w * 0.38), int(h * 0.35))
            buttons = self.drawer_buttons()
            if buttons["game"].collidepoint(pos):
                self.speak_readable("一起玩，打开小游戏", page="drawer")
                return self.open_game()
            if buttons["toolbox"].collidepoint(pos):
                self.speak_readable("百宝箱", page="drawer")
                self.modal = "toolbox"
            elif buttons["rest"].collidepoint(pos):
                self.speak_readable("护眼休息", page="drawer")
                self.modal = "rest"
                self.rest_started_at = None
                self.eye_rest_recorded = False
            elif buttons["companion"].collidepoint(pos):
                self.speak_readable("主动陪伴", page="drawer")
                self.modal = "companion"
            elif not panel.collidepoint(pos):
                self.drawer_open = False
            else:
                self.read_target_at(pos)
            return None

        widgets = self.widget_layout()
        if widgets["today"].collidepoint(pos) or widgets["goal"].collidepoint(pos):
            self.read_target_at(pos)
            self.game_summary = self.store.game_summary()
            self.reset_memory_book_position("chat")
            self.modal = "memory"
            return None
        if widgets["reward"].collidepoint(pos):
            self.read_target_at(pos)
            self.modal = "rewards"
            return None
        if widgets["tasks"].collidepoint(pos):
            self.read_target_at(pos)
            self.modal = "rewards"
            return None
        if widgets["mood"].collidepoint(pos):
            self.read_target_at(pos)
            self.xingbao_click_index = (self.xingbao_click_index + 1) % 3
            state = ("happy", "thinking", "yawn")[self.xingbao_click_index]
            self.set_xingbao_state(state, seconds=4.5)
            return None
        if widgets["quick_game"].collidepoint(pos):
            self.speak_readable("游戏，打开小游戏", page="desktop")
            return self.open_game()
        if widgets["quick_focus"].collidepoint(pos):
            self.speak_readable("专心，打开专心小钟", page="desktop")
            self.modal = "pomodoro"
            return None
        if widgets["quick_draw"].collidepoint(pos):
            self.speak_readable("画画，打开星宝画板", page="desktop")
            self.modal = "drawing"
            return None
        if widgets["quick_gallery"].collidepoint(pos):
            self.speak_readable("展板，看看我的作品", page="desktop")
            self.modal = "gallery"
            return None

        areas = self.layout()
        if areas["drawer"].collidepoint(pos):
            self.speak_readable("打开小抽屉", page="desktop")
            self.drawer_open = True
        elif areas["memory"].collidepoint(pos):
            self.speak_readable("打开回忆本", page="desktop")
            self.reset_memory_book_position("chat")
            self.modal = "memory"
        elif areas["pet"].collidepoint(pos):
            states = ("happy", "thinking", "yawn")
            state = states[self.xingbao_click_index % len(states)]
            self.xingbao_click_index += 1
            self.set_xingbao_state(state, seconds=4.5)
            messages = {
                "happy": "见到你真开心！",
                "thinking": "星宝正在想一个有趣的问题",
                "yawn": "哈——欠，记得劳逸结合哦",
            }
            self.show_notice(messages[state])
            self.speak_readable(messages[state], page="desktop")
        elif areas["health"].collidepoint(pos):
            self.read_target_at(pos)
            self.modal = "health"
        elif areas["wifi"].collidepoint(pos):
            self.read_target_at(pos)
            self.modal = "network"
        elif areas["volume"].collidepoint(pos):
            self.read_target_at(pos)
            self.modal = "volume"
        elif areas["battery"].collidepoint(pos):
            self.read_target_at(pos)
            self.modal = "battery"
        elif areas["lock"].collidepoint(pos):
            self.speak_readable("锁屏", page="desktop")
            self.modal = "lock_confirm"
        elif areas["parent"].collidepoint(pos):
            self.speak_readable("家长中心", page="desktop")
            if not self.parent_verified:
                self.parent_answer = ""
                if self.parent_lock_remaining() == 0:
                    self.new_parent_question()
            else:
                self.refresh_parent_summaries()
            self.modal = "parent_center" if self.parent_verified else "parent"
        else:
            self.read_target_at(pos)
        return None

    def lock_slider_track_rect(self):
        w, h = self.screen.get_size()
        return pygame.Rect(int(w * 0.27), int(h * 0.55), int(w * 0.46), int(h * 0.085))

    def lock_slider_knob_rect(self):
        track = self.lock_slider_track_rect()
        height = track.height - max(8, int(track.height * 0.16))
        width = max(int(height * 2.4), int(track.width * 0.24))
        left = track.left + max(4, int(track.height * 0.08))
        travel = max(1, track.width - width - max(8, int(track.height * 0.16)))
        return pygame.Rect(
            left + int(travel * self.lock_slider_progress),
            track.centery - height // 2,
            width,
            height,
        )

    def reset_lock_slider(self):
        self.lock_slider_progress = 0.0
        self.lock_slider_dragging = False

    def begin_lock_slider(self, pos):
        track = self.lock_slider_track_rect()
        knob = self.lock_slider_knob_rect()
        if knob.inflate(int(track.height * 0.25), int(track.height * 0.25)).collidepoint(pos):
            self.lock_slider_dragging = True
            return True
        return False

    def update_lock_slider(self, pos):
        if not self.lock_slider_dragging:
            return False
        track = self.lock_slider_track_rect()
        knob = self.lock_slider_knob_rect()
        minimum = track.left + knob.width // 2 + max(4, int(track.height * 0.08))
        maximum = track.right - knob.width // 2 - max(4, int(track.height * 0.08))
        self.lock_slider_progress = max(0.0, min(1.0, (int(pos[0]) - minimum) / max(1, maximum - minimum)))
        if self.lock_slider_progress >= 0.92:
            self.unlock_from_slider()
            return True
        return False

    def finish_lock_slider(self, pos):
        unlocked = self.update_lock_slider(pos)
        if not unlocked:
            self.reset_lock_slider()
        return unlocked

    def unlock_from_slider(self):
        self.locked = False
        self.modal = None
        self.reset_lock_slider()
        self.speak_readable("欢迎回来", page="locked")
        self.show_notice("欢迎回来")

    def draw_drawer(self):
        w, h = self.screen.get_size()
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((65, 43, 27, 48))
        self.screen.blit(shade, (0, 0))
        panel = pygame.Rect(int(w * 0.03), int(h * 0.56), int(w * 0.38), int(h * 0.35))
        rounded_panel(self.screen, panel, (255, 244, 218), radius=28)
        draw_text(self.screen, "小抽屉", (panel.centerx, int(h * 0.61)), int(h * 0.04), bold=True)
        self.register_read_target(panel, "小抽屉。选一个你想玩的吧。", page="drawer")

        buttons = [
            ("百宝箱", self.drawer_buttons()["toolbox"]),
            ("一起玩", self.drawer_buttons()["game"]),
            ("护眼休息", self.drawer_buttons()["rest"]),
            ("主动陪伴", self.drawer_buttons()["companion"]),
        ]
        for index, (label, rect) in enumerate(buttons):
            selected = index == self.drawer_focus
            rounded_panel(
                self.screen,
                rect,
                (255, 214, 105) if selected else (255, 251, 235),
                border=(205, 136, 62),
                radius=16,
                width=3 if selected else 2,
            )
            draw_text(self.screen, label, rect.center, int(h * 0.027), bold=selected)
            self.register_read_target(rect, label, page="drawer")

        draw_text(self.screen, "选一个你想玩的吧", (panel.centerx, int(h * 0.895)), int(h * 0.017), color=(126, 92, 63))

    def modal_read_text(self):
        if self.modal == "memory":
            if self.memory_tab == "chat":
                records = self.memory_chat_records()
                if not records:
                    return "回忆本还没有聊天记录。以后和星宝说过的话会住在这里。"
                return "回忆本聊天记录，共{}条。上下滑动寻找，点一条就能听。".format(len(records))
            memories = self.memory_growth_records()
            if not memories:
                return "回忆本还没有成长记录。玩游戏、画画和休息的小故事会住在这里。"
            return "回忆本成长记录，共{}条。上下滑动寻找，点一条可以听详情。".format(len(memories))
        if self.modal == "memory_detail":
            entry = self.selected_memory or {}
            return "{}。{}".format(self.child_memory_title(entry), self.child_memory_summary(entry))
        if self.modal in ("health", "rest"):
            if self.modal == "rest" and self.rest_started_at is not None:
                remaining = max(0, 20 - int(time.monotonic() - self.rest_started_at))
                return "护眼休息，还剩{}秒。看看远处，慢慢眨眼。".format(remaining)
            return "护眼小提醒。坐直一点，小肩膀放松，眼睛离屏幕远一点。"
        if self.modal == "parent":
            remaining = self.parent_lock_remaining()
            if remaining > 0:
                return "家长验证已暂时锁定，还剩{}秒。儿童桌面仍然可以正常使用。".format(
                    remaining
                )
            return "家长验证。请选择正确结果，题目是{}。".format(self.parent_question["text"])
        if self.modal == "parent_center":
            return "家长设置。当前音量{}%。天气城市是{}，可以修改；也可以打开孩子近况查看非敏感总结，或最小化程序。".format(self.volume, self.weather_city)
        if self.modal == "weather_city":
            return "设置天气城市。当前城市是{}。请选择一个城市，星宝查询天气时会使用它。".format(self.weather_city)
        if self.modal == "parent_summaries":
            count = len(self.parent_summary_backend.load())
            return "成长记忆报告，共{}项非敏感记忆。内容已经按类别直接展示，上下滑动可以查看，移除后不再用于后续对话。".format(count)
        if self.modal == "network":
            return "网络已连接，星宝可以上网啦。" if self.network["online"] else "当前离线。没有网络也可以玩小游戏。"
        if self.modal == "volume":
            return "声音大小，当前音量{}%。保持舒适音量，保护听力。".format(self.volume)
        if self.modal == "battery":
            return "小电池，电量{}%。{}".format(self.battery["percent"], self.battery["detail"])
        if self.modal == "lock_confirm":
            return "确认锁屏。锁屏后需要再次点击才能返回。"
        if self.modal == "locked":
            return "星宝休息中。点击屏幕或按确认键唤醒。"
        if self.modal == "toolbox":
            return "百宝箱。今天想玩哪个小工具？可以选专心小钟，也可以选画板。"
        if self.modal == "companion":
            state = "已开启" if self.active_companion else "已关闭"
            return "主动陪伴{}。Kimi场景识别{}，点击开关可以控制它。".format(state, state)
        if self.modal == "pomodoro":
            minutes, seconds = divmod(self.pomodoro_remaining(), 60)
            return "专心小钟，还剩{}分{}秒。完成可以获得积分。".format(minutes, seconds)
        if self.modal == "drawing":
            return "星宝画板。可以在中间画画，画好后点画好啦。"
        if self.modal == "rewards":
            reward = self.store.reward_level()
            return "我的积分。成长第{}级，当前有{}积分。".format(reward["level"], self.store.data["points"])
        if self.modal == "gallery":
            artworks = self.recent_artworks()
            return "小小展板。" + ("这里有{}幅作品。".format(len(artworks)) if artworks else "展板还是空的，去画第一幅作品吧。")
        if self.modal == "artwork_view":
            entry = self.selected_artwork or {}
            return "我的作品，{}。".format(entry.get("title", "星宝画作"))
        return "星宝正在这里陪你。"

    def draw_modal(self):
        if not self.modal:
            return
        w, h = self.screen.get_size()
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((54, 36, 22, 150 if self.modal == "locked" else 92))
        self.screen.blit(shade, (0, 0))
        rect, close, action = self.modal_geometry()
        if self.modal == "parent_summaries":
            rounded_panel(
                self.screen,
                rect,
                (244, 246, 249),
                border=(174, 181, 190),
                radius=22,
                width=2,
            )
        else:
            rounded_panel(self.screen, rect, (255, 249, 232), radius=30)
        titles = {
            "memory": "回忆本",
            "memory_detail": "这段记忆",
            "health": "护眼小提醒",
            "parent": "家长验证",
            "parent_center": "家长设置",
            "weather_city": "天气城市",
            "parent_summaries": "成长记忆报告",
            "rest": "休息一下",
            "network": "网络",
            "volume": "声音大小",
            "battery": "小电池",
            "lock_confirm": "确认锁屏？",
            "locked": "星宝休息中",
            "toolbox": "百宝箱",
            "companion": "主动陪伴",
            "pomodoro": "专心小钟",
            "drawing": "星宝画板",
            "rewards": "我的积分",
            "gallery": "小小展板",
            "artwork_view": "我的作品",
        }
        draw_text(
            self.screen,
            titles[self.modal],
            (rect.centerx, int(h * (0.18 if self.modal == "memory" else 0.25))),
            int(h * 0.043),
            color=(45, 55, 66) if self.modal == "parent_summaries" else (91, 55, 31),
            bold=True,
        )
        # The drawing canvas must receive touch strokes directly.  Do not
        # register the whole modal as a read-aloud target, otherwise a tap on
        # the canvas speaks its introduction instead of drawing.
        if self.modal != "drawing":
            self.register_read_target(rect, self.modal_read_text(), page=self.modal)

        def button(label, box, selected=False):
            rounded_panel(self.screen, box, (255, 215, 112) if selected else (255, 252, 239),
                          border=(205, 136, 62), radius=16, width=3 if selected else 2)
            draw_text(self.screen, label, box.center, int(h * 0.025), bold=selected)

        if self.modal == "memory":
            tabs = self.memory_tab_rects()
            button("聊天记录", tabs["chat"], self.memory_tab == "chat")
            button("成长记录", tabs["growth"], self.memory_tab == "growth")
            rendered_scroll = self.current_memory_scroll_render()
            if self.memory_tab == "chat":
                records = self.memory_chat_records()
                visible, first_row_offset, row_shift_units = self.chat_records_for_render(
                    rendered_scroll
                )
                chat_canvas = pygame.Rect(
                    int(w * 0.295), int(h * 0.315), int(w * 0.41), int(h * 0.47)
                )
                rounded_panel(
                    self.screen,
                    chat_canvas,
                    (238, 238, 238),
                    border=(213, 213, 213),
                    radius=10,
                    width=1,
                )
                if not visible:
                    draw_text(self.screen, "还没有聊天记录", (rect.centerx, int(h * 0.46)), int(h * 0.030), bold=True)
                    draw_text(self.screen, "之后你和星宝说过的话会按顺序显示在这里", (rect.centerx, int(h * 0.53)), int(h * 0.019), color=(104, 104, 104))
                chat_rows = self.chat_record_rects()
                chat_step = chat_rows[1].y - chat_rows[0].y
                first_row = chat_rows[0].move(0, first_row_offset * chat_step)
                chat_shift = int(row_shift_units * chat_step)
                previous_clip = self.screen.get_clip()
                self.screen.set_clip(chat_canvas)
                for index, entry in enumerate(visible):
                    row = first_row.move(0, index * chat_step + chat_shift)
                    is_child = entry.get("role") == "child"
                    bubble = self.chat_bubble_rect(entry, row)
                    avatar_center = (
                        row.right - int(w * 0.020),
                        bubble.centery,
                    ) if is_child else (
                        row.x + int(w * 0.020),
                        bubble.centery,
                    )
                    pygame.draw.circle(
                        self.screen,
                        (94, 125, 155) if is_child else (74, 150, 126),
                        avatar_center,
                        int(h * 0.020),
                    )
                    draw_text(
                        self.screen,
                        "我" if is_child else "星",
                        avatar_center,
                        int(h * 0.016),
                        color=(255, 255, 255),
                        bold=True,
                    )
                    rounded_panel(
                        self.screen,
                        bubble,
                        (149, 236, 105) if is_child else (255, 255, 255),
                        border=(133, 211, 91) if is_child else (220, 220, 220),
                        radius=8,
                        width=1,
                    )
                    draw_wrapped_text(
                        self.screen,
                        str(entry.get("content", "")),
                        bubble.inflate(-int(w * 0.018), -int(h * 0.010)),
                        size=int(h * 0.016),
                        color=(42, 42, 42),
                        line_gap=1,
                        max_lines=2,
                    )
                    timestamp = format_memory_timestamp(entry.get("timestamp"))
                    draw_text(
                        self.screen,
                        timestamp,
                        (row.centerx, row.y + int(h * 0.009)),
                        int(h * 0.010),
                        color=(132, 132, 132),
                    )
                self.screen.set_clip(previous_clip)
                draw_text(
                    self.screen,
                    "共{}条  ·  上下滑动查找  ·  点击气泡即可点读".format(len(records)),
                    (rect.centerx, rect.bottom - int(h * 0.035)),
                    int(h * 0.015), color=(102, 102, 102),
                )
            else:
                memories = self.memory_growth_records()
                visible, first_card_offset, card_shift_units = self.growth_records_for_render(
                    rendered_scroll
                )
                if not visible:
                    draw_text(self.screen, "还没有成长记录", (rect.centerx, int(h * 0.46)), int(h * 0.030), bold=True)
                    draw_text(self.screen, "玩游戏、画画和休息的小故事会住在这里", (rect.centerx, int(h * 0.53)), int(h * 0.021), color=(125, 91, 62))
                memory_cards = self.memory_entry_rects()
                memory_step = memory_cards[1].y - memory_cards[0].y
                first_card = memory_cards[0].move(0, first_card_offset * memory_step)
                memory_shift = int(card_shift_units * memory_step)
                growth_canvas = pygame.Rect(
                    memory_cards[0].x,
                    memory_cards[0].y - int(h * 0.010),
                    memory_cards[0].w,
                    memory_cards[-1].bottom - memory_cards[0].y + int(h * 0.020),
                )
                previous_clip = self.screen.get_clip()
                self.screen.set_clip(growth_canvas)
                for index, entry in enumerate(visible):
                    card = first_card.move(0, index * memory_step + memory_shift)
                    rounded_panel(self.screen, card, (255, 252, 242), border=(219, 177, 123), radius=15, width=2)
                    thumbnail = pygame.Rect(
                        card.x + int(w * 0.007), card.y + int(h * 0.009),
                        int(w * 0.045), card.h - int(h * 0.018))
                    rounded_panel(self.screen, thumbnail.inflate(4, 4), (255, 247, 222), border=(219, 177, 123), radius=9, width=1)
                    self.screen.blit(self.memory_thumbnail(entry, thumbnail.size), thumbnail.topleft)
                    type_names = {"game": "小游戏", "artwork": "我的画", "health": "休息", "learning": "学本领", "story": "故事", "companion": "和星宝玩"}
                    label = type_names.get(entry.get("type"), "记忆")
                    title = "{}·{}".format(label, self.child_memory_title(entry))
                    summary = self.child_memory_summary(entry)
                    if len(summary) > 32:
                        summary = summary[:32] + "…"
                    draw_text(self.screen, title, (card.x + int(w * 0.14), card.y + int(h * 0.030)), int(h * 0.020), bold=True)
                    draw_text(self.screen, summary, (card.x + int(w * 0.17), card.y + int(h * 0.063)), int(h * 0.016), color=(125, 91, 62))
                    timestamp = format_memory_timestamp(entry.get("timestamp"))
                    draw_text(self.screen, timestamp, (card.right - int(w * 0.055), card.y + int(h * 0.030)), int(h * 0.014), color=(125, 91, 62))
                self.screen.set_clip(previous_clip)
                draw_text(
                    self.screen,
                    "星宝记住了{}件小事·上下滑动".format(len(memories)),
                    (rect.centerx, rect.bottom - int(h * 0.035)),
                    int(h * 0.016), color=(125, 91, 62),
                )
        elif self.modal == "memory_detail":
            entry = self.selected_memory or {}
            type_names = {"game": "小游戏", "artwork": "我的画", "health": "休息", "learning": "学本领", "story": "故事", "companion": "和星宝玩"}
            draw_text(self.screen, type_names.get(entry.get("type"), "记忆"), (rect.centerx, int(h * 0.34)), int(h * 0.021), color=(199, 119, 35), bold=True)
            draw_text(self.screen, self.child_memory_title(entry), (rect.centerx, int(h * 0.41)), int(h * 0.032), bold=True)
            summary = self.child_memory_summary(entry)
            for index, line in enumerate((summary[:34], summary[34:68])):
                if line:
                    draw_text(self.screen, line, (rect.centerx, int(h * (0.49 + index * 0.045))), int(h * 0.020), color=(103, 72, 48))
            draw_text(self.screen, "记在{}".format(format_memory_timestamp(entry.get("timestamp"))), (rect.centerx, int(h * 0.59)), int(h * 0.017), color=(125, 91, 62))
            source_names = {"game_center": "小游戏里", "drawing_board": "小画板里", "eye_rest": "护眼休息时", "focus_timer": "专心小钟里"}
            draw_text(self.screen, "这是星宝在{}记住的".format(source_names.get(entry.get("source"), "陪伴时")), (rect.centerx, int(h * 0.63)), int(h * 0.017), color=(125, 91, 62))
            button("返回回忆本", action, True)
        elif self.modal in ("health", "rest"):
            if self.modal == "rest" and self.rest_started_at is not None:
                remaining = max(0, 20 - int(time.monotonic() - self.rest_started_at))
                draw_text(self.screen, str(remaining), (rect.centerx, int(h * 0.43)), int(h * 0.12), color=(219, 139, 49), bold=True)
                draw_text(self.screen, "看看远处，慢慢眨眼", (rect.centerx, int(h * 0.55)), int(h * 0.029), color=(103, 72, 48))
                if remaining == 0:
                    if not self.eye_rest_recorded:
                        self.eye_rest_recorded = True
                        self.store.save(eye_rest_completed=int(self.store.data.get("eye_rest_completed", 0)) + 1)
                        self.store.record_activity("eye_rest", "完成20秒护眼休息", "看看远处，放松眼睛")
                        self.remember("health", "完成护眼休息", "完成20秒远眺与眨眼", "eye_rest")
                        self.show_notice("星宝记住这次休息啦")
                    draw_text(self.screen, "休息完成，眼睛舒服多啦！", (rect.centerx, int(h * 0.65)), int(h * 0.026), bold=True)
            else:
                lines = ["坐直一点，小肩膀放松", "眼睛离屏幕远一点", "玩一会儿，就看看远处"]
                for i, line in enumerate(lines):
                    draw_text(self.screen, line, (rect.centerx, int(h * (0.37 + i * 0.075))), int(h * 0.026), color=(103, 72, 48))
                button("开始20秒护眼休息", action, True)
        elif self.modal == "parent":
            remaining = self.parent_lock_remaining()
            if remaining > 0:
                draw_text(
                    self.screen,
                    "连续两次回答错误",
                    (rect.centerx, int(h * 0.40)),
                    int(h * 0.034),
                    color=(146, 72, 60),
                    bold=True,
                )
                draw_text(
                    self.screen,
                    "{}秒后可以重新验证".format(remaining),
                    (rect.centerx, int(h * 0.51)),
                    int(h * 0.050),
                    bold=True,
                )
                draw_text(
                    self.screen,
                    "只锁定家长入口，儿童桌面仍可正常使用",
                    (rect.centerx, int(h * 0.64)),
                    int(h * 0.021),
                    color=(125, 91, 62),
                )
            else:
                draw_text(self.screen, "请选择正确结果（答案高于200）", (rect.centerx, int(h * 0.34)), int(h * 0.025), color=(103, 72, 48))
                draw_text(self.screen, self.parent_question["text"], (rect.centerx, int(h * 0.42)), int(h * 0.050), bold=True)
                for label, rx in zip(self.parent_question["choices"], (0.32, 0.45, 0.58)):
                    button(str(label), pygame.Rect(int(w * rx), int(h * 0.50), int(w * 0.10), int(h * 0.10)))
                typed = self.parent_answer if self.parent_answer else "也可用数字键输入后按回车"
                draw_text(self.screen, typed, (rect.centerx, int(h * 0.66)), int(h * 0.021), color=(125, 91, 62), bold=bool(self.parent_answer))
        elif self.modal == "parent_center":
            draw_text(self.screen, "护眼提醒：20分钟", (rect.centerx, int(h * 0.35)), int(h * 0.027))
            draw_text(self.screen, "内容安全：儿童模式", (rect.centerx, int(h * 0.42)), int(h * 0.027))
            button("−", pygame.Rect(int(w * 0.36), int(h * 0.53), int(w * 0.08), int(h * 0.09)))
            draw_text(self.screen, "音量{}%".format(self.volume), (rect.centerx, int(h * 0.575)), int(h * 0.030), bold=True)
            button("+", pygame.Rect(int(w * 0.56), int(h * 0.53), int(w * 0.08), int(h * 0.09)))
            button("天气城市：{}".format(self.weather_city), pygame.Rect(int(w * 0.38), int(h * 0.65), int(w * 0.24), int(h * 0.06)), True)
            button("查看孩子近况", pygame.Rect(int(w * 0.38), int(h * 0.72), int(w * 0.24), int(h * 0.06)), True)
            button("最小化程序", pygame.Rect(int(w * 0.38), int(h * 0.80), int(w * 0.24), int(h * 0.06)), True)
            draw_text(self.screen, "仅展示非敏感信息·所有数据保存在本机", (rect.centerx, int(h * 0.47)), int(h * 0.017), color=(125, 91, 62))
        elif self.modal == "weather_city":
            draw_text(self.screen, "当前城市：{}".format(self.weather_city), (rect.centerx, int(h * 0.285)), int(h * 0.024), color=(103, 72, 48), bold=True)
            for city, box in self.weather_city_rects().items():
                button(city, box, city == self.weather_city)
            draw_text(self.screen, "用于天气查询；不会获取设备位置", (rect.centerx, int(h * 0.660)), int(h * 0.017), color=(125, 91, 62))
        elif self.modal == "parent_summaries":
            summaries = self.parent_report_entries()
            rendered_scroll = self.current_parent_summary_scroll_render()
            visible, row_shift_units = self.parent_summaries_for_render(rendered_scroll)
            report = pygame.Rect(
                int(w * 0.278), int(h * 0.315), int(w * 0.444), int(h * 0.395)
            )
            rounded_panel(
                self.screen,
                report,
                (249, 250, 252),
                border=(194, 200, 207),
                radius=10,
                width=1,
            )
            draw_text(
                self.screen,
                "由星宝本地记忆库整理  ·  仅展示非敏感信息",
                (report.centerx, int(h * 0.337)),
                int(h * 0.014),
                color=(99, 108, 117),
            )
            if not visible:
                draw_text(self.screen, "目前还没有可整理的记忆", (rect.centerx, int(h * 0.46)), int(h * 0.027), bold=True)
                draw_text(self.screen, "继续聊天和游戏后，兴趣、表达与成长变化会直接呈现在这里", (rect.centerx, int(h * 0.53)), int(h * 0.017), color=(99, 108, 117))
            category_names = {
                "memories": "留下的记忆",
                "interests": "兴趣与爱好",
                "preferences": "互动偏好",
                "chat_habits": "沟通与表达",
                "conversation_style": "沟通与表达",
                "answer_performance": "学习与作答",
                "play_time": "使用与游玩",
                "recent_change": "近期观察",
            }
            report_rows = self.parent_summary_rects()
            row_step = report_rows[1].y - report_rows[0].y
            report_rows.append(report_rows[-1].move(0, row_step))
            # Scroll only inside the card body.  Clipping to the full report
            # panel let the outgoing first row draw over the fixed heading
            # while easing upward, which looked like it overflowed above the
            # report page.
            report_content_viewport = pygame.Rect(
                report.x,
                report_rows[0].y,
                report.width,
                report.bottom - report_rows[0].y,
            )
            # The category separator ends with the final visible row.  At the
            # end of a short report it must not extend into the unused lower
            # part of the panel.
            if visible:
                last_row_index = min(len(visible) - 1, len(report_rows) - 1)
                last_row = report_rows[last_row_index].move(
                    0, int(row_shift_units * row_step)
                )
                divider_bottom = min(
                    report_content_viewport.bottom,
                    max(report_content_viewport.top, last_row.bottom),
                )
            else:
                divider_bottom = report_content_viewport.top
            pygame.draw.line(
                self.screen,
                (208, 213, 219),
                (int(w * 0.395), report_content_viewport.top),
                (int(w * 0.395), divider_bottom),
                1,
            )
            previous_clip = self.screen.get_clip()
            self.screen.set_clip(report_content_viewport)
            for index, (entry, base_row) in enumerate(zip(visible, report_rows)):
                row = base_row.move(0, int(row_shift_units * row_step))
                # Draw the top edge for every row, including the first one.
                # That keeps the topmost visible entry enclosed after scroll.
                pygame.draw.line(
                    self.screen,
                    (222, 225, 229),
                    (row.x + int(w * 0.012), row.y),
                    (row.right - int(w * 0.012), row.y),
                    1,
                )
                delete = self.summary_delete_rect(row)
                title = str(entry.get("title", "孩子近况"))
                content = str(entry.get("content", ""))
                draw_text(
                    self.screen,
                    category_names.get(entry.get("category"), "成长观察"),
                    (row.x + int(w * 0.055), row.centery),
                    int(h * 0.015),
                    color=(66, 79, 92),
                    bold=True,
                )
                draw_wrapped_text(
                    self.screen,
                    "{}：{}".format(title, content),
                    pygame.Rect(
                        int(w * 0.407),
                        row.y + int(h * 0.010),
                        int(w * 0.245),
                        row.h - int(h * 0.016),
                    ),
                    size=int(h * 0.014),
                    color=(48, 54, 61),
                    line_gap=1,
                    max_lines=2,
                )
                pygame.draw.rect(
                    self.screen,
                    (226, 229, 233),
                    delete,
                    width=1,
                    border_radius=8,
                )
                draw_text(
                    self.screen,
                    "移除",
                    delete.center,
                    int(h * 0.013),
                    color=(108, 113, 120),
                )
                # Close every row explicitly.  Without this lower boundary,
                # the final visible entry visually merged with the blank area
                # below it and appeared taller than the entries above.
                pygame.draw.line(
                    self.screen,
                    (222, 225, 229),
                    (row.x + int(w * 0.012), row.bottom),
                    (row.right - int(w * 0.012), row.bottom),
                    1,
                )
            self.screen.set_clip(previous_clip)
            draw_text(
                self.screen,
                "共 {} 项，向上或向下滑动查看 · 移除后不再用于后续对话".format(
                    len(summaries)
                ),
                (rect.centerx, int(h * 0.755)),
                int(h * 0.014),
                color=(99, 108, 117),
            )
        elif self.modal == "network":
            network_text = "网络已连接" if self.network["online"] else "当前离线"
            draw_text(self.screen, network_text, (rect.centerx, int(h * 0.40)), int(h * 0.040), color=(73, 143, 104), bold=True)
            detail = "星宝可以上网啦" if self.network["online"] else "没有网络也没关系"
            draw_text(self.screen, detail, (rect.centerx, int(h * 0.47)), int(h * 0.021), color=(125, 91, 62))
            draw_text(self.screen, "没有网络也可以玩小游戏", (rect.centerx, int(h * 0.52)), int(h * 0.026), color=(103, 72, 48))
        elif self.modal == "volume":
            draw_text(self.screen, "{}%".format(self.volume), (rect.centerx, int(h * 0.39)), int(h * 0.060), bold=True)
            button("−", pygame.Rect(int(w * 0.35), int(h * 0.48), int(w * 0.10), int(h * 0.11)))
            button("+", pygame.Rect(int(w * 0.55), int(h * 0.48), int(w * 0.10), int(h * 0.11)))
            draw_text(self.screen, "保持舒适音量，保护听力", (rect.centerx, int(h * 0.66)), int(h * 0.024), color=(103, 72, 48))
        elif self.modal == "battery":
            draw_text(self.screen, "电量{}%".format(self.battery["percent"]), (rect.centerx, int(h * 0.42)), int(h * 0.050), color=(73, 143, 104), bold=True)
            draw_text(self.screen, self.battery["detail"], (rect.centerx, int(h * 0.55)), int(h * 0.027), color=(103, 72, 48))
        elif self.modal == "lock_confirm":
            draw_text(self.screen, "锁屏后需要再次点击才能返回", (rect.centerx, int(h * 0.43)), int(h * 0.027), color=(103, 72, 48))
            button("确认锁屏", action, True)
        elif self.modal == "locked":
            draw_text(self.screen, "向右滑动唤醒", (rect.centerx, int(h * 0.46)), int(h * 0.030), color=(103, 72, 48), bold=True)
            track = self.lock_slider_track_rect()
            pygame.draw.rect(self.screen, (225, 213, 193), track, border_radius=track.height // 2)
            pygame.draw.rect(self.screen, (255, 253, 245), track, width=2, border_radius=track.height // 2)
            fill = pygame.Rect(track.left, track.top, int(track.width * self.lock_slider_progress), track.height)
            if fill.width:
                pygame.draw.rect(self.screen, (255, 202, 103), fill, border_radius=track.height // 2)
            knob = self.lock_slider_knob_rect()
            pygame.draw.rect(self.screen, (255, 240, 194), knob, border_radius=knob.height // 2)
            pygame.draw.rect(self.screen, (205, 136, 62), knob, width=2, border_radius=knob.height // 2)
            draw_text(self.screen, "向右滑动", knob.center, int(h * 0.017), color=(112, 70, 37), bold=True)
            draw_text(self.screen, "→", (track.right - int(track.height * 0.25), track.centery), int(h * 0.030), color=(151, 119, 77), bold=True)
        elif self.modal == "toolbox":
            draw_text(self.screen, "今天想玩哪个小工具？", (rect.centerx, int(h * 0.35)), int(h * 0.026), color=(103, 72, 48))
            button("专心小钟", pygame.Rect(int(w * 0.31), int(h * 0.43), int(w * 0.17), int(h * 0.10)), True)
            button("画板", pygame.Rect(int(w * 0.52), int(h * 0.43), int(w * 0.17), int(h * 0.10)))
            draw_text(self.screen, "星宝会提醒你坐远一点、喝喝水", (rect.centerx, int(h * 0.64)), int(h * 0.020), color=(125, 91, 62))
        elif self.modal == "companion":
            draw_text(self.screen, "Kimi 场景识别", (rect.centerx, int(h * 0.39)), int(h * 0.030), color=(103, 72, 48), bold=True)
            toggle = self.companion_toggle_rect()
            track_color = (101, 184, 117) if self.active_companion else (186, 177, 163)
            pygame.draw.rect(self.screen, track_color, toggle, border_radius=toggle.height // 2)
            pygame.draw.rect(self.screen, (255, 255, 255), toggle, width=2, border_radius=toggle.height // 2)
            knob_radius = max(1, toggle.height // 2 - 5)
            knob_x = toggle.right - toggle.height // 2 if self.active_companion else toggle.left + toggle.height // 2
            pygame.draw.circle(self.screen, (255, 255, 255), (knob_x, toggle.centery), knob_radius)
            draw_text(self.screen, "ON" if self.active_companion else "OFF", (rect.centerx, int(h * 0.56)), int(h * 0.027), color=(73, 143, 104) if self.active_companion else (125, 91, 62), bold=True)
            detail = "已开启 Kimi 场景识别，星宝会根据场景主动陪伴" if self.active_companion else "Kimi 场景识别已关闭，不会发送场景识别请求"
            draw_text(self.screen, detail, (rect.centerx, int(h * 0.64)), int(h * 0.020), color=(125, 91, 62))
        elif self.modal == "pomodoro":
            remaining = self.pomodoro_remaining()
            minutes, seconds = divmod(remaining, 60)
            draw_text(self.screen, "{:02d}:{:02d}".format(minutes, seconds), (rect.centerx, int(h * 0.43)), int(h * 0.085), color=(219, 139, 49), bold=True)
            if remaining == 0:
                draw_text(self.screen, "专心完成，做得真棒！", (rect.centerx, int(h * 0.56)), int(h * 0.027), bold=True)
            else:
                draw_text(self.screen, "完成可获得50积分", (rect.centerx, int(h * 0.56)), int(h * 0.024), color=(103, 72, 48), bold=True)
            start = pygame.Rect(int(w * 0.34), int(h * 0.64), int(w * 0.14), int(h * 0.075))
            reset = pygame.Rect(int(w * 0.52), int(h * 0.64), int(w * 0.14), int(h * 0.075))
            button("暂停" if self.pomodoro_started_at is not None else "开始", start, self.pomodoro_started_at is not None)
            button("重新开始", reset)
        elif self.modal == "drawing":
            canvas = self.drawing_rect()
            rounded_panel(self.screen, canvas, (255, 253, 244), border=(219, 177, 123), radius=12, width=2)
            self.screen.blit(self.ensure_drawing_surface(), canvas.topleft)
            draw_text(self.screen, "画好一幅，可以得到30积分", (int(w * 0.385), int(h * 0.73)), int(h * 0.018), color=(125, 91, 62))
            finish = pygame.Rect(int(w * 0.49), int(h * 0.70), int(w * 0.10), int(h * 0.055))
            clear = pygame.Rect(int(w * 0.60), int(h * 0.70), int(w * 0.09), int(h * 0.055))
            button("画好啦", finish)
            button("清空", clear)
        elif self.modal == "rewards":
            reward = self.store.reward_level()
            points = self.store.data["points"]
            draw_text(self.screen, "{}积分·成长第{}级".format(points, reward["level"]), (rect.centerx, int(h * 0.36)), int(h * 0.040), color=(199, 119, 35), bold=True)
            bar = pygame.Rect(int(w * 0.34), int(h * 0.42), int(w * 0.32), int(h * 0.026))
            pygame.draw.rect(self.screen, (232, 218, 185), bar, border_radius=bar.h // 2)
            fill = pygame.Rect(bar.x, bar.y, int(bar.w * reward["progress"] / reward["next"]), bar.h)
            if fill.w:
                pygame.draw.rect(self.screen, (239, 176, 61), fill, border_radius=bar.h // 2)
            draw_text(self.screen, "再得{}积分，星宝就长大一级啦".format(reward["next"] - reward["progress"]), (rect.centerx, int(h * 0.49)), int(h * 0.021), color=(103, 72, 48))
            draw_text(self.screen, "专心{}次   画了{}幅".format(
                self.store.data["focus_completed"], self.store.data["drawings_completed"]),
                (rect.centerx, int(h * 0.57)), int(h * 0.024), bold=True)
            history = self.store.data.get("reward_history", [])
            latest = history[-1] if history else None
            latest_text = "刚刚因为{}得到{}积分".format(latest["reason"], latest["amount"]) if latest else "玩游戏、专心和画画都能得积分"
            draw_text(self.screen, latest_text, (rect.centerx, int(h * 0.65)), int(h * 0.021), color=(125, 91, 62))
            draw_text(self.screen, "专心完成+50 · 5颗星星+25 · 画好一幅+30", (rect.centerx, int(h * 0.72)), int(h * 0.019), color=(125, 91, 62))
        elif self.modal == "gallery":
            artworks = self.recent_artworks()
            boxes = self.gallery_artwork_rects()
            if not artworks:
                draw_text(self.screen, "展板还是空的，去画下第一幅作品吧！", (rect.centerx, int(h * 0.43)), int(h * 0.027), color=(103, 72, 48), bold=True)
            for entry, box in zip(artworks, boxes):
                rounded_panel(self.screen, box, (255, 252, 240), border=(205, 150, 87), radius=14, width=2)
                image_rect = pygame.Rect(box.x + int(w * 0.008), box.y + int(h * 0.012), box.w - int(w * 0.016), int(h * 0.14))
                self.screen.blit(self.artwork_image(entry, image_rect.size), image_rect.topleft)
                draw_text(self.screen, entry.get("title", "星宝画作"), (box.centerx, box.bottom - int(h * 0.038)), int(h * 0.016), bold=True)
                draw_text(self.screen, format_gallery_date(entry.get("time")), (box.centerx, box.bottom - int(h * 0.014)), int(h * 0.013), color=(125, 91, 62))
            activities = self.store.data.get("activity_history", [])
            focus_count = self.store.data.get("focus_completed", 0)
            eye_count = self.store.data.get("eye_rest_completed", 0)
            draw_text(self.screen, "我做到了：专心{}次 · 休息{}次 · 画画{}幅".format(focus_count, eye_count, len(self.store.data.get("artworks", []))), (rect.centerx, int(h * 0.63)), int(h * 0.022), bold=True)
            if activities:
                latest = activities[-1]
                draw_text(self.screen, "最近：{}  {}".format(latest.get("title", ""), format_gallery_date(latest.get("time"))), (rect.centerx, int(h * 0.69)), int(h * 0.018), color=(125, 91, 62))
        elif self.modal == "artwork_view":
            entry = self.selected_artwork or {}
            image_rect = pygame.Rect(int(w * 0.32), int(h * 0.32), int(w * 0.36), int(h * 0.35))
            rounded_panel(self.screen, image_rect.inflate(int(w * 0.016), int(h * 0.025)), (255, 252, 240), border=(205, 150, 87), radius=14, width=2)
            self.screen.blit(self.artwork_image(entry, image_rect.size), image_rect.topleft)
            draw_text(self.screen, "画在{}".format(format_gallery_date(entry.get("time"))), (rect.centerx, int(h * 0.72)), int(h * 0.019), color=(125, 91, 62))

        if self.modal != "locked":
            rounded_panel(self.screen, close, (255, 225, 159), radius=16, width=2)
            draw_text(self.screen, "关闭", close.center, int(h * 0.022), bold=True)
            self.register_read_target(close, "关闭", page=self.modal)

    def draw_dynamic_status(self):
        w, h = self.screen.get_size()
        # The board RTC is eight hours behind the presentation time.  This is
        # display-only; timers continue to use time.monotonic().
        now = datetime.now() + timedelta(hours=8)
        weekdays = "一二三四五六日"
        distance_alert = self.vision_state.get("distance_too_close") == 1
        water_alert = self.vision_state.get("needs_water") == 1
        time_text = now.strftime("%H:%M")
        date_text = "{}月{}日  星期{}".format(now.month, now.day, weekdays[now.weekday()])
        if distance_alert:
            health_text = "坐得太近啦"
        elif water_alert:
            health_text = "该喝水啦，休息一下"
        elif self.vision_state.get("available"):
            health_text = "坐得刚刚好"
        else:
            health_text = "星宝正在看看你坐得好不好"
        time_size = int(h * 0.037)
        date_size = int(h * 0.023)
        health_size = int(h * 0.019)
        time_center_x = int(w * 0.047)
        gap = max(int(w * 0.014), int(h * 0.016))
        time_width = font(time_size, bold=True).size(time_text)[0]
        date_width = font(date_size).size(date_text)[0]
        health_width = font(health_size, bold=distance_alert or water_alert).size(health_text)[0]
        health_icon_width = max(1, round(40 * h / TOP_STATUS_SOURCE_SIZE[1]))
        health_icon_height = max(1, round(42 * h / TOP_STATUS_SOURCE_SIZE[1]))
        health_icon_gap = max(5, int(h * 0.009))
        health_group_width = health_icon_width + health_icon_gap + health_width
        date_center_x = time_center_x + time_width // 2 + gap + date_width // 2
        health_center_x = date_center_x + date_width // 2 + gap + health_group_width // 2
        health_text_center_x = health_center_x + health_group_width // 2 - health_width // 2
        health_icon_x = health_center_x - health_group_width // 2
        # The source wallpaper contains a fixed screenshot of the whole header.
        # Cover it first, then paint live text and the extracted static elements
        # independently.  This prevents the old 08:30/date/battery values from
        # showing through whenever the display changes.
        area = pygame.Rect(0, 0, w, int(h * 0.087))
        cover = pygame.Surface(area.size, pygame.SRCALPHA)
        cover.fill((255, 222, 184, 255) if (distance_alert or water_alert) else (250, 232, 199, 255))
        self.screen.blit(cover, area.topleft)
        draw_text(self.screen, time_text, (time_center_x, int(h * 0.043)), time_size, bold=True)
        draw_text(self.screen, date_text, (date_center_x, int(h * 0.043)), date_size)
        health_color = (220, 58, 58) if distance_alert else ((128, 61, 36) if water_alert else (91, 55, 31))
        draw_text(self.screen, health_text, (health_text_center_x, int(h * 0.043)), health_size, color=health_color, bold=distance_alert or water_alert)
        self.draw_top_status_asset(
            "health_icon",
            topleft=(health_icon_x, int(h * 0.043) - health_icon_height // 2),
        )
        for key in (
            "left_divider", "brand", "wifi", "volume", "battery_text", "battery", "lock",
            "divider", "parent_icon", "parent_text",
        ):
            self.draw_top_status_asset(key)
        left_area = pygame.Rect(0, 0, health_center_x + health_width // 2 + gap, area.height)
        self.register_read_target(left_area, "{}，{}。{}".format(time_text, date_text, health_text), page="desktop")

    def draw_xingbao_animation(self):
        w, h = self.screen.get_size()
        pet = self.layout()["pet"]
        scene_rect = pygame.Rect(0, 0, int(w * 0.44), int(h * 0.43))
        scene_rect.center = pet.center
        if self.scene_animator.draw(self.screen, scene_rect, pygame.time.get_ticks()):
            return
        t = pygame.time.get_ticks() / 1000.0
        state = self.xingbao_state()
        pulse = (math.sin(t * 2.4) + 1.0) / 2.0
        if self.animation_overlay is None or self.animation_overlay_size != (w, h):
            self.animation_overlay = pygame.Surface((w, h), pygame.SRCALPHA)
            self.animation_overlay_size = (w, h)
        overlay = self.animation_overlay
        overlay.fill((0, 0, 0, 0))
        palette = {
            "alert": (244, 137, 71), "thinking": (103, 181, 184), "yawn": (132, 158, 199),
            "happy": (255, 172, 76), "celebrate": (245, 134, 167), "blink": (255, 194, 62),
            "idle": (255, 194, 62),
        }
        color = palette.get(state, (255, 194, 62))
        speed = 1.2 if state == "yawn" else 2.4
        pulse = (math.sin(t * speed) + 1.0) / 2.0
        radius = int(min(w, h) * (0.115 + pulse * (0.013 if state in ("happy", "celebrate") else 0.008)))
        shadow = pygame.Rect(pet.centerx - int(w * 0.065), pet.centery + int(h * 0.115), int(w * 0.13), int(h * 0.035))
        pygame.draw.ellipse(overlay, (112, 77, 47, 35), shadow)
        pygame.draw.circle(overlay, color + (35 + int(pulse * 30),), pet.center, radius, width=max(2, int(h * 0.004)))
        particle_count = 10 if state == "celebrate" else 7 if state == "happy" else 5
        orbit_speed = 1.1 if state in ("happy", "celebrate") else 0.65
        for index in range(particle_count):
            angle = t * orbit_speed + index * math.tau / particle_count
            orbit = radius + int(h * 0.025)
            point = (int(pet.centerx + math.cos(angle) * orbit), int(pet.centery + math.sin(angle) * orbit * 0.62))
            dot = max(3, int(h * (0.005 + 0.002 * math.sin(t * 3 + index))))
            pygame.draw.circle(overlay, color + (150,), point, dot)

        if state == "yawn":
            for index in range(3):
                cloud_x = pet.right + int(w * (0.012 + index * 0.016))
                cloud_y = pet.y + int(h * (0.03 - index * 0.018 + math.sin(t * 1.8 + index) * 0.006))
                pygame.draw.circle(overlay, (185, 205, 222, 150 - index * 25), (cloud_x, cloud_y), int(h * (0.009 + index * 0.003)))
        elif state == "thinking":
            for index in range(3):
                point = (pet.right + int(w * (0.006 + index * 0.013)), pet.y + int(h * (0.06 - index * 0.025)))
                pygame.draw.circle(overlay, (103, 181, 184, 145), point, int(h * (0.007 + index * 0.003)), width=max(2, int(h * 0.003)))
        elif state == "celebrate":
            for index in range(8):
                x = pet.x - int(w * 0.04) + int((index / 7) * (pet.w + w * 0.08))
                y = pet.y - int(h * (0.01 + 0.03 * ((index * 3) % 4))) + int(math.sin(t * 4 + index) * h * 0.012)
                pygame.draw.circle(overlay, (245, 134 + index * 6, 100 + index * 10, 180), (x, y), max(3, int(h * 0.006)))
        self.screen.blit(overlay, (0, 0))

        lobster_state = {
            "thinking": "thinking", "yawn": "laptop", "celebrate": "celebrate",
            "happy": "celebrate", "alert": "laptop", "blink": "wave", "idle": "wave",
        }.get(state, "wave")
        lobster_source = self.lobster_sprites.get(lobster_state)
        if lobster_source is not None:
            target_height = int(h * 0.43)
            scale = target_height / lobster_source.get_height()
            target_size = (max(1, round(lobster_source.get_width() * scale)), max(1, target_height))
            cache_key = (lobster_state, target_size)
            sprite = self.scaled_lobster_sprites.get(cache_key)
            if sprite is None:
                sprite = pygame.transform.smoothscale(lobster_source, target_size)
                self.scaled_lobster_sprites[cache_key] = sprite
            float_y = int(math.sin(t * 2.0) * h * 0.006)
            sprite_rect = sprite.get_rect(center=(pet.centerx, pet.centery + float_y))
            self.screen.blit(sprite, sprite_rect)
        else:
            frame_state = {
                "yawn": "yawn", "thinking": "thinking", "celebrate": "celebrate",
                "happy": "celebrate", "alert": "idle", "blink": "idle", "idle": "idle",
            }.get(state, "idle")
            fps = 3.5 if frame_state == "celebrate" else 2.6 if frame_state == "yawn" else 2.0
            frame_index = int(t * fps) % 4
            target_size = int(h * 0.44)
            cache_key = (frame_state, frame_index, target_size)
            sprite = self.scaled_xingbao_frames.get(cache_key)
            if sprite is None:
                sprite = pygame.transform.smoothscale(self.xingbao_frames[frame_state][frame_index], (target_size, target_size))
                self.scaled_xingbao_frames[cache_key] = sprite
            sprite_rect = sprite.get_rect(center=pet.center)
            self.screen.blit(sprite, sprite_rect)

        bubble_messages = {
            "thinking": "星宝正在想一个好点子",
            "yawn": "哈——欠…一起休息一下吧",
            "happy": "今天也要开心探索呀",
            "celebrate": "太棒啦！星宝为你庆祝",
        }
        bubble = pygame.Rect(int(w * 0.61), int(h * 0.40), int(w * 0.16), int(h * 0.075))
        if state == "alert":
            rounded_panel(self.screen, bubble, (255, 244, 218), border=(219, 139, 72), radius=18, width=2)
            if self.vision_state.get("distance_too_close") and self.vision_state.get("needs_water"):
                message = "坐远一点，再喝口水吧"
            elif self.vision_state.get("distance_too_close"):
                message = "眼睛离屏幕远一点哦"
            else:
                message = "星宝提醒你喝水啦"
            draw_text(self.screen, message, bubble.center, int(h * 0.020), color=(128, 61, 36), bold=True)
        elif state in bubble_messages:
            rounded_panel(self.screen, bubble, (255, 249, 227), border=color, radius=18, width=2)
            draw_text(self.screen, bubble_messages[state], bubble.center, int(h * 0.016), color=(91, 55, 31), bold=True)

    def draw_widgets(self):
        w, h = self.screen.get_size()
        widgets = self.widget_layout()

        today = widgets["today"]
        rounded_panel(self.screen, today, (255, 248, 226), border=(210, 159, 99), radius=18, width=2)
        self.draw_widget_icon("today", pygame.Rect(today.x + int(w * 0.012), today.y + int(h * 0.012), int(h * 0.040), int(h * 0.040)))
        draw_text(self.screen, "今天玩了", (today.centerx, today.y + int(h * 0.033)), int(h * 0.022), bold=True)
        draw_text(self.screen, "{}局  ·  {}颗星".format(
            self.game_summary["today_games"], self.game_summary["stars"]),
            (today.centerx, today.y + int(h * 0.075)), int(h * 0.024), color=(191, 117, 41), bold=True)
        last_game = self.game_summary["last_game"]
        if len(last_game) > 8:
            last_game = last_game[:8] + "…"
        draw_text(self.screen, "最近：{}".format(last_game), (today.centerx, today.y + int(h * 0.115)), int(h * 0.018), color=(118, 83, 55))
        self.register_read_target(
            today,
            "今天玩了{}局，得到{}颗星。最近玩的是{}。".format(
                self.game_summary["today_games"],
                self.game_summary["stars"],
                self.game_summary["last_game"],
            ),
            page="desktop",
        )

        tasks = widgets["tasks"]
        rounded_panel(self.screen, tasks, (255, 250, 231), border=(198, 150, 92), radius=18, width=2)
        self.draw_widget_icon("tasks", pygame.Rect(tasks.x + int(w * 0.012), tasks.y + int(h * 0.016), int(h * 0.036), int(h * 0.036)))
        draw_text(self.screen, "今天的小任务", (tasks.centerx, tasks.y + int(h * 0.045)), int(h * 0.021), bold=True)
        today_key = datetime.now().date().isoformat()
        activities = [item for item in self.store.data.get("activity_history", []) if str(item.get("time", "")).startswith(today_key)]
        task_rows = [
            ("玩1局小游戏", self.game_summary["today_games"] > 0),
            ("专心5分钟", any(item.get("kind") == "focus" for item in activities)),
            ("画1幅画", any(item.get("kind") == "artwork" for item in activities)),
        ]
        for index, (label, done) in enumerate(task_rows):
            y = tasks.y + int(h * (0.085 + index * 0.04))
            pygame.draw.circle(self.screen, (116, 167, 97) if done else (218, 199, 166), (tasks.x + int(w * 0.026), y), max(4, int(h * 0.007)))
            draw_text(self.screen, label, (tasks.x + int(w * 0.095), y), int(h * 0.017), color=(91, 95, 61) if done else (118, 83, 55), bold=done)
        self.register_read_target(
            tasks,
            "今天的小任务。" + "。".join("{}，{}".format(label, "完成了" if done else "还没有完成") for label, done in task_rows),
            page="desktop",
        )

        goal = widgets["goal"]
        rounded_panel(self.screen, goal, (247, 251, 229), border=(153, 171, 101), radius=18, width=2)
        target = 3
        current = min(target, self.game_summary["today_games"])
        self.draw_widget_icon("goal", pygame.Rect(goal.x + int(w * 0.012), goal.y + int(h * 0.010), int(h * 0.040), int(h * 0.040)))
        draw_text(self.screen, "今天的小目标", (goal.centerx, goal.y + int(h * 0.030)), int(h * 0.021), bold=True)
        bar = pygame.Rect(goal.x + int(w * 0.018), goal.y + int(h * 0.061), goal.w - int(w * 0.036), int(h * 0.017))
        pygame.draw.rect(self.screen, (230, 220, 185), bar, border_radius=bar.h // 2)
        fill = pygame.Rect(bar.x, bar.y, int(bar.w * current / target), bar.h)
        if fill.w:
            pygame.draw.rect(self.screen, (125, 173, 101), fill, border_radius=bar.h // 2)
        goal_text = "已完成" if current >= target else "再完成{}局".format(target - current)
        draw_text(self.screen, goal_text, (goal.centerx, goal.y + int(h * 0.102)), int(h * 0.018), color=(91, 112, 65), bold=True)
        self.register_read_target(goal, "今天的小目标，{}。".format(goal_text), page="desktop")

        reward_box = widgets["reward"]
        reward = self.store.reward_level()
        rounded_panel(self.screen, reward_box, (255, 243, 210), border=(211, 147, 56), radius=18, width=2)
        self.draw_widget_icon("reward", pygame.Rect(reward_box.x + int(w * 0.014), reward_box.y + int(h * 0.010), int(h * 0.040), int(h * 0.040)))
        draw_text(self.screen, "成长", (reward_box.centerx, reward_box.y + int(h * 0.030)), int(h * 0.021), bold=True)
        draw_text(self.screen, "{}积分".format(self.store.data["points"]), (reward_box.centerx, reward_box.y + int(h * 0.072)), int(h * 0.027), color=(199, 119, 35), bold=True)
        self.register_read_target(
            reward_box,
            "成长，当前有{}积分。".format(self.store.data["points"]),
            page="desktop",
        )

        mood = widgets["mood"]
        rounded_panel(self.screen, mood, (240, 249, 239), border=(122, 167, 130), radius=18, width=2)
        state = self.xingbao_state()
        mood_labels = {
            "idle": "元气陪伴中", "blink": "眨眨眼", "thinking": "正在想事情",
            "yawn": "打了个哈欠", "happy": "开心转圈圈", "celebrate": "为你庆祝",
            "alert": "健康提醒中",
        }
        self.draw_widget_icon("mood", pygame.Rect(mood.x + int(w * 0.014), mood.y + int(h * 0.008), int(h * 0.036), int(h * 0.036)))
        draw_text(self.screen, "星宝心情", (mood.centerx, mood.y + int(h * 0.028)), int(h * 0.019), bold=True)
        draw_text(self.screen, mood_labels.get(state, "陪伴中"), (mood.centerx, mood.y + int(h * 0.067)), int(h * 0.020), color=(71, 120, 89), bold=True)
        self.register_read_target(mood, "星宝心情，{}。".format(mood_labels.get(state, "陪伴中")), page="desktop")

        quick_labels = (("quick_game", "游戏"), ("quick_focus", "专心"), ("quick_draw", "画画"), ("quick_gallery", "展板"))
        for key, label in quick_labels:
            box = widgets[key]
            rounded_panel(self.screen, box, (255, 246, 218), border=(199, 137, 69), radius=16, width=2)
            icon_size = int(h * 0.026)
            self.draw_widget_icon(key, pygame.Rect(box.centerx - icon_size // 2,
                                                    box.y + int(h * 0.012),
                                                    icon_size, icon_size))
            draw_text(self.screen, label, (box.centerx, box.y + int(h * 0.057)), int(h * 0.017), bold=True)
            self.register_read_target(box, label, page="desktop")

    def draw_ambient_motion(self):
        w, h = self.screen.get_size()
        t = pygame.time.get_ticks() / 1000.0
        anchors = [
            (0.27, 0.24, (232, 190, 102)), (0.72, 0.23, (127, 190, 177)),
            (0.27, 0.66, (235, 157, 150)), (0.71, 0.69, (229, 187, 91)),
            (0.34, 0.47, (143, 193, 185)), (0.68, 0.57, (238, 167, 157)),
        ]
        for index, (rx, ry, color) in enumerate(anchors):
            x = int(w * rx + math.sin(t * 0.45 + index) * w * 0.004)
            y = int(h * ry + math.cos(t * 0.55 + index * 1.7) * h * 0.008)
            radius = max(2, int(h * (0.004 + 0.0015 * (1 + math.sin(t + index)))))
            pygame.draw.circle(self.screen, color, (x, y), radius)

    def render(self):
        self.prepare_next_drawing_if_due()
        self.poll_integrations()
        self.begin_read_targets()
        self.screen.blit(self._scaled_background(), (0, 0))
        self.draw_dynamic_status()
        self.draw_ambient_motion()
        self.draw_widgets()
        self.draw_xingbao_animation()
        self.draw_camera_snapshot_overlay()
        if self.drawer_open:
            self.draw_drawer()
        self.draw_modal()
        if self.notice and pygame.time.get_ticks() < self.notice_until:
            w, h = self.screen.get_size()
            text_size = int(h * 0.023)
            text_font = font(text_size, bold=True)
            horizontal_padding = max(32, int(h * 0.05))
            max_width = int(w * 0.86)
            search_notice = self.notice.startswith("[[SEARCH]] ")
            recognize_icon_kind = (
                "camera" if self.notice == "让我看一看"
                else "emotion" if self.notice == "正在识别中"
                else "search" if search_notice else ""
            )
            notice_text = (
                self.notice[len("[[SEARCH]] "):]
                if search_notice
                else self.notice
            )
            # Reserve a little room for the native-drawn lens.  This avoids
            # relying on emoji coverage in the board's Chinese font.
            search_icon_width = int(text_size * 1.5) if recognize_icon_kind else 0
            preferred_width = max(
                int(w * 0.36),
                text_font.size(notice_text)[0] + horizontal_padding + search_icon_width,
            )
            panel_width = min(max_width, preferred_width)
            usable_width = panel_width - horizontal_padding
            lines = []
            current = ""
            for character in notice_text:
                candidate = current + character
                if current and text_font.size(candidate)[0] > usable_width:
                    lines.append(current)
                    current = character
                else:
                    current = candidate
            if current:
                lines.append(current)
            line_height = text_font.get_linesize()
            text_block_width = max(
                (text_font.size(line)[0] for line in lines), default=0
            )
            panel_height = max(int(h * 0.075), line_height * len(lines) + max(20, int(h * 0.03)))
            rect = pygame.Rect(0, 0, panel_width, panel_height)
            rect.midbottom = (w // 2, int(h * 0.865))
            rounded_panel(self.screen, rect, (255, 249, 227), radius=20, width=2)
            text_top = rect.centery - (line_height * len(lines)) // 2
            text_center_x = rect.centerx
            if recognize_icon_kind:
                icon_size = max(16, int(text_size * 1.18))
                icon_gap = max(4, int(text_size * 0.24))
                group_width = icon_size + icon_gap + text_block_width
                group_left = rect.centerx - group_width // 2
                lens_x = group_left + icon_size // 2
                lens_y = rect.centery
                text_center_x = group_left + icon_size + icon_gap + text_block_width // 2
                cache_key = (recognize_icon_kind, icon_size)
                icon = self.scaled_status_recognize_icons.get(cache_key)
                source_icon = (
                    self.search_status_icon
                    if recognize_icon_kind == "search"
                    else self.status_recognize_icons.get(recognize_icon_kind)
                )
                if icon is None and source_icon is not None:
                    icon = pygame.transform.smoothscale(source_icon, (icon_size, icon_size))
                    self.scaled_status_recognize_icons[cache_key] = icon
                if icon is not None:
                    self.screen.blit(icon, icon.get_rect(center=(lens_x, lens_y)))
                elif recognize_icon_kind == "search":
                    # Keep a readable fallback for deployments missing the asset.
                    lens_radius = max(5, int(text_size * 0.28))
                    pygame.draw.circle(
                        self.screen, (45, 127, 214), (lens_x, lens_y), lens_radius, width=2
                    )
                    pygame.draw.line(
                        self.screen,
                        (45, 127, 214),
                        (lens_x + lens_radius - 1, lens_y + lens_radius - 1),
                        (lens_x + lens_radius + max(4, lens_radius // 2), lens_y + lens_radius + max(4, lens_radius // 2)),
                        width=3,
                    )
            for index, line in enumerate(lines):
                draw = draw_loading_status_text if is_loading_status_text(self.notice) else draw_text
                draw(
                    self.screen,
                    line,
                    (text_center_x, text_top + index * line_height + line_height // 2),
                    text_size,
                    bold=True,
                )
        if self.pending_focus_memory:
            self.pending_focus_memory = False
            media_path = self.save_memory_snapshot("focus")
            self.remember(
                "health", "我专心了5分钟", "星宝陪我安静做完了一件事",
                "focus_timer", media_path=media_path)

    def run(self, snapshot=None, quit_pygame=True):
        result = None
        self.active = True
        self.render()
        pygame.display.flip()
        last_render_ms = pygame.time.get_ticks()
        if snapshot:
            pygame.image.save(self.screen, str(snapshot))
            self.running = False
        while self.running:
            board_runtime.pump()
            self.clock.tick(self.event_fps)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    result = self.handle_key(event.key)
                elif event.type == pygame.MOUSEWHEEL and self.modal in ("memory", "parent_summaries"):
                    self.scroll_current_modal(-event.y)
                elif event.type == pygame.MOUSEBUTTONDOWN and self.locked:
                    self.begin_lock_slider(event.pos)
                elif event.type == pygame.MOUSEBUTTONDOWN and self.modal == "drawing" and self.drawing_rect().collidepoint(event.pos):
                    self.drawing = True
                    self.handle_draw_point(event.pos, start=True)
                elif event.type == pygame.MOUSEBUTTONDOWN and self.modal in ("memory", "parent_summaries"):
                    self.begin_memory_scroll_touch(event.pos, "mouse")
                elif event.type == pygame.MOUSEMOTION and self.locked and self.lock_slider_dragging:
                    self.update_lock_slider(event.pos)
                elif event.type == pygame.MOUSEMOTION and self.modal == "drawing" and self.drawing:
                    self.handle_draw_point(event.pos)
                elif event.type == pygame.MOUSEMOTION and self.modal in ("memory", "parent_summaries"):
                    self.update_memory_scroll_touch(event.pos, "mouse")
                elif event.type == pygame.MOUSEBUTTONUP:
                    if self.locked:
                        self.finish_lock_slider(event.pos)
                    elif self.modal == "drawing" and self.drawing:
                        self.handle_draw_point(event.pos)
                        self.drawing = False
                        self.last_draw_pos = None
                    elif self.modal in ("memory", "parent_summaries") and self.scroll_touch_start is not None:
                        if self.scroll_touch_source == "mouse" and not self.finish_memory_scroll_touch(event.pos, "mouse"):
                            result = self.handle_touch(event.pos)
                    else:
                        result = self.handle_touch(event.pos)
                elif event.type == pygame.FINGERDOWN and self.locked:
                    w, h = self.screen.get_size()
                    self.begin_lock_slider((int(event.x * w), int(event.y * h)))
                elif event.type == pygame.FINGERDOWN and self.modal == "drawing":
                    w, h = self.screen.get_size()
                    point = (int(event.x * w), int(event.y * h))
                    if self.drawing_rect().collidepoint(point):
                        self.drawing = True
                        self.handle_draw_point(point, start=True)
                elif event.type == pygame.FINGERDOWN and self.modal in ("memory", "parent_summaries"):
                    w, h = self.screen.get_size()
                    self.begin_memory_scroll_touch(
                        (int(event.x * w), int(event.y * h)), "finger"
                    )
                elif event.type == pygame.FINGERMOTION and self.locked and self.lock_slider_dragging:
                    w, h = self.screen.get_size()
                    self.update_lock_slider((int(event.x * w), int(event.y * h)))
                elif event.type == pygame.FINGERMOTION and self.modal == "drawing" and self.drawing:
                    w, h = self.screen.get_size()
                    self.handle_draw_point((int(event.x * w), int(event.y * h)))
                elif event.type == pygame.FINGERMOTION and self.modal in ("memory", "parent_summaries"):
                    w, h = self.screen.get_size()
                    self.update_memory_scroll_touch(
                        (int(event.x * w), int(event.y * h)), "finger"
                    )
                elif event.type == pygame.FINGERUP:
                    w, h = self.screen.get_size()
                    point = (int(event.x * w), int(event.y * h))
                    if self.locked:
                        self.finish_lock_slider(point)
                    elif self.modal == "drawing" and self.drawing:
                        self.handle_draw_point(point)
                        self.drawing = False
                        self.last_draw_pos = None
                    elif self.modal in ("memory", "parent_summaries") and self.scroll_touch_start is not None:
                        if self.scroll_touch_source == "finger" and not self.finish_memory_scroll_touch(point, "finger"):
                            result = self.handle_touch(point)
                    else:
                        result = self.handle_touch(point)
                elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                if result == "game":
                    break
            now_ms = pygame.time.get_ticks()
            active_render_fps = 15 if self.drawing else self.target_fps
            render_interval_ms = max(1, int(1000 / active_render_fps))
            if now_ms - last_render_ms >= render_interval_ms:
                self.render()
                pygame.display.flip()
                last_render_ms = now_ms
        if quit_pygame:
            pygame.quit()
        self.active = False
        return result or self.next_action


def main(argv=None):
    args = parse_args(argv)
    fullscreen = not args.snapshot
    snapshot = ROOT / "screenshots" / "desktop_launcher.png" if args.snapshot else None
    trace("desktop_main_start snapshot={} bridge={}".format(bool(snapshot), not args.no_central_bridge))
    trace("display_env driver={} display={} wayland={} session={}".format(
        pygame.display.get_driver() if pygame.display.get_init() else "not_initialized",
        os.environ.get("DISPLAY", ""),
        os.environ.get("WAYLAND_DISPLAY", ""),
        os.environ.get("XDG_SESSION_TYPE", ""),
    ))

    if not snapshot and not args.no_central_bridge:
        from examples.central_ui_dispatcher_example import serve
        threading.Thread(target=serve, name="central-ui-bridge", daemon=True).start()

    vision_bridge = None
    if not snapshot and not args.no_vision:
        vision_bridge = VisionProcessBridge(
            ROOT / "integrations" / "vision_release",
            ROOT / "saves" / "vision_status.json",
            source=args.camera_source,
            project_root=ROOT.parents[1],
            companion_settings_path=ROOT / "saves" / "desktop_settings.json",
        )
        vision_bridge.start()

    game = None
    speech_client = None
    if not snapshot:
        if not args.no_game_speech:
            speech_client = CentralSpeechClient(
                host=args.game_speech_host,
                port=args.game_speech_port,
            )

    launcher = None
    while True:
        if launcher is None:
            trace("launcher_create")
            launcher = DesktopLauncher(
                fullscreen=fullscreen,
                size=(args.width, args.height),
                on_speech_request=(speech_client.submit if speech_client is not None else None),
                low_effects=args.low_effects,
            )
        else:
            trace("launcher_reactivate")
            launcher.reactivate_display()
        board_runtime.bind(desktop=launcher, app=game)
        action = launcher.run(snapshot=snapshot, quit_pygame=False)
        trace("launcher_return action={!r}".format(action))
        if snapshot or action != "game":
            trace("launcher_break snapshot={} action={!r}".format(bool(snapshot), action))
            break
        if game is None:
            trace("game_lazy_create")
            game = XingbaoApp(
                fullscreen=fullscreen,
                size=(args.width, args.height),
                log_dir=ROOT / "logs",
                low_effects=args.low_effects,
                save_dir=ROOT / "saves",
                demo_speed="slow",
                debug_layout=False,
                preload_only=False,
                on_speech_request=(speech_client.submit if speech_client is not None else None),
                on_game_state=(speech_client.submit_state if speech_client is not None else None),
            )
            board_runtime.bind(desktop=launcher, app=game)
        games_before = game.records.games_played
        game.activate_display(fullscreen=fullscreen, size=(args.width, args.height))
        pygame.event.clear()
        trace("game_before_run state={} running={} requested_pending={}".format(
            getattr(game.state, "value", game.state), game.running, bool(board_runtime.pending_game)
        ))
        board_runtime.bind(desktop=launcher, app=game)
        requested = board_runtime.pending_game
        board_runtime.pending_game = None
        if requested and requested["game_id"] is not None:
            game.start_game(requested["game_id"], difficulty=requested["difficulty"])
            trace("game_start_requested game_id={} difficulty={}".format(
                requested["game_id"], requested["difficulty"]
            ))
        game.show_first_frame()
        trace("game_first_frame driver={} size={} flags={}".format(
            pygame.display.get_driver(), game.screen.get_size(), game.screen.get_flags()
        ))
        try:
            game.run(quit_pygame=False)
        except Exception:
            trace("game_exception")
            traceback.print_exc()
            raise
        trace("game_after_run state={} running={}".format(
            getattr(game.state, "value", game.state), game.running
        ))
        print("XINGBAO_GAME_LOOP_RETURNED state={} running={}".format(
            getattr(game.state, "value", game.state), game.running
        ), flush=True)
        completed = max(0, game.records.games_played - games_before)
        if completed:
            config = IntegrationConfig(ROOT)
            memory_path = config.resolve("memory_file") or ROOT / "saves" / "xingbao_memory.json"
            memory = MemoryBackend(memory_path)
            snapshot_data = game.records.snapshot()
            game_media_path = game.last_game_screenshot
            if game_media_path:
                try:
                    game_media_path = Path(game_media_path).resolve().relative_to(ROOT.resolve()).as_posix()
                except ValueError:
                    pass
            try:
                memory.add(
                    "game",
                    "我玩了{}".format(snapshot_data.get("last_game", "小游戏")),
                    "我完成了{}局，还得到了星星".format(completed),
                    source="game_center",
                    media_path=game_media_path,
                )
            except OSError:
                pass
    pygame.quit()
    if vision_bridge is not None:
        vision_bridge.stop()
    if speech_client is not None:
        speech_client.close()


if __name__ == "__main__":
    main()
