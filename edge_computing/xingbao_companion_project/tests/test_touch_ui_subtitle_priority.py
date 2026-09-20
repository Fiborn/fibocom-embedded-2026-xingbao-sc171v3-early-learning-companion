"""Regression coverage for touch-UI subtitle priority."""

import importlib
import sys
from pathlib import Path


def _load_desktop_module():
    """Load the standalone touch UI without resolving the project-root ``src``."""
    touch_ui_root = Path(__file__).resolve().parents[1] / "components" / "touch_ui"
    sys.path.insert(0, str(touch_ui_root))
    sys.modules.pop("src", None)
    try:
        return importlib.import_module("desktop")
    finally:
        sys.path.remove(str(touch_ui_root))


def test_external_notice_cannot_replace_active_dialogue_subtitle(monkeypatch):
    desktop = _load_desktop_module()
    launcher = object.__new__(desktop.DesktopLauncher)
    launcher.dialogue_subtitle_active = True
    launcher.notice = "正在和星宝对话"
    launcher.notice_until = 123
    monkeypatch.setattr(desktop.pygame.time, "get_ticks", lambda: 999)

    assert launcher.show_notice("已点击按钮", seconds=1.6, priority="external") is False
    assert launcher.notice == "正在和星宝对话"
    assert launcher.notice_until == 123

    assert launcher.show_notice("星宝正在思考", seconds=1.6, priority="dialogue") is True
    assert launcher.notice == "星宝正在思考"
    assert launcher.notice_until == 2599
