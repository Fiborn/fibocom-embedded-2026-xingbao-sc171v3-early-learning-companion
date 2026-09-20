"""Run the released touch desktop with the restored r5 phase-one NDJSON bridge.

This process intentionally starts only the display/touch UI and port 8765.
It does not start vision, game speech, wake word, ASR, TTS, or the arm service.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Callable

try:
    from .embedded_toolbox_runtime import EmbeddedToolboxRuntime
except ImportError:
    from embedded_toolbox_runtime import EmbeddedToolboxRuntime


# The board's PulseAudio session may expose only a null sink.  Letting SDL
# initialize its real audio backend in the display-only phase can block before
# Pygame creates the X11 window.  Voice and TTS use their own board services,
# so this UI process must stay audio-free.
os.environ["SDL_AUDIODRIVER"] = "dummy"


DEFAULT_UI_DIR = Path(
    os.getenv(
        "XINGBAO_UI_DIR",
        "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge",
    )
)
DRAWING_TOOL_SLUGS = {"draw", "drawing", "drawing_board", "shape_drawing"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTION_BUTTON_ASSET_DIR = PROJECT_ROOT / "components" / "touch_ui" / "assets" / "ui" / "action_buttons"
os.environ.setdefault("XINGBAO_COMPANION_DATA_DIR", str(PROJECT_ROOT / "data"))
VISUAL_TOOLS_SCRIPT = PROJECT_ROOT / "web" / "kids_visual_tools" / "kids_visual_tools.py"
VISUAL_TOOLS_WINDOW_TITLE = "\u513f\u7ae5\u53ef\u89c6\u5316\u5c0f\u5de5\u5177\u7bb1"
TOOLBOX_REGISTRY_PATH = PROJECT_ROOT / "config" / "kids_visual_tools_registry.json"
TOOLBOX_PAGE_SIZE = 9
TOOLBOX_GRID_MODAL = "r5_toolbox_grid"
TOOLBOX_ACTIVITY_MODAL = "r5_tool_activity"
TOOLBOX_DRAWING_KINDS = {"drawing", "coloring", "stickers"}
TOOLBOX_TIMER_KINDS = {"timer", "pomodoro"}
VOICE_MODAL_WHITELIST = {"memory", "rest", "drawing", "pomodoro", "gallery", "favorites"}
SEARCH_STATUS_PREFIX = "[[SEARCH]] "
UI_EVENT_HOST = os.getenv("XINGBAO_GAME_EVENT_HOST", "127.0.0.1")
UI_EVENT_PORT = int(os.getenv("XINGBAO_GAME_EVENT_PORT", "8766"))
# 触控 UI 只能提交这组语义事件。动作由中枢和机械臂服务二次白名单，
# 本模块绝不持有或生成舵机角度、速度、时序等低层参数。
UI_INTERACTION_EVENTS = frozenset(
    {
        "game_started",
        "game_answer_correct",
        "game_completed",
        "reward_received",
        "toolbox_opened",
        "toolbox_activity_started",
        "toolbox_result_saved",
        "drawing_started",
        "drawing_completed",
        "guided_expression_recover",
        "conversation_stop",
        "synthetic_wake",
    }
)


def _sanitize_status_text(value: object) -> str:
    """Preserve symbols while normalising only troublesome whitespace.

    Conversation stream chunks can leave duplicate spaces after a sentence.
    Some display/font combinations render those gaps as tofu, so fold any
    whitespace run to one ordinary ASCII space.  All non-whitespace symbols
    and characters are left untouched for the glyph fallback chain.
    """
    return re.sub(r"[\s\u200b\ufeff]+", " ", str(value or "")).strip()


def _is_duplicate_quick_voice_tap(
    previous: tuple[float, int, int] | None,
    pos: tuple[int, int],
    *,
    now: float,
) -> bool:
    """Detect SDL's mouse event synthesized from one Wayland finger release."""
    if previous is None:
        return False
    previous_at, previous_x, previous_y = previous
    point_x, point_y = int(pos[0]), int(pos[1])
    return (
        now - previous_at < 0.25
        and abs(point_x - previous_x) <= 24
        and abs(point_y - previous_y) <= 24
    )


def _emit_ui_interaction_event(
    event: str,
    *,
    on_delivery_result: Callable[[dict[str, Any]], None] | None = None,
    **context: object,
) -> None:
    """Forward one reviewed UI outcome to the central event port without blocking touch."""
    clean_event = str(event or "").strip()
    if clean_event not in UI_INTERACTION_EVENTS:
        return
    payload = {"event": clean_event}
    payload.update(
        {
            str(key): str(value)[:120]
            for key, value in context.items()
            if value is not None and str(value).strip()
        }
    )
    message = {
        "type": "game_event",
        "source": "touch_ui",
        "message_id": str(uuid.uuid4()),
        "payload": payload,
    }

    def send() -> None:
        result: dict[str, Any]
        try:
            encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            with socket.create_connection((UI_EVENT_HOST, UI_EVENT_PORT), timeout=0.35) as sock:
                sock.settimeout(0.35)
                sock.sendall(encoded)
                raw_response = sock.makefile("rb").readline()
            response = json.loads(raw_response.decode("utf-8-sig"))
            result = response if isinstance(response, dict) else {"ok": False}
        except (OSError, UnicodeDecodeError, ValueError):
            result = {"ok": False}
        if on_delivery_result is not None:
            try:
                on_delivery_result(result)
            except Exception:
                pass

    threading.Thread(
        target=send,
        name="xingbao-ui-interaction-event",
        daemon=True,
    ).start()


