from pathlib import Path
import subprocess
import sys


TOUCH_UI_DIR = Path(__file__).resolve().parents[1] / "components" / "touch_ui"
sys.path.insert(0, str(TOUCH_UI_DIR))

from src.wayland_minimize import minimize_window, request_gnome_window_minimize


def test_request_gnome_window_minimize_targets_the_ui_window_title_when_wayland_has_no_pid() -> None:
    received: list[object] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        received.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="(true, 'true')\n", stderr="")

    assert request_gnome_window_minimize(
        4242,
        window_title="星宝学习桌面",
        runner=runner,
    ) is True

    command, kwargs = received[0]
    assert command[:8] == [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.gnome.Shell",
        "--object-path",
        "/org/gnome/Shell",
        "--method",
    ]
    assert command[8] == "org.gnome.Shell.Eval"
    assert "get_title() === \"星宝学习桌面\"" in command[9]
    assert ".minimize()" in command[9]
    assert kwargs["timeout"] == 2.0


def test_request_gnome_window_minimize_reports_rejected_shell_request() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="(true, 'false')\n", stderr="")

    assert request_gnome_window_minimize(4242, runner=runner) is False


def test_minimize_window_uses_the_compositor_without_iconifying_wayland_surface() -> None:
    iconify_calls: list[bool] = []

    assert minimize_window(
        4242,
        video_driver="wayland",
        compositor_minimize=lambda pid: pid == 4242,
        iconify=lambda: iconify_calls.append(True) or True,
    ) is True
    assert iconify_calls == []
