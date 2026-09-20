"""Best-effort native Wayland minimize request for the GNOME board session."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable


GDBUS_MINIMIZE_PREFIX = (
    "(() => { const window = global.get_window_actors()"
    ".map(actor => actor.meta_window)"
)


def request_gnome_window_minimize(
    pid: int,
    *,
    window_title: str = "星宝学习桌面",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """Ask Mutter to minimize the Wayland window owned by ``pid``.

    Wayland clients cannot minimize their own fullscreen surface through an
    SDL protocol.  The board's GNOME Shell exposes a session-local D-Bus API,
    so target the compositor's Meta.Window by its unique desktop title.  SDL
    Wayland windows report ``MetaWindow.get_pid() == -1`` on this board.
    """
    if pid <= 0:
        return False
    safe_title = json.dumps(window_title, ensure_ascii=False)
    script = (
        f"{GDBUS_MINIMIZE_PREFIX}.find(window => window.get_title() === {safe_title}); "
        "if (!window) return false; window.minimize(); return true; })()"
    )
    command = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.gnome.Shell",
        "--object-path",
        "/org/gnome/Shell",
        "--method",
        "org.gnome.Shell.Eval",
        script,
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and "'true'" in completed.stdout


def minimize_window(
    pid: int,
    *,
    video_driver: str,
    compositor_minimize: Callable[[int], bool] = request_gnome_window_minimize,
    iconify: Callable[[], bool],
) -> bool:
    """Minimize through Mutter for Wayland, or SDL for legacy X11 sessions."""
    if video_driver.casefold() == "wayland":
        return compositor_minimize(pid)
    return bool(iconify())