def _visual_tool_window_id() -> int | None:
    """Return the existing 85-tool window id when it is visible on X11."""
    try:
        tree = subprocess.check_output(
            ["xwininfo", "-root", "-tree"],
            env=dict(os.environ),
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(
        r"(0x[0-9a-fA-F]+).*" + re.escape(VISUAL_TOOLS_WINDOW_TITLE),
        tree,
    )
    return int(match.group(1), 16) if match else None


def _raise_x11_window(window_id: int) -> bool:
    """Raise a known X11 window without requiring an extra desktop package."""
    try:
        import ctypes

        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        display = x11.XOpenDisplay(None)
        if not display:
            return False
        try:
            x11.XRaiseWindow(display, ctypes.c_ulong(window_id))
            x11.XSetInputFocus(display, ctypes.c_ulong(window_id), 2, 0)
            x11.XFlush(display)
        finally:
            x11.XCloseDisplay(display)
        return True
    except OSError:
        return False


def _running_visual_tools_pids() -> list[int]:
    """Find only toolbox processes belonging to this r5 project."""
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cwd = (entry / "cwd").resolve()
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if cwd != PROJECT_ROOT:
            continue
        arguments = [item.decode("utf-8", errors="replace") for item in argv if item]
        if any(Path(item).name == VISUAL_TOOLS_SCRIPT.name for item in arguments):
            matches.append(int(entry.name))
    return matches


def _open_visual_tools(params: dict[str, Any]) -> dict[str, Any]:
    """Launch or foreground the real 85-tool Tk toolbox from the central UI."""
    if not VISUAL_TOOLS_SCRIPT.is_file():
        return {"ok": False, "error": "visual_tools_script_missing"}

    slug = str(params.get("tool_slug") or "").strip().casefold()
    if slug and not re.fullmatch(r"[a-z0-9_]+", slug):
        return {"ok": False, "error": "invalid_visual_tool_slug"}

    existing = _running_visual_tools_pids()
    window_id = _visual_tool_window_id()
    if not slug and existing:
        raised = _raise_x11_window(window_id) if window_id is not None else False
        return {
            "ok": True,
            "mode": "raised" if raised else "already_running",
            "pid": existing[0],
            "window_id": window_id,
        }

    command = [sys.executable, str(VISUAL_TOOLS_SCRIPT)]
    if slug:
        command.extend(["--tool", slug])
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    return {"ok": True, "mode": "launched", "pid": process.pid, "tool_slug": slug}


def _load_toolbox_items() -> list[dict[str, Any]]:
    """Load the canonical 85-tool registry without depending on a Tk window."""
    try:
        data = json.loads(TOOLBOX_REGISTRY_PATH.read_text(encoding="utf-8"))
        tools = data.get("tools") if isinstance(data, dict) else None
        if not isinstance(tools, list):
            return []
        return [dict(item) for item in tools if isinstance(item, dict)]
    except (OSError, ValueError, TypeError):
        return []


def _toolbox_state(desktop: Any) -> list[dict[str, Any]]:
    items = getattr(desktop, "r5_toolbox_items", None)
    if not isinstance(items, list):
        items = _load_toolbox_items()
        desktop.r5_toolbox_items = items
    if not hasattr(desktop, "r5_toolbox_page"):
        desktop.r5_toolbox_page = 0
    if not hasattr(desktop, "r5_toolbox_selected"):
        desktop.r5_toolbox_selected = None
    if not hasattr(desktop, "r5_toolbox_counter"):
        desktop.r5_toolbox_counter = 0
    if not hasattr(desktop, "r5_toolbox_message"):
        desktop.r5_toolbox_message = ""
    return items


def _toolbox_runtime(desktop: Any) -> EmbeddedToolboxRuntime:
    runtime = getattr(desktop, "r5_toolbox_runtime", None)
    if not isinstance(runtime, EmbeddedToolboxRuntime):
        runtime = EmbeddedToolboxRuntime(PROJECT_ROOT)
        desktop.r5_toolbox_runtime = runtime
    return runtime


def _toolbox_open(desktop: Any, slug: str = "") -> None:
    """Enter the 85-tool browser inside the existing Pygame desktop."""
    items = _toolbox_state(desktop)
    desktop.drawer_open = False
    desktop.drawing = False
    desktop.last_draw_pos = None
    desktop.r5_return_to_toolbox = False
    normalized_slug = str(slug or "").strip().casefold()
    _emit_ui_interaction_event("toolbox_opened", tool_slug=normalized_slug or "home")
    selected_index = next(
        (index for index, item in enumerate(items)
         if str(item.get("slug") or "").casefold() == normalized_slug),
        None,
    )
    if selected_index is None:
        desktop.r5_toolbox_selected = None
        desktop.r5_toolbox_page = 0
        desktop.modal = TOOLBOX_GRID_MODAL
        desktop.show_notice("\u767e\u5b9d\u7bb1\uff1a\u6bcf\u98759\u4e2a\u5c0f\u5de5\u5177", seconds=2.4)
        return
    desktop.r5_toolbox_selected = selected_index
    desktop.r5_toolbox_page = selected_index // TOOLBOX_PAGE_SIZE
    desktop.modal = TOOLBOX_ACTIVITY_MODAL
    item = items[selected_index]
    _toolbox_runtime(desktop).activate(item)
    desktop.show_notice(str(item.get("title") or "\u767e\u5b9d\u7bb1"), seconds=2.0)


def _toolbox_grid_geometry(desktop: Any) -> tuple[Any, Any, Any, Any, list[Any]]:
    pygame = sys.modules[desktop.__class__.__module__].pygame
    width, height = desktop.screen.get_size()
    panel = pygame.Rect(int(width * 0.10), int(height * 0.07), int(width * 0.80), int(height * 0.86))
    close = pygame.Rect(panel.right - int(width * 0.072), panel.y + int(height * 0.018), int(width * 0.052), int(height * 0.058))
    previous = pygame.Rect(panel.x + int(width * 0.030), panel.bottom - int(height * 0.092), int(width * 0.145), int(height * 0.062))
    following = pygame.Rect(panel.right - int(width * 0.175), panel.bottom - int(height * 0.092), int(width * 0.145), int(height * 0.062))
    grid = pygame.Rect(panel.x + int(width * 0.030), panel.y + int(height * 0.115), panel.w - int(width * 0.060), int(height * 0.610))
    gap_x = max(8, int(width * 0.012))
    gap_y = max(8, int(height * 0.018))
    card_w = (grid.w - gap_x * 2) // 3
    card_h = (grid.h - gap_y * 2) // 3
    cards = [
        pygame.Rect(grid.x + col * (card_w + gap_x), grid.y + row * (card_h + gap_y), card_w, card_h)
        for row in range(3) for col in range(3)
    ]
    return panel, close, previous, following, cards


def _toolbox_activity_geometry(desktop: Any) -> tuple[Any, Any, Any, Any, Any]:
    pygame = sys.modules[desktop.__class__.__module__].pygame
    width, height = desktop.screen.get_size()
    panel = pygame.Rect(int(width * 0.18), int(height * 0.12), int(width * 0.64), int(height * 0.76))
    close = pygame.Rect(panel.right - int(width * 0.070), panel.y + int(height * 0.022), int(width * 0.050), int(height * 0.062))
    back = pygame.Rect(panel.x + int(width * 0.030), panel.y + int(height * 0.026), int(width * 0.120), int(height * 0.056))
    primary = pygame.Rect(int(width * 0.335), panel.bottom - int(height * 0.125), int(width * 0.165), int(height * 0.074))
    secondary = pygame.Rect(int(width * 0.520), panel.bottom - int(height * 0.125), int(width * 0.145), int(height * 0.074))
    return panel, close, back, primary, secondary


def _toolbox_save_geometry(desktop: Any) -> Any:
    pygame = sys.modules[desktop.__class__.__module__].pygame
    width, height = desktop.screen.get_size()
    panel, _, _, _, _ = _toolbox_activity_geometry(desktop)
    return pygame.Rect(
        panel.right - int(width * 0.160),
        panel.y + int(height * 0.024),
        int(width * 0.080),
        int(height * 0.058),
    )


def _toolbox_color(value: Any) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[offset:offset + 2], 16) for offset in (0, 2, 4))
        except ValueError:
            pass
    return (92, 173, 226)


def _toolbox_button(released_desktop: Any, desktop: Any, rect: Any, label: str, *, selected: bool = False) -> None:
    fill = (255, 221, 132) if selected else (255, 251, 236)
    border = (204, 137, 62) if selected else (219, 177, 123)
    released_desktop.rounded_panel(desktop.screen, rect, fill, border=border, radius=16, width=3 if selected else 2)
    _, height = desktop.screen.get_size()
    released_desktop.draw_text(desktop.screen, label, rect.center, max(16, int(height * 0.022)), bold=selected)


def _toolbox_activity_copy(item: dict[str, Any], count: int) -> tuple[str, str, str, str]:
    kind = str(item.get("kind") or "").casefold()
    title = str(item.get("title") or "\u661f\u5b9d\u5c0f\u6d3b\u52a8")
    purpose = str(item.get("purpose") or "\u4e00\u8d77\u73a9\u4e00\u73a9")
    if kind in TOOLBOX_DRAWING_KINDS:
        return ("\u4f60\u53ef\u4ee5\u5728\u661f\u5b9d\u753b\u677f\u91cc\u5b8c\u6210\u8fd9\u4e2a\u521b\u4f5c\u4e3b\u9898", purpose, "\u6253\u5f00\u753b\u677f", "\u6362\u4e2a\u4e3b\u9898")
    if kind in TOOLBOX_TIMER_KINDS:
        return ("\u5f00\u542f\u661f\u5b9d\u4e13\u5fc3\u5c0f\u949f\uff0c\u4e00\u8d77\u5b8c\u6210\u5c0f\u4efb\u52a1", purpose, "\u6253\u5f00\u8ba1\u65f6\u5668", "\u5df2\u5b8c\u6210")
    if kind == "water":
        return ("\u559d\u6c34\u4e00\u6b21\uff0c\u7ed9\u8eab\u4f53\u52a0\u6ee1\u5143\u6c14", purpose, "\u6211\u559d\u597d\u4e86", "\u518d\u6765\u4e00\u6b21")
    if kind == "breath":
        return ("\u8ddf\u7740\u661f\u5b9d\uff1a\u5438\u6c14\u3001\u505c\u4e00\u505c\u3001\u6162\u6162\u547c\u6c14", purpose, "\u5b8c\u6210\u4e00\u6b21\u547c\u5438", "\u518d\u6765\u4e00\u6b21")
    if kind == "mood":
        return ("\u70b9\u4e00\u4e0b\u9009\u4e2d\u4f60\u6b64\u523b\u7684\u5fc3\u60c5\uff0c\u661f\u5b9d\u4f1a\u966a\u4f60", purpose, "\u8bb0\u5f55\u5fc3\u60c5", "\u6362\u4e00\u4e2a")
    if kind.startswith("game"):
        return ("\u4eca\u5929\u7684\u5c0f\u6311\u6218\u5df2\u51c6\u5907\u597d", purpose, "\u5f00\u59cb\u6311\u6218", "\u6362\u4e00\u9898")
    if kind in {"cards", "story", "player"}:
        return ("\u70b9\u4e00\u4e0b\u8ba9\u661f\u5b9d\u6362\u4e00\u5f20\u5c0f\u5361\u7247\u6216\u4e00\u6bb5\u5c0f\u6545\u4e8b", purpose, "\u4e0b\u4e00\u4e2a", "\u518d\u542c\u4e00\u6b21")
    return ("{}\uff1a\u8fd9\u4e00\u8f6e\u5df2\u7ecf\u4e92\u52a8{}\u6b21".format(title, count), purpose, "\u5f00\u59cb\u4e92\u52a8", "\u6362\u4e00\u4e2a")


