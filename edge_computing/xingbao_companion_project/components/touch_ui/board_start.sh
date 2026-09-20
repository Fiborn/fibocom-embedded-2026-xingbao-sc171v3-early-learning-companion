#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
cd "$SCRIPT_DIR"
mkdir -p saves/artworks saves/memory_shots logs

# The voice companion and touch desktop can share the privacy-safe memory files.
# Override this variable when the companion is installed elsewhere.
if [ -z "${XINGBAO_COMPANION_DATA_DIR:-}" ]; then
    sibling_data="../xingbao_companion/data"
    if [ -d "$sibling_data" ]; then
        export XINGBAO_COMPANION_DATA_DIR="$(CDPATH= cd -- "$sibling_data" && pwd)"
    fi
fi

# Never allow test-only SDL drivers in the board display process.
case "${SDL_VIDEODRIVER:-}" in
    dummy|offscreen) unset SDL_VIDEODRIVER ;;
esac

if [ "${XINGBAO_STOP_OLD_UI:-1}" != "0" ] && command -v pgrep >/dev/null 2>&1; then
    old_pids="$(pgrep -f 'desktop.py .*--fullscreen' 2>/dev/null || true)"
    for pid in $old_pids; do
        if [ "$pid" != "$$" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    [ -z "$old_pids" ] || sleep 0.3
fi

# SSH sessions do not inherit the physical desktop session environment.
# Prefer X11 on this board because pygame/SDL can report Wayland even when it is unavailable.
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ -d "$runtime_dir" ]; then
    for socket in /tmp/.X11-unix/X*; do
        if [ -S "$socket" ]; then
            export DISPLAY=":${socket##*X}"
            break
        fi
    done
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ -d "$runtime_dir" ]; then
    for socket in "$runtime_dir"/wayland-*; do
        if [ -S "$socket" ]; then
            export XDG_RUNTIME_DIR="$runtime_dir"
            export WAYLAND_DISPLAY="${socket##*/}"
            break
        fi
    done
fi

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    export XDG_RUNTIME_DIR="$runtime_dir"
    export SDL_VIDEODRIVER="wayland"
else
    if [ -z "${DISPLAY:-}" ]; then
        for socket in /tmp/.X11-unix/X*; do
            if [ -S "$socket" ]; then
                export DISPLAY=":${socket##*X}"
                break
            fi
        done
    fi
    if [ -n "${DISPLAY:-}" ]; then
        if [ -z "${XAUTHORITY:-}" ]; then
            for auth in "$runtime_dir"/xauth_* "$runtime_dir"/.mutter-Xwaylandauth.* "$HOME/.Xauthority"; do
                if [ -r "$auth" ]; then
                    export XAUTHORITY="$auth"
                    break
                fi
            done
        fi
        export SDL_VIDEODRIVER="x11"
    else
        echo "[display] No X11 or Wayland session found; refusing offscreen startup." >&2
        echo "[display] Start the board desktop session first, then run this script again." >&2
        exit 2
    fi
fi

PYTHON_BIN="/usr/bin/python3"
echo "[display] DISPLAY=${DISPLAY:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-} XAUTHORITY=${XAUTHORITY:-}"
echo "[ui] unified phase-one wrapper"
exec "$PYTHON_BIN" "$PROJECT_DIR/tools/board_phase1_ui.py" \
    --ui-dir "$SCRIPT_DIR" "$@"
