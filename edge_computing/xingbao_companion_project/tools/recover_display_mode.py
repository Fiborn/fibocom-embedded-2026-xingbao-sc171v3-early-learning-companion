"""Reapply the active Mutter display layout before the touch UI starts.

Some board cold boots report the built-in DSI panel as enabled while no frame is
scanned out to it.  Reapplying the already-active layout through Mutter forces a
safe, temporary modeset without persisting desktop settings or needing root.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Sequence, Tuple


_DISPLAY_BUS = "org.gnome.Mutter.DisplayConfig"
_DISPLAY_PATH = "/org/gnome/Mutter/DisplayConfig"
_DISPLAY_INTERFACE = "org.gnome.Mutter.DisplayConfig"
_TEMPORARY_APPLY_METHOD = 1


def _as_properties(value: object) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mode_id(modes: Iterable[Sequence[object]]) -> str:
    """Select the live mode, falling back only to Mutter's preferred mode."""
    cached: List[Sequence[object]] = list(modes)
    for mode in cached:
        if len(mode) >= 7 and _as_properties(mode[6]).get("is-current"):
            return str(mode[0])
    for mode in cached:
        if len(mode) >= 7 and _as_properties(mode[6]).get("is-preferred"):
            return str(mode[0])
    raise RuntimeError("No current or preferred display mode is available.")


def build_current_layout(state: Sequence[object]) -> Tuple[int, List[tuple]]:
    """Convert ``GetCurrentState`` output to ``ApplyMonitorsConfig`` input."""
    if len(state) != 4:
        raise RuntimeError("Unexpected Mutter display-state response.")
    serial, monitors, logical_monitors, _properties = state
    mode_by_spec: Dict[tuple, str] = {}
    for monitor in monitors:
        if len(monitor) < 2:
            raise RuntimeError("Unexpected physical-monitor entry.")
        specification = tuple(monitor[0])
        mode_by_spec[specification] = _mode_id(monitor[1])

    apply_layout: List[tuple] = []
    for logical_monitor in logical_monitors:
        if len(logical_monitor) < 6:
            raise RuntimeError("Unexpected logical-monitor entry.")
        x, y, scale, transform, primary, monitor_specs = logical_monitor[:6]
        configured_monitors = []
        for specification in monitor_specs:
            key = tuple(specification)
            mode_id = mode_by_spec.get(key)
            if not mode_id:
                raise RuntimeError("Active monitor has no selectable mode: {}".format(key))
            configured_monitors.append((str(key[0]), mode_id, {}))
        if not configured_monitors:
            raise RuntimeError("Logical monitor has no physical outputs.")
        apply_layout.append(
            (int(x), int(y), float(scale), int(transform), bool(primary), configured_monitors)
        )
    if not apply_layout:
        raise RuntimeError("Mutter reported no active logical monitors.")
    return int(serial), apply_layout


def _ensure_session_bus() -> None:
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/{}".format(os.getuid())
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path={}/bus".format(runtime_dir)


def reapply_current_layout() -> None:
    """Ask Mutter for a one-time modeset of its current display layout."""
    _ensure_session_bus()
    try:
        from gi.repository import Gio, GLib
    except ImportError as exc:
        raise RuntimeError("PyGObject is unavailable for display recovery.") from exc

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    state_result = connection.call_sync(
        _DISPLAY_BUS,
        _DISPLAY_PATH,
        _DISPLAY_INTERFACE,
        "GetCurrentState",
        None,
        None,
        Gio.DBusCallFlags.NONE,
        10000,
        None,
    )
    serial, layout = build_current_layout(state_result.unpack())
    parameters = GLib.Variant(
        "(uua(iiduba(ssa{sv}))a{sv})",
        (serial, _TEMPORARY_APPLY_METHOD, layout, {}),
    )
    connection.call_sync(
        _DISPLAY_BUS,
        _DISPLAY_PATH,
        _DISPLAY_INTERFACE,
        "ApplyMonitorsConfig",
        parameters,
        None,
        Gio.DBusCallFlags.NONE,
        10000,
        None,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0.0,
        help="Wait briefly for the graphical session before asking Mutter to modeset.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.wait_seconds > 0:
        time.sleep(args.wait_seconds)
    try:
        reapply_current_layout()
    except Exception as exc:
        print("[display-recover] skipped: {}".format(exc), file=sys.stderr, flush=True)
        return 1
    print("[display-recover] temporary modeset applied", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