def _draw_toolbox_grid(released_desktop: Any, desktop: Any) -> None:
    pygame = released_desktop.pygame
    items = _toolbox_state(desktop)
    width, height = desktop.screen.get_size()
    shade = pygame.Surface((width, height), pygame.SRCALPHA)
    shade.fill((42, 31, 58, 132))
    desktop.screen.blit(shade, (0, 0))
    panel, close, previous, following, cards = _toolbox_grid_geometry(desktop)
    released_desktop.rounded_panel(desktop.screen, panel, (255, 249, 234), border=(211, 163, 102), radius=30, width=3)
    released_desktop.draw_text(desktop.screen, "\u767e\u5b9d\u7bb1\u00b785\u4e2a\u4e92\u52a8\u5c0f\u5de5\u5177", (panel.centerx, panel.y + int(height * 0.052)), int(height * 0.034), bold=True)
    pages = max(1, (len(items) + TOOLBOX_PAGE_SIZE - 1) // TOOLBOX_PAGE_SIZE)
    desktop.r5_toolbox_page = max(0, min(int(desktop.r5_toolbox_page), pages - 1))
    released_desktop.draw_text(desktop.screen, "\u7b2c {} / {} \u9875\uff0c\u6bcf\u9875 3\u00d73".format(desktop.r5_toolbox_page + 1, pages), (panel.centerx, panel.y + int(height * 0.090)), int(height * 0.020), color=(117, 82, 56))
    start = desktop.r5_toolbox_page * TOOLBOX_PAGE_SIZE
    for offset, (item, card) in enumerate(zip(items[start:start + TOOLBOX_PAGE_SIZE], cards)):
        color = _toolbox_color(item.get("color"))
        released_desktop.rounded_panel(desktop.screen, card, (255, 253, 246), border=color, radius=18, width=3)
        circle_center = (card.x + int(card.w * 0.15), card.y + int(card.h * 0.22))
        pygame.draw.circle(desktop.screen, color, circle_center, max(12, int(min(card.w, card.h) * 0.105)))
        released_desktop.draw_text(desktop.screen, str(item.get("no") or start + offset + 1), circle_center, max(14, int(height * 0.018)), color=(255, 255, 255), bold=True)
        title = str(item.get("title") or "\u661f\u5b9d\u5c0f\u5de5\u5177")
        purpose = str(item.get("purpose") or "\u4e00\u8d77\u73a9\u4e00\u73a9")
        released_desktop.draw_text(desktop.screen, title[:12], (card.centerx, card.y + int(card.h * 0.45)), max(17, int(height * 0.024)), bold=True)
        released_desktop.draw_text(desktop.screen, purpose[:16], (card.centerx, card.y + int(card.h * 0.70)), max(13, int(height * 0.016)), color=(117, 82, 56))
        desktop.register_read_target(card, "{}\uff0c{}".format(title, purpose), page="toolbox")
    _toolbox_button(released_desktop, desktop, previous, "\u4e0a\u4e00\u9875", selected=desktop.r5_toolbox_page > 0)
    _toolbox_button(released_desktop, desktop, following, "\u4e0b\u4e00\u9875", selected=desktop.r5_toolbox_page < pages - 1)
    _toolbox_button(released_desktop, desktop, close, "\u5173\u95ed")
    desktop.register_read_target(close, "\u5173\u95ed\u767e\u5b9d\u7bb1", page="toolbox")


def _draw_toolbox_activity(released_desktop: Any, desktop: Any) -> None:
    pygame = released_desktop.pygame
    items = _toolbox_state(desktop)
    selected = getattr(desktop, "r5_toolbox_selected", None)
    if not isinstance(selected, int) or not (0 <= selected < len(items)):
        desktop.modal = TOOLBOX_GRID_MODAL
        return
    item = items[selected]
    width, height = desktop.screen.get_size()
    shade = pygame.Surface((width, height), pygame.SRCALPHA)
    shade.fill((42, 31, 58, 132))
    desktop.screen.blit(shade, (0, 0))
    panel, close, back, _, _ = _toolbox_activity_geometry(desktop)
    save = _toolbox_save_geometry(desktop)
    color = _toolbox_color(item.get("color"))
    released_desktop.rounded_panel(desktop.screen, panel, (255, 250, 238), border=color, radius=30, width=3)
    _toolbox_button(released_desktop, desktop, back, "\u8fd4\u56de\u767e\u5b9d\u7bb1")
    _toolbox_button(released_desktop, desktop, save, "\u4fdd\u5b58\u6210\u679c", selected=True)
    _toolbox_button(released_desktop, desktop, close, "\u5173\u95ed")
    title = str(item.get("title") or "\u661f\u5b9d\u5c0f\u5de5\u5177")
    released_desktop.draw_text(desktop.screen, title, (panel.centerx, panel.y + int(height * 0.072)), int(height * 0.032), bold=True)
    body = pygame.Rect(panel.x + int(width * 0.025), panel.y + int(height * 0.115), panel.w - int(width * 0.050), panel.h - int(height * 0.145))
    _toolbox_runtime(desktop).draw(released_desktop, desktop, item, body)
    return
    width, height = desktop.screen.get_size()
    shade = pygame.Surface((width, height), pygame.SRCALPHA)
    shade.fill((42, 31, 58, 132))
    desktop.screen.blit(shade, (0, 0))
    panel, close, back, primary, secondary = _toolbox_activity_geometry(desktop)
    color = _toolbox_color(item.get("color"))
    released_desktop.rounded_panel(desktop.screen, panel, (255, 250, 238), border=color, radius=30, width=3)
    _toolbox_button(released_desktop, desktop, back, "\u8fd4\u56de\u767e\u5b9d\u7bb1")
    _toolbox_button(released_desktop, desktop, close, "\u5173\u95ed")
    title = str(item.get("title") or "\u661f\u5b9d\u5c0f\u5de5\u5177")
    headline, purpose, primary_label, secondary_label = _toolbox_activity_copy(item, int(desktop.r5_toolbox_counter))
    released_desktop.draw_text(desktop.screen, title, (panel.centerx, panel.y + int(height * 0.145)), int(height * 0.040), bold=True)
    released_desktop.draw_text(desktop.screen, str(item.get("category") or "\u4e92\u52a8\u5c0f\u6e38\u620f"), (panel.centerx, panel.y + int(height * 0.205)), int(height * 0.020), color=color, bold=True)
    orb = (panel.centerx, panel.y + int(height * 0.355))
    for radius, alpha in ((int(height * 0.115), 35), (int(height * 0.087), 80)):
        halo = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(halo, (*color, alpha), (radius, radius), radius)
        desktop.screen.blit(halo, (orb[0] - radius, orb[1] - radius))
    pygame.draw.circle(desktop.screen, color, orb, int(height * 0.056))
    released_desktop.draw_text(desktop.screen, "\u73a9", orb, int(height * 0.036), color=(255, 255, 255), bold=True)
    released_desktop.draw_text(desktop.screen, headline[:28], (panel.centerx, panel.y + int(height * 0.485)), int(height * 0.023), color=(93, 67, 50), bold=True)
    released_desktop.draw_text(desktop.screen, purpose[:34], (panel.centerx, panel.y + int(height * 0.535)), int(height * 0.019), color=(117, 82, 56))
    message = str(getattr(desktop, "r5_toolbox_message", ""))
    if message:
        released_desktop.draw_text(desktop.screen, message[:34], (panel.centerx, panel.y + int(height * 0.605)), int(height * 0.020), color=color, bold=True)
    _toolbox_button(released_desktop, desktop, primary, primary_label, selected=True)
    _toolbox_button(released_desktop, desktop, secondary, secondary_label)
    desktop.register_read_target(primary, primary_label, page="tool_activity")
    desktop.register_read_target(secondary, secondary_label, page="tool_activity")


def _handle_toolbox_touch(released_desktop: Any, desktop: Any, pos: tuple[int, int]) -> None:
    items = _toolbox_state(desktop)
    if desktop.modal == TOOLBOX_GRID_MODAL:
        _, close, previous, following, cards = _toolbox_grid_geometry(desktop)
        pages = max(1, (len(items) + TOOLBOX_PAGE_SIZE - 1) // TOOLBOX_PAGE_SIZE)
        if close.collidepoint(pos):
            desktop.modal = None
            desktop.speak_readable("\u5173\u95ed\u767e\u5b9d\u7bb1", page="toolbox")
            return
        if previous.collidepoint(pos):
            desktop.r5_toolbox_page = max(0, desktop.r5_toolbox_page - 1)
            desktop.speak_readable("\u4e0a\u4e00\u9875", page="toolbox")
            return
        if following.collidepoint(pos):
            desktop.r5_toolbox_page = min(pages - 1, desktop.r5_toolbox_page + 1)
            desktop.speak_readable("\u4e0b\u4e00\u9875", page="toolbox")
            return
        start = desktop.r5_toolbox_page * TOOLBOX_PAGE_SIZE
        for offset, card in enumerate(cards):
            index = start + offset
            if index < len(items) and card.collidepoint(pos):
                desktop.r5_toolbox_selected = index
                desktop.r5_toolbox_message = ""
                desktop.modal = TOOLBOX_ACTIVITY_MODAL
                _toolbox_runtime(desktop).activate(items[index])
                _emit_ui_interaction_event(
                    "toolbox_activity_started",
                    tool_slug=str(items[index].get("slug") or ""),
                    tool_kind=str(items[index].get("kind") or ""),
                )
                desktop.speak_readable(str(items[index].get("title") or "\u767e\u5b9d\u7bb1"), page="toolbox")
                return
        return

    _, close, back, primary, secondary = _toolbox_activity_geometry(desktop)
    if close.collidepoint(pos):
        desktop.modal = None
        desktop.speak_readable("\u5173\u95ed", page="tool_activity")
        return
    if back.collidepoint(pos):
        desktop.modal = TOOLBOX_GRID_MODAL
        desktop.speak_readable("\u8fd4\u56de\u767e\u5b9d\u7bb1", page="tool_activity")
        return
    selected = getattr(desktop, "r5_toolbox_selected", None)
    if not isinstance(selected, int) or not (0 <= selected < len(items)):
        desktop.modal = TOOLBOX_GRID_MODAL
        return
    item = items[selected]
    save = _toolbox_save_geometry(desktop)
    if save.collidepoint(pos):
        title = str(item.get("title") or "\u661f\u5b9d\u5c0f\u6d3b\u52a8")
        summary = _toolbox_runtime(desktop).result_summary(item)
        entry = desktop.remember(
            "game",
            "\u5b8c\u6210\u00b7{}".format(title),
            summary,
            "game_center",
        )
        if entry is not None:
            desktop.r5_toolbox_message = "\u5df2\u4fdd\u5b58\u5230\u56de\u5fc6\u672c\uff1a{}".format(summary)
            desktop.show_notice("\u5df2\u4fdd\u5b58\u5230\u56de\u5fc6\u672c", seconds=2.5)
            desktop.speak_readable("\u6210\u679c\u5df2\u4fdd\u5b58\u5230\u56de\u5fc6\u672c", page="tool_activity")
            kind = str(item.get("kind") or "").casefold()
            _emit_ui_interaction_event(
                "drawing_completed" if kind in TOOLBOX_DRAWING_KINDS else "toolbox_result_saved",
                tool_slug=str(item.get("slug") or ""),
                tool_kind=kind,
            )
        else:
            desktop.r5_toolbox_message = "\u4fdd\u5b58\u5931\u8d25\uff0c\u8bf7\u518d\u8bd5\u4e00\u6b21"
            desktop.show_notice("\u56de\u5fc6\u672c\u4fdd\u5b58\u5931\u8d25", seconds=2.5)
        return
    runtime_result = _toolbox_runtime(desktop).handle_touch(released_desktop, desktop, item, pos)
    if runtime_result == "drawing":
        desktop.r5_return_to_toolbox = True
        desktop.modal = "drawing"
        desktop.drawing = False
        desktop.last_draw_pos = None
        desktop.speak_readable("\u6253\u5f00\u661f\u5b9d\u753b\u677f", page="drawing")
    elif runtime_result:
        _emit_ui_interaction_event(
            runtime_result,
            tool_slug=str(item.get("slug") or ""),
            tool_kind=str(item.get("kind") or ""),
        )
    return
    kind = str(item.get("kind") or "").casefold()
    if primary.collidepoint(pos):
        if kind in TOOLBOX_DRAWING_KINDS:
            desktop.r5_return_to_toolbox = True
            desktop.modal = "drawing"
            desktop.drawing = False
            desktop.last_draw_pos = None
            desktop.speak_readable("\u6253\u5f00\u661f\u5b9d\u753b\u677f", page="drawing")
            return
        if kind in TOOLBOX_TIMER_KINDS:
            desktop.r5_return_to_toolbox = True
            desktop.modal = "pomodoro"
            desktop.speak_readable("\u6253\u5f00\u4e13\u5fc3\u5c0f\u949f", page="pomodoro")
            return
        desktop.r5_toolbox_counter += 1
        desktop.r5_toolbox_message = "\u592a\u68d2\u4e86\uff0c\u5df2\u5b8c\u6210\u4e00\u6b21\u3002"
        desktop.speak_readable(desktop.r5_toolbox_message, page="tool_activity")
        return
    if secondary.collidepoint(pos):
        desktop.r5_toolbox_counter += 1
        desktop.r5_toolbox_message = "\u65b0\u7684\u5c0f\u4efb\u52a1\u6765\u5566\uff0c\u8bd5\u8bd5\u770b\u3002"
        desktop.speak_readable(desktop.r5_toolbox_message, page="tool_activity")



def _open_drawer_toolbox(desktop: Any) -> None:
    """Route the released drawer's toolbox tile to the embedded 85-tool UI."""
    desktop.mark_user_activity()
    desktop.speak_readable("\u6253\u5f00\u767e\u5b9d\u7bb1", page="drawer")
    _toolbox_open(desktop)
    return
    result = _open_visual_tools({})
    desktop.drawer_open = False
    desktop.modal = None
    desktop.drawing = False
    desktop.last_draw_pos = None
    if result.get("ok"):
        desktop.show_notice("\u5df2\u6253\u5f00\u767e\u5b9d\u7bb185\u4e2a\u5c0f\u5de5\u5177", seconds=3.0)
    else:
        desktop.show_notice("\u767e\u5b9d\u7bb1\u6253\u5f00\u5931\u8d25", seconds=3.0)


def _install_drawer_toolbox_bridge(released_desktop: Any) -> None:
    """Embed the canonical 85-tool browser into the released Pygame desktop."""
    launcher = released_desktop.DesktopLauncher
    if getattr(launcher, "_xingbao_r5_full_toolbox_bridge", False):
        return

    original_handle_touch = launcher.handle_touch
    original_handle_key = launcher.handle_key
    original_draw_modal = launcher.draw_modal
    original_handle_modal_touch = launcher._handle_modal_touch
    original_close_modal = launcher._close_modal
    original_handle_draw_point = launcher.handle_draw_point
    original_complete_drawing = launcher.complete_drawing
    original_open_game = launcher.open_game
    original_draw_widgets = launcher.draw_widgets
    original_layout = launcher.layout

    def quick_voice_controls(self: Any) -> dict[str, Any]:
        """Return the three compact, icon-only voice controls at bottom-right."""
        pygame = released_desktop.pygame
        width, height = self.screen.get_size()
        size = max(44, min(int(height * 0.082), int(width * 0.073)))
        gap = max(9, int(size * 0.18))
        bottom = height - max(12, int(height * 0.024))
        right = width - max(14, int(width * 0.016))
        names = ("voice", "stop", "next")
        return {
            name: pygame.Rect(right - (len(names) - index) * size - (len(names) - 1 - index) * gap, bottom - size, size, size)
            for index, name in enumerate(names)
        }

    def consume_quick_voice_tap(self: Any, pos: tuple[int, int]) -> bool:
        """Consume one physical touch only once across FINGERUP/MOUSEBUTTONUP."""
        now = time.monotonic()
        duplicate = _is_duplicate_quick_voice_tap(
            getattr(self, "_quick_voice_last_tap", None),
            pos,
            now=now,
        )
        self._quick_voice_last_tap = (now, int(pos[0]), int(pos[1]))
        return duplicate

    def draw_quick_voice_control(
        self: Any,
        name: str,
        rect: Any,
        fill: tuple[int, int, int],
        border: tuple[int, int, int],
        *,
        icon_color: tuple[int, int, int],
        icon_scale: float = 0.62,
    ) -> None:
        """Draw a coloured touch target plus the supplied transparent icon."""
        pygame = released_desktop.pygame
        released_desktop.rounded_panel(
            self.screen,
            rect,
            fill,
            border=border,
            radius=max(16, rect.w // 2),
            width=1,
        )
        cache = getattr(self, "_quick_voice_icon_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._quick_voice_icon_cache = cache
        icon_side = max(18, int(rect.w * icon_scale))
        cache_key = (name, icon_side)
        icon = cache.get(cache_key)
        if icon is None:
            try:
                raw_icon = pygame.image.load(str(ACTION_BUTTON_ASSET_DIR / f"{name}.png")).convert_alpha()
                # The supplied glyphs are black with a transparent alpha
                # mask.  Add the accent colour while preserving that mask.
                raw_icon.fill((*icon_color, 0), special_flags=pygame.BLEND_RGB_ADD)
                icon = pygame.transform.smoothscale(raw_icon, (icon_side, icon_side))
                cache[cache_key] = icon
            except (pygame.error, OSError):
                icon = False
        if icon:
            self.screen.blit(icon, icon.get_rect(center=rect.center))

    def layout(self: Any) -> dict[str, Any]:
        """Retain the desktop's normal top-system hit areas unchanged."""
        return original_layout(self)

    def handle_draw_point(self: Any, pos: tuple[int, int], start: bool = False) -> Any:
        was_empty = not bool(getattr(self, "drawing_has_content", False))
        result = original_handle_draw_point(self, pos, start=start)
        if was_empty and bool(getattr(self, "drawing_has_content", False)):
            _emit_ui_interaction_event("drawing_started", scene="drawing_board")
        return result

    def complete_drawing(self: Any) -> Any:
        result = original_complete_drawing(self)
        if result:
            _emit_ui_interaction_event("drawing_completed", scene="drawing_board")
        return result

    def open_game(self: Any) -> Any:
        _emit_ui_interaction_event("game_started", scene="game_center")
        return original_open_game(self)

    def draw_modal(self: Any) -> Any:
        if self.modal == TOOLBOX_GRID_MODAL:
            _draw_toolbox_grid(released_desktop, self)
            return None
        if self.modal == TOOLBOX_ACTIVITY_MODAL:
            _draw_toolbox_activity(released_desktop, self)
            return None
        return original_draw_modal(self)

    def draw_widgets(self: Any) -> Any:
        result = original_draw_widgets(self)
        pending_voice_notice = str(getattr(self, "_pending_voice_notice", "") or "")
        if pending_voice_notice:
            self._pending_voice_notice = ""
            self.show_notice(pending_voice_notice, seconds=2.5)
        if self.modal or self.drawer_open:
            return result
        controls = quick_voice_controls(self)
        # Near-white fills let the three controls sit quietly in changing
        # scene backgrounds; colour is concentrated in the glyph instead of
        # competing with the main Xingbao illustration.
        draw_quick_voice_control(
            self, "voice", controls["voice"], (247, 251, 253), (220, 232, 239),
            icon_color=(72, 151, 194),
        )
        draw_quick_voice_control(
            self, "stop", controls["stop"], (253, 248, 248), (240, 226, 225),
            icon_color=(197, 107, 103), icon_scale=0.34,
        )
        draw_quick_voice_control(
            self, "next", controls["next"], (248, 252, 248), (223, 237, 226),
            icon_color=(86, 163, 105), icon_scale=0.34,
        )
        self.register_read_target(controls["voice"], "呼唤星宝。点击后等同于说星宝星宝，会开启新的聊天。", page="desktop")
        self.register_read_target(controls["stop"], "停止对话。点击后星宝会停止聆听，需要再次说星宝星宝才会继续。", page="desktop")
        self.register_read_target(controls["next"], "继续。点击后星宝会继续当前的表达步骤。", page="desktop")
        return result

    def handle_modal_touch(self: Any, pos: tuple[int, int]) -> Any:
        if self.modal in {TOOLBOX_GRID_MODAL, TOOLBOX_ACTIVITY_MODAL}:
            _handle_toolbox_touch(released_desktop, self, pos)
            return None
        return original_handle_modal_touch(self, pos)

    def close_modal(self: Any) -> Any:
        return_to_toolbox = bool(getattr(self, "r5_return_to_toolbox", False))
        source_modal = self.modal
        result = original_close_modal(self)
        if return_to_toolbox and source_modal in {"drawing", "pomodoro"}:
            self.r5_return_to_toolbox = False
            self.modal = TOOLBOX_ACTIVITY_MODAL
        return result

    def handle_touch(self: Any, pos: tuple[int, int]) -> Any:
        # The restored native parent entry owns the far-right header zone.
        if (
            not self.modal
            and not self.drawer_open
            and original_layout(self)["parent"].collidepoint(pos)
        ):
            return original_handle_touch(self, pos)
        if (
            not self.modal
            and not self.drawer_open
            and quick_voice_controls(self)["voice"].collidepoint(pos)
        ):
            if consume_quick_voice_tap(self, pos):
                return None
            def handle_wake_delivery(result: dict[str, Any]) -> None:
                if not bool(result.get("ok")):
                    # The sender runs off the Pygame thread.  The render loop
                    # consumes this small pending value and updates its notice
                    # safely on the UI thread.
                    self._pending_voice_notice = "语音未开启"

            _emit_ui_interaction_event(
                "synthetic_wake",
                on_delivery_result=handle_wake_delivery,
                scene="voice_conversation",
            )
            self.show_notice("正在呼唤星宝", seconds=1.8)
            return None
        if (
            not self.modal
            and not self.drawer_open
            and quick_voice_controls(self)["stop"].collidepoint(pos)
        ):
            if consume_quick_voice_tap(self, pos):
                return None
            _emit_ui_interaction_event(
                "conversation_stop",
                scene="voice_conversation",
            )
            self.show_notice("正在停止聊天", seconds=1.8)
            return None
        if (
            not self.modal
            and not self.drawer_open
            and quick_voice_controls(self)["next"].collidepoint(pos)
        ):
            if consume_quick_voice_tap(self, pos):
                return None
            _emit_ui_interaction_event(
                "guided_expression_recover",
                scene="guided_expression",
            )
            self.show_notice("星宝正在继续刚才的对话", seconds=1.8)
            return None
        if (
            not self.modal
            and self.drawer_open
            and self.drawer_buttons()["toolbox"].collidepoint(pos)
        ):
            _open_drawer_toolbox(self)
            return None
        return original_handle_touch(self, pos)

    def handle_key(self: Any, key: int) -> Any:
        if self.modal in {TOOLBOX_GRID_MODAL, TOOLBOX_ACTIVITY_MODAL}:
            self.mark_user_activity()
            if key == released_desktop.pygame.K_ESCAPE:
                self.modal = TOOLBOX_GRID_MODAL if self.modal == TOOLBOX_ACTIVITY_MODAL else None
                return None
            if self.modal == TOOLBOX_GRID_MODAL:
                items = _toolbox_state(self)
                pages = max(1, (len(items) + TOOLBOX_PAGE_SIZE - 1) // TOOLBOX_PAGE_SIZE)
                if key in (released_desktop.pygame.K_LEFT, released_desktop.pygame.K_UP):
                    self.r5_toolbox_page = max(0, self.r5_toolbox_page - 1)
                    return None
                if key in (released_desktop.pygame.K_RIGHT, released_desktop.pygame.K_DOWN):
                    self.r5_toolbox_page = min(pages - 1, self.r5_toolbox_page + 1)
                    return None
            return None
        if (
            not self.modal
            and self.drawer_open
            and key in (released_desktop.pygame.K_RETURN, released_desktop.pygame.K_SPACE)
            and int(self.drawer_focus) == 0
        ):
            _open_drawer_toolbox(self)
            return None
        return original_handle_key(self, key)

    launcher.handle_touch = handle_touch
    launcher.handle_key = handle_key
    launcher.draw_widgets = draw_widgets
    launcher.draw_modal = draw_modal
    launcher._handle_modal_touch = handle_modal_touch
    launcher._close_modal = close_modal
    launcher.handle_draw_point = handle_draw_point
    launcher.complete_drawing = complete_drawing
    launcher.open_game = open_game
    launcher.layout = layout
    launcher._xingbao_r5_full_toolbox_bridge = True


def phase1_modal_for_command(command: dict[str, Any]) -> str | None:
    """Map the r5 high-level toolbox commands to released desktop modals."""
    name = str(command.get("name") or "").strip()
    params = command.get("params")
    safe_params = dict(params) if isinstance(params, dict) else {}
    if name == "open_visual_tools":
        return "toolbox"
    if name != "launch_visual_tool":
        return None
    slug = str(safe_params.get("tool_slug") or "").strip().casefold()
    return "drawing" if slug in DRAWING_TOOL_SLUGS else None


def _load_released_ui(ui_dir: Path):
    resolved = ui_dir.expanduser().resolve()
    if not (resolved / "desktop.py").is_file():
        raise FileNotFoundError(f"released touch UI is missing: {resolved / 'desktop.py'}")
    sys.path.insert(0, str(resolved))
    import desktop as released_desktop  # type: ignore
    from examples.central_ui_dispatcher_example import (  # type: ignore
        dispatch_assistant_output as released_dispatch,
    )
    from src.board_adapter import runtime as board_runtime  # type: ignore

    return released_desktop, released_dispatch, board_runtime


def _apply_phase1_command(board_runtime: Any, command: dict[str, Any]) -> dict[str, Any]:
    name = str(command.get("name") or "").strip()
    params = command.get("params")
    safe_params = dict(params) if isinstance(params, dict) else {}

    def apply_on_ui_thread() -> dict[str, Any]:
        desktop = board_runtime.desktop
        if desktop is None:
            return {"ok": False, "action": name, "error": "desktop_not_bound"}

        if board_runtime.app is not None and getattr(board_runtime.app, "running", False):
            board_runtime.app.stop()
        board_runtime.pending_game = None

        if name == "return_to_desktop":
            desktop.modal = None
            desktop.drawer_open = False
            desktop.drawing = False
            desktop.last_draw_pos = None
            desktop.mark_user_activity()
            return {
                "ok": True,
                "action": name,
                "page": "desktop",
                "executed_on_ui_thread": True,
            }

        if name == "open_drawer":
            desktop.modal = None
            desktop.drawer_open = True
            desktop.drawing = False
            desktop.last_draw_pos = None
            desktop.mark_user_activity()
            return {
                "ok": True,
                "action": name,
                "page": "drawer",
                "executed_on_ui_thread": True,
            }

        if name == "open_desktop_modal":
            modal = str(safe_params.get("modal") or "").strip().casefold()
            if modal not in VOICE_MODAL_WHITELIST:
                return {"ok": False, "action": name, "error": "unsupported_desktop_modal"}
            desktop.modal = modal
            desktop.drawer_open = False
            desktop.drawing = False
            desktop.last_draw_pos = None
            if modal == "rest":
                desktop.rest_started_at = None
                desktop.eye_rest_recorded = False
            desktop.mark_user_activity()
            return {
                "ok": True,
                "action": name,
                "page": modal,
                "executed_on_ui_thread": True,
            }

        slug = str(safe_params.get("tool_slug") or "").strip().casefold()
        # ``draw`` is an in-process canvas, not an 85-tool activity card.
        # Handle it before the generic toolbox launcher: otherwise that
        # branch reports success for ``tool_activity`` while no canvas is
        # visible to the child.
        if name == "launch_visual_tool" and slug in DRAWING_TOOL_SLUGS:
            desktop.modal = "drawing"
            desktop.drawer_open = False
            desktop.drawing = False
            desktop.last_draw_pos = None
            desktop.r5_return_to_toolbox = True
            desktop.mark_user_activity()
            desktop.show_notice("星宝画板", seconds=2.0)
            return {
                "ok": True,
                "action": name,
                "page": "drawing",
                "tool_slug": slug,
                "embedded": True,
                "executed_on_ui_thread": True,
            }
        if name in {"open_visual_tools", "launch_visual_tool"}:
            _toolbox_open(desktop, slug)
            desktop.mark_user_activity()
            return {
                "ok": True,
                "action": name,
                "page": "toolbox" if not slug else "tool_activity",
                "tool_slug": slug,
                "embedded": True,
                "executed_on_ui_thread": True,
            }
        if name == "open_visual_tools" or (
            name == "launch_visual_tool" and slug not in DRAWING_TOOL_SLUGS
        ):
            launch_result = _open_visual_tools(safe_params)
            if launch_result.get("ok"):
                desktop.modal = None
                desktop.drawer_open = False
                desktop.drawing = False
                desktop.last_draw_pos = None
                desktop.mark_user_activity()
                desktop.show_notice("\u5df2\u6253\u5f0085\u4e2a\u5c0f\u5de5\u5177", seconds=3.0)
            return {
                "ok": bool(launch_result.get("ok")),
                "action": name,
                "page": "visual_tools",
                "tool_slug": slug,
                "visual_tools": launch_result,
                "executed_on_ui_thread": True,
            }

        modal = phase1_modal_for_command(command)
        if modal is None:
            return {
                "ok": False,
                "action": name,
                "error": "unsupported_visual_tool",
                "tool_slug": safe_params.get("tool_slug"),
            }
        desktop.modal = modal
        desktop.drawer_open = modal == "toolbox"
        desktop.drawing = False
        desktop.last_draw_pos = None
        desktop.mark_user_activity()
        desktop.show_notice("百宝箱" if modal == "toolbox" else "星宝画板", seconds=3.0)
        return {
            "ok": True,
            "action": name,
            "page": modal,
            "tool_slug": safe_params.get("tool_slug"),
            "executed_on_ui_thread": True,
        }

    return board_runtime.submit(apply_on_ui_thread, timeout=15.0)


def _install_game_status_overlay(released_desktop: Any) -> None:
    """Draw central voice state above the active full-screen game."""
    app_class = released_desktop.XingbaoApp
    if getattr(app_class, "_xingbao_central_status_overlay", False):
        return
    original_render = app_class.render

    def render(self: Any) -> Any:
        result = original_render(self)
        text = str(getattr(self, "_central_status_text", "") or "").strip()
        until = int(getattr(self, "_central_status_until", 0) or 0)
        pygame = released_desktop.pygame
        if not text or pygame.time.get_ticks() >= until:
            return result

        is_search_status = text.startswith(SEARCH_STATUS_PREFIX)
        if is_search_status:
            text = text[len(SEARCH_STATUS_PREFIX):]
        loading_status = is_search_status or released_desktop.is_loading_status_text(text)

        width, height = self.screen.get_size()
        text_size = max(23, int(height * 0.035))
        text_font = released_desktop.font(text_size, bold=True)
        horizontal_padding = max(36, int(height * 0.06))
        max_width = int(width * 0.88)
        icon_width = int(text_size * 1.5) if is_search_status else 0
        panel_width = min(
            max_width,
            max(int(width * 0.60), text_font.size(text)[0] + horizontal_padding + icon_width),
        )
        usable_width = panel_width - horizontal_padding
        lines: list[str] = []
        current = ""
        for character in text:
            candidate = current + character
            if current and text_font.size(candidate)[0] > usable_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
        line_height = text_font.get_linesize()
        panel_height = max(56, line_height * len(lines) + max(20, int(height * 0.03)))
        panel = pygame.Rect(0, 0, panel_width, panel_height)
        panel.midbottom = (width // 2, int(height * 0.94))
        shade = pygame.Surface(panel.size, pygame.SRCALPHA)
        shade.fill((8, 35, 58, 232))
        self.screen.blit(shade, panel.topleft)
        pygame.draw.rect(
            self.screen,
            (92, 210, 255),
            panel,
            width=max(2, int(height * 0.004)),
            border_radius=max(12, int(height * 0.022)),
        )
        text_top = panel.centery - (line_height * len(lines)) // 2
        text_center_x = panel.centerx
        if is_search_status:
            radius = max(5, int(text_size * 0.27))
            lens_x = panel.left + horizontal_padding // 2
            lens_y = panel.centery
            pygame.draw.circle(self.screen, (92, 210, 255), (lens_x, lens_y), radius, width=2)
            pygame.draw.line(
                self.screen,
                (92, 210, 255),
                (lens_x + radius - 1, lens_y + radius - 1),
                (lens_x + radius + max(4, radius // 2), lens_y + radius + max(4, radius // 2)),
                width=3,
            )
            text_center_x += icon_width // 2
        for index, line in enumerate(lines):
            draw = (
                released_desktop.draw_loading_status_text
                if loading_status
                else released_desktop.draw_text
            )
            draw(
                self.screen,
                line,
                (text_center_x, text_top + index * line_height + line_height // 2),
                text_size,
                color=(245, 252, 255),
                bold=True,
            )
        return result

    app_class.render = render
    app_class._xingbao_central_status_overlay = True


def _apply_game_status_notice(
    board_runtime: Any,
    text: str,
    *,
    duration_ms: int,
    subtitle_priority: str = "external",
) -> dict[str, Any]:
    """Show central status in the active game or the visible desktop shell."""
    clean_text = _sanitize_status_text(text)
    if not clean_text:
        return {"ok": True, "action": "game_status_notice", "skipped": True}

    def apply_on_ui_thread() -> dict[str, Any]:
        app = board_runtime.app
        seconds = max(0.4, min(30.0, float(duration_ms or 4000) / 1000.0))
        if app is not None and getattr(app, "running", False):
            app._central_status_text = clean_text
            app._central_status_until = (
                __import__("pygame").time.get_ticks() + int(seconds * 1000)
            )
            return {
                "ok": True,
                "action": "game_status_notice",
                "text": clean_text,
                "duration_ms": int(seconds * 1000),
                "executed_on_ui_thread": True,
            }
        desktop = board_runtime.desktop
        if desktop is None or not callable(getattr(desktop, "show_notice", None)):
            return {
                "ok": True,
                "action": "desktop_status_notice",
                "skipped": True,
                "reason": "desktop_not_bound",
            }
        desktop.show_notice(clean_text, seconds=seconds, priority=subtitle_priority)
        return {
            "ok": True,
            "action": "desktop_status_notice",
            "text": clean_text,
            "duration_ms": int(seconds * 1000),
            "executed_on_ui_thread": True,
        }

    return board_runtime.submit(apply_on_ui_thread, timeout=5.0)


def _apply_vision_distance_status(
    board_runtime: Any,
    status: dict[str, Any],
) -> dict[str, Any]:
    """Apply a vision distance transition directly on the Pygame UI thread."""
    if "distance_too_close" not in status:
        return {"ok": False, "action": "vision_distance_status", "error": "missing_distance"}
    too_close = bool(int(status.get("distance_too_close") or 0))

    def apply_on_ui_thread() -> dict[str, Any]:
        desktop = board_runtime.desktop
        if desktop is None:
            return {"ok": False, "action": "vision_distance_status", "error": "desktop_not_bound"}
        if "needs_water" in status:
            needs_water = bool(int(status.get("needs_water") or 0))
        else:
            needs_water = bool((getattr(desktop, "vision_state", {}) or {}).get("needs_water"))
        # Persist locally too, so the desktop's normal half-second status-file
        # poll cannot overwrite the bridge-delivered transition.
        try:
            desktop.vision_adapter.write(too_close, needs_water)
        except OSError:
            pass
        state = desktop.update_vision_state(too_close, needs_water, hold_seconds=0.8)
        return {
            "ok": True,
            "action": "vision_distance_status",
            "distance_too_close": int(too_close),
            "text": "坐得太近啦" if too_close else "坐得刚刚好",
            "state": state,
            "executed_on_ui_thread": True,
        }

    return board_runtime.submit(apply_on_ui_thread, timeout=5.0)


def build_dispatcher(
    released_dispatch: Callable[[dict[str, Any]], dict[str, Any]],
    board_runtime: Any,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Extend the released dispatcher without modifying its release directory."""

    def dispatch(message: dict[str, Any]) -> dict[str, Any]:
        payload = message.get("payload")
        safe_payload = dict(payload) if isinstance(payload, dict) else {}
        snapshot_payload = safe_payload.get("camera_snapshot")
        if snapshot_payload is not None:
            if not isinstance(snapshot_payload, dict):
                result = {
                    "ok": False,
                    "action": "camera_snapshot",
                    "error": "invalid_camera_snapshot",
                }
            else:
                action = snapshot_payload.get("action")
                if action == "show":
                    data_uri = snapshot_payload.get("data_uri")
                    width = snapshot_payload.get("width")
                    height = snapshot_payload.get("height")
                    mirror = bool(snapshot_payload.get("mirror", True))
                    is_valid = (
                        isinstance(data_uri, str)
                        and type(width) is int
                        and type(height) is int
                        and width > 0
                        and height > 0
                    )
                    if not is_valid:
                        result = {
                            "ok": False,
                            "action": "camera_snapshot_show",
                            "error": "invalid_camera_snapshot",
                        }
                    else:
                        def apply_on_ui_thread() -> dict[str, Any]:
                            desktop = board_runtime.desktop
                            setter = getattr(desktop, "set_camera_snapshot", None)
                            if not callable(setter):
                                return {
                                    "ok": False,
                                    "action": "camera_snapshot_show",
                                    "error": "desktop_not_bound",
                                }
                            try:
                                applied = setter(data_uri, width, height, mirror=mirror)
                            except TypeError:
                                # Older in-process desktop adapters only
                                # support the original three arguments.
                                applied = setter(data_uri, width, height)
                            return {
                                "ok": bool(applied),
                                "action": "camera_snapshot_show",
                            }

                        result = board_runtime.submit(apply_on_ui_thread, timeout=5.0)
                elif action == "clear":
                    def apply_on_ui_thread() -> dict[str, Any]:
                        desktop = board_runtime.desktop
                        clearer = getattr(desktop, "clear_camera_snapshot", None)
                        if not callable(clearer):
                            return {
                                "ok": False,
                                "action": "camera_snapshot_clear",
                                "error": "desktop_not_bound",
                            }
                        return {
                            "ok": bool(clearer()),
                            "action": "camera_snapshot_clear",
                        }

                    result = board_runtime.submit(apply_on_ui_thread, timeout=5.0)
                else:
                    result = {
                        "ok": False,
                        "action": "camera_snapshot",
                        "error": "invalid_camera_snapshot",
                    }
            return {
                "type": "command_result",
                "request_id": message.get("request_id"),
                "ok": bool(result.get("ok")),
                "results": [result],
            }
        scene_payload = safe_payload.get("xingbao_scene")
        if isinstance(scene_payload, dict):
            scene_id = scene_payload.get("id")
            if type(scene_id) is not int or not 0 <= scene_id <= 27:
                result = {
                    "ok": False, "action": "xingbao_scene", "error": "invalid_scene_id",
                }
            else:
                def apply_on_ui_thread() -> dict[str, Any]:
                    desktop = board_runtime.desktop
                    setter = getattr(desktop, "set_xingbao_scene", None)
                    if not callable(setter):
                        return {"ok": False, "action": "xingbao_scene", "error": "desktop_not_bound"}
                    return {
                        "ok": bool(setter(scene_id)), "action": "xingbao_scene", "id": scene_id,
                        "source": str(scene_payload.get("source") or "unknown"),
                    }

                result = board_runtime.submit(apply_on_ui_thread, timeout=5.0)
            return {
                "type": "command_result", "request_id": message.get("request_id"),
                "ok": bool(result.get("ok")), "results": [result],
            }
        dialogue_state = safe_payload.get("dialogue_subtitle_state")
        if isinstance(dialogue_state, dict):
            active = bool(dialogue_state.get("active"))

            def apply_on_ui_thread() -> dict[str, Any]:
                desktop = board_runtime.desktop
                if desktop is None:
                    return {"ok": True, "action": "dialogue_subtitle_state", "skipped": True}
                desktop.dialogue_subtitle_active = active
                return {"ok": True, "action": "dialogue_subtitle_state", "active": active}

            result = board_runtime.submit(apply_on_ui_thread, timeout=5.0)
            return {
                "type": "command_result", "request_id": message.get("request_id"),
                "ok": bool(result.get("ok")), "results": [result],
            }
        vision_status = safe_payload.get("vision_status")
        if isinstance(vision_status, dict):
            result = _apply_vision_distance_status(board_runtime, vision_status)
            return {
                "type": "command_result",
                "request_id": message.get("request_id"),
                "ok": bool(result.get("ok")),
                "results": [result],
            }
        command = safe_payload.get("ui_command")
        safe_command = dict(command) if isinstance(command, dict) else {}
        name = str(safe_command.get("name") or "").strip()
        is_phase1_command = name in {
            "open_visual_tools",
            "launch_visual_tool",
            "return_to_desktop",
            "open_drawer",
            "open_desktop_modal",
        }
        if not is_phase1_command:
            response = released_dispatch(message)
        else:
            forwarded = copy.deepcopy(message)
            forwarded_payload = forwarded.get("payload")
            if not isinstance(forwarded_payload, dict):
                forwarded_payload = {}
                forwarded["payload"] = forwarded_payload
            forwarded_payload["ui_command"] = None
            response = released_dispatch(forwarded)
            results = response.setdefault("results", [])
            phase1_result = _apply_phase1_command(board_runtime, safe_command)
            results.append(phase1_result)
            response["ok"] = bool(response.get("ok")) and bool(phase1_result.get("ok"))

        screen_text = str(safe_payload.get("screen_text") or "").strip()
        if screen_text:
            expression = safe_payload.get("screen_expression")
            safe_expression = dict(expression) if isinstance(expression, dict) else {}
            status_result = _apply_game_status_notice(
                board_runtime,
                screen_text,
                duration_ms=int(safe_expression.get("duration_ms") or 4000),
                subtitle_priority=str(safe_payload.get("subtitle_priority") or "external"),
            )
            response.setdefault("results", []).append(status_result)
            response["ok"] = bool(response.get("ok")) and bool(status_result.get("ok"))
        return response

    return dispatch


def _build_server(
    dispatch: Callable[[dict[str, Any]], dict[str, Any]],
    host: str,
    port: int,
) -> socketserver.ThreadingTCPServer:
    class NDJSONHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            for raw in self.rfile:
                try:
                    message = json.loads(raw.decode("utf-8-sig"))
                    if not isinstance(message, dict):
                        raise ValueError("NDJSON message must be an object")
                    response = dispatch(message)
                except Exception as exc:
                    response = {
                        "type": "command_result",
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                try:
                    self.wfile.write(
                        (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                    )
                except (BrokenPipeError, ConnectionResetError):
                    return

    class ThreadedNDJSONServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    return ThreadedNDJSONServer((host, port), NDJSONHandler)


def _released_desktop_pids(ui_dir: Path) -> list[int]:
    """Find only standalone desktop.py processes running from this UI release."""
    expected_cwd = ui_dir.expanduser().resolve()
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            cwd = (entry / "cwd").resolve()
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if cwd != expected_cwd:
            continue
        arguments = [item.decode("utf-8", errors="replace") for item in argv if item]
        if any(Path(item).name == "desktop.py" for item in arguments):
            matches.append(pid)
    return matches


def _stop_competing_released_ui(ui_dir: Path) -> list[int]:
    """Stop stale released-UI instances without touching unrelated projects."""
    pids = _released_desktop_pids(ui_dir)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if pids:
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            live = [pid for pid in pids if Path(f"/proc/{pid}").exists()]
            if not live:
                break
            time.sleep(0.1)
        for pid in pids:
            if Path(f"/proc/{pid}").exists():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        print(f"[phase1] stopped competing released UI pids={pids}", flush=True)
    return pids


def _watch_competing_released_ui(
    ui_dir: Path,
    board_runtime: Any,
    stopped: threading.Event,
) -> None:
    while not stopped.wait(1.0):
        stopped_pids = _stop_competing_released_ui(ui_dir)
        desktop = board_runtime.desktop
        if stopped_pids and desktop is not None and getattr(desktop, "active", False):
            # A stale fullscreen window can leave GNOME in front after it exits.
            # Queue exactly one display reassertion on Pygame's main thread.
            board_runtime.submit(desktop.reactivate_display, wait=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start display, touch UI, and r5 bridge only.")
    parser.add_argument("--ui-dir", type=Path, default=DEFAULT_UI_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    ui_dir = args.ui_dir.expanduser().resolve()
    _stop_competing_released_ui(ui_dir)
    released_desktop, released_dispatch, board_runtime = _load_released_ui(ui_dir)
    _install_drawer_toolbox_bridge(released_desktop)
    _install_game_status_overlay(released_desktop)
    dispatcher = build_dispatcher(released_dispatch, board_runtime)
    server = _build_server(dispatcher, args.host, args.port)
    bridge = threading.Thread(
        target=server.serve_forever,
        name="r5-phase1-ui-bridge",
        daemon=True,
    )
    bridge.start()
    stop_watcher = threading.Event()
    watcher = threading.Thread(
        target=_watch_competing_released_ui,
        args=(ui_dir, board_runtime, stop_watcher),
        name="r5-phase1-ui-single-instance",
        daemon=True,
    )
    watcher.start()
    try:
        return int(
            released_desktop.main(
                [
                    "--fullscreen",
                    "--low-effects",
                    "--no-central-bridge",
                    "--no-vision",
                ]
            )
            or 0
        )
    finally:
        stop_watcher.set()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
