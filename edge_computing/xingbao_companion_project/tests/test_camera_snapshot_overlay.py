"""Regression coverage for the in-memory camera snapshot preview."""

import base64
import importlib
import io
import os
import sys
from pathlib import Path

import pytest


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def _load_desktop_module():
    touch_ui_root = Path(__file__).resolve().parents[1] / "components" / "touch_ui"
    sys.path.insert(0, str(touch_ui_root))
    sys.modules.pop("src", None)
    try:
        return importlib.import_module("desktop")
    finally:
        sys.path.remove(str(touch_ui_root))


def _jpeg_uri(pygame, size=(640, 480)):
    image = pygame.Surface(size)
    image.fill((67, 152, 219))
    encoded = io.BytesIO()
    pygame.image.save(image, encoded, "snapshot.jpg")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")


def _two_tone_jpeg_uri(pygame, size=(64, 32)):
    image = pygame.Surface(size)
    image.fill((225, 30, 30), pygame.Rect(0, 0, size[0] // 2, size[1]))
    image.fill((30, 45, 225), pygame.Rect(size[0] // 2, 0, size[0] // 2, size[1]))
    encoded = io.BytesIO()
    pygame.image.save(image, encoded, "snapshot.jpg")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")


def _png_uri(pygame, size=(640, 480)):
    image = pygame.Surface(size)
    image.fill((228, 112, 97))
    encoded = io.BytesIO()
    pygame.image.save(image, encoded, "snapshot.png")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")


@pytest.fixture
def fake_desktop():
    desktop_module = _load_desktop_module()
    pygame = desktop_module.pygame
    pygame.init()
    pygame.display.set_mode((1000, 700))
    launcher = object.__new__(desktop_module.DesktopLauncher)
    launcher.screen = pygame.display.get_surface()
    launcher.camera_snapshot_surface = None
    launcher.camera_snapshot_size = None
    return launcher


def test_desktop_camera_snapshot_keeps_aspect_ratio_and_respects_subtitle_area(fake_desktop):
    data_uri = _jpeg_uri(sys.modules["desktop"].pygame)

    assert fake_desktop.set_camera_snapshot(data_uri, 640, 480) is True
    rect = fake_desktop.camera_snapshot_rect()
    assert rect.width <= int(fake_desktop.screen.get_width() * 0.62)
    assert rect.height <= int(fake_desktop.screen.get_height() * 0.58)
    assert rect.bottom < int(fake_desktop.screen.get_height() * 0.88)
    assert abs(rect.width / rect.height - 640 / 480) < 0.02


def test_desktop_camera_snapshot_is_horizontally_mirrored(fake_desktop):
    pygame = sys.modules["desktop"].pygame

    assert fake_desktop.set_camera_snapshot(_two_tone_jpeg_uri(pygame), 64, 32) is True

    left = fake_desktop.camera_snapshot_surface.get_at((8, 16))
    right = fake_desktop.camera_snapshot_surface.get_at((55, 16))
    assert left.b > left.r
    assert right.r > right.b


def test_loading_status_shine_sweeps_across_camera_and_search_text(fake_desktop):
    desktop_module = sys.modules["desktop"]
    pygame = desktop_module.pygame
    rect = pygame.Rect(100, 80, 300, 48)

    first = desktop_module.loading_status_shine_rect(rect, 24, now_ms=0)
    middle = desktop_module.loading_status_shine_rect(rect, 24, now_ms=700)

    assert desktop_module.is_loading_status_text("让我看一看") is True
    assert desktop_module.is_loading_status_text("[[SEARCH]] 正在查询中") is True
    assert middle.centerx > first.centerx


def test_invalid_camera_snapshot_does_not_replace_existing_overlay(fake_desktop):
    pygame = sys.modules["desktop"].pygame
    data_uri = _jpeg_uri(pygame)
    assert fake_desktop.set_camera_snapshot(data_uri, 640, 480) is True
    previous = fake_desktop.camera_snapshot_surface

    assert fake_desktop.set_camera_snapshot("data:text/plain;base64,QQ==", 1, 1) is False
    assert fake_desktop.camera_snapshot_surface is previous


def test_disguised_png_camera_snapshot_does_not_replace_existing_overlay(fake_desktop):
    pygame = sys.modules["desktop"].pygame
    assert fake_desktop.set_camera_snapshot(_jpeg_uri(pygame), 640, 480) is True
    previous = fake_desktop.camera_snapshot_surface

    assert fake_desktop.set_camera_snapshot(_png_uri(pygame), 640, 480) is False
    assert fake_desktop.camera_snapshot_surface is previous


def test_camera_snapshot_rejects_dimensions_that_do_not_match_the_jpeg(fake_desktop):
    pygame = sys.modules["desktop"].pygame
    assert fake_desktop.set_camera_snapshot(_jpeg_uri(pygame), 640, 480) is True
    previous = fake_desktop.camera_snapshot_surface
    mismatched_jpeg = _jpeg_uri(pygame, size=(320, 240))

    assert fake_desktop.set_camera_snapshot(mismatched_jpeg, 640, 480) is False
    assert fake_desktop.camera_snapshot_surface is previous


def test_camera_snapshot_rejects_data_larger_than_one_mebibyte(fake_desktop):
    oversized = base64.b64encode(b"x" * (1024 * 1024 + 1)).decode("ascii")

    assert fake_desktop.set_camera_snapshot(
        "data:image/jpeg;base64," + oversized, 640, 480
    ) is False
    assert fake_desktop.camera_snapshot_surface is None


class _DesktopRecorder:
    def __init__(self):
        self.received_snapshot = None
        self.clear_count = 0

    def set_camera_snapshot(self, data_uri, width, height):
        self.received_snapshot = (data_uri, width, height)
        return True

    def clear_camera_snapshot(self):
        self.clear_count += 1
        return True


class _BoardRuntime:
    def __init__(self):
        self.desktop = _DesktopRecorder()
        self.submissions = 0

    def submit(self, function, *args, **kwargs):
        self.submissions += 1
        return function(*args)


def _load_bridge_module():
    import tools.board_phase1_ui as bridge

    return bridge


def test_camera_snapshot_show_command_runs_on_ui_thread():
    runtime = _BoardRuntime()
    dispatch = _load_bridge_module().build_dispatcher(
        lambda _message: {"type": "command_result", "ok": True, "results": []}, runtime
    )
    data_uri = "data:image/jpeg;base64,AA=="

    response = dispatch({"payload": {"camera_snapshot": {
        "action": "show", "data_uri": data_uri, "width": 640, "height": 480,
    }}})

    assert response["ok"] is True
    assert response["results"][0]["action"] == "camera_snapshot_show"
    assert runtime.desktop.received_snapshot == (data_uri, 640, 480)
    assert runtime.submissions == 1
    assert data_uri not in repr(response)


def test_camera_snapshot_clear_command_is_idempotent():
    runtime = _BoardRuntime()
    dispatch = _load_bridge_module().build_dispatcher(
        lambda _message: {"type": "command_result", "ok": True, "results": []}, runtime
    )

    first = dispatch({"payload": {"camera_snapshot": {"action": "clear"}}})
    second = dispatch({"payload": {"camera_snapshot": {"action": "clear"}}})

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["results"][0]["action"] == "camera_snapshot_clear"
    assert runtime.desktop.clear_count == 2


def test_camera_snapshot_bridge_rejects_malformed_show_without_touching_overlay():
    runtime = _BoardRuntime()
    dispatch = _load_bridge_module().build_dispatcher(
        lambda _message: {"type": "command_result", "ok": True, "results": []}, runtime
    )

    response = dispatch({"payload": {"camera_snapshot": {
        "action": "show", "data_uri": "data:image/jpeg;base64,AA==", "width": 0, "height": 480,
    }}})

    assert response["ok"] is False
    assert response["results"][0]["error"] == "invalid_camera_snapshot"
    assert runtime.desktop.received_snapshot is None
    assert runtime.submissions == 0
