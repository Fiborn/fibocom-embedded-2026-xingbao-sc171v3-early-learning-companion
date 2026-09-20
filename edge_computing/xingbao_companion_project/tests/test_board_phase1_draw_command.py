from types import SimpleNamespace

from tools.board_phase1_ui import _apply_phase1_command, _is_duplicate_quick_voice_tap


class _Desktop:
    modal = None
    drawer_open = True
    drawing = True
    last_draw_pos = (1, 1)
    r5_return_to_toolbox = False

    def mark_user_activity(self) -> None:
        self.marked = True

    def show_notice(self, text: str, *, seconds: float) -> None:
        self.notice = (text, seconds)


class _Runtime:
    def __init__(self) -> None:
        self.desktop = _Desktop()
        self.app = None
        self.pending_game = object()

    @staticmethod
    def submit(callback, *, timeout: float):  # type: ignore[no-untyped-def]
        return callback()


def test_draw_tool_command_opens_visible_drawing_canvas() -> None:
    runtime = _Runtime()

    result = _apply_phase1_command(
        runtime,
        {"name": "launch_visual_tool", "params": {"tool_slug": "draw"}},
    )

    assert result["ok"] is True
    assert result["page"] == "drawing"
    assert runtime.desktop.modal == "drawing"
    assert runtime.desktop.r5_return_to_toolbox is True


def test_quick_voice_tap_deduplicates_wayland_mouse_and_finger_release() -> None:
    previous = (10.0, 100, 200)

    assert _is_duplicate_quick_voice_tap(previous, (112, 214), now=10.20) is True
    assert _is_duplicate_quick_voice_tap(previous, (126, 214), now=10.20) is False
    assert _is_duplicate_quick_voice_tap(previous, (112, 214), now=10.26) is False
