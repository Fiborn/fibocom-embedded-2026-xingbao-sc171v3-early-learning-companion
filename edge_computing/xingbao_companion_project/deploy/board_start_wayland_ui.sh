#!/usr/bin/env bash
# Native Wayland launcher for the Xingbao touch UI.  It is started by cron's
# unified launcher, not by a systemd project service.  If GDM recreates the
# Wayland session, Pygame exits and this small loop waits for the new socket
# before starting the UI again.
set -u

PROJECT=/home/fibo/xingbao_companion_project
PYTHON_BIN=/usr/bin/python3
PYGAME_SITE=/home/fibo/.local/lib/python3.8/site-packages
XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/5005}
WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
WAYLAND_SOCKET="$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"

export HOME=/home/fibo
export XDG_RUNTIME_DIR
export WAYLAND_DISPLAY
export SDL_AUDIODRIVER=dummy
export PATH=/usr/local/bin:/usr/bin:/bin

wayland_pygame_ready() {
    [ -S "$WAYLAND_SOCKET" ] || return 1
    env -u DISPLAY \
        XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
        WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
        SDL_VIDEODRIVER=wayland \
        PYTHONPATH="$PYGAME_SITE" \
        "$PYTHON_BIN" -c 'import pygame; pygame.display.init(); assert pygame.display.get_driver() == "wayland"; pygame.display.quit()' \
        >/dev/null 2>&1
}

wayland_socket_identity() {
    # GDM can recreate wayland-0 at the same path after a compositor restart.
    # The device/inode pair changes even though WAYLAND_DISPLAY does not.
    stat -Lc '%d:%i' "$WAYLAND_SOCKET" 2>/dev/null || true
}

while true; do
    until wayland_pygame_ready; do
        echo "$(date -Is) waiting for native Wayland UI session"
        sleep 2
    done

    session_identity="$(wayland_socket_identity)"
    if [ -z "$session_identity" ]; then
        echo "$(date -Is) Wayland socket identity unavailable; retrying"
        sleep 2
        continue
    fi

    echo "$(date -Is) starting Xingbao UI on Wayland"
    env -u DISPLAY \
        XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
        WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
        SDL_VIDEODRIVER=wayland \
        SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0 \
        SDL_AUDIODRIVER=dummy \
        PYTHONPATH="$PYGAME_SITE" \
        "$PYTHON_BIN" -u "$PROJECT/tools/board_phase1_ui.py" \
        --ui-dir "$PROJECT/components/touch_ui" &
    ui_pid=$!

    # A Wayland client may remain alive after GNOME replaces its compositor,
    # but its old socket can no longer present frames. Restart only the UI
    # child when the socket identity changes; the other Xingbao services stay
    # online and the outer loop reconnects to the new desktop session.
    while kill -0 "$ui_pid" 2>/dev/null; do
        sleep 1
        current_identity="$(wayland_socket_identity)"
        if [ -z "$current_identity" ] || [ "$current_identity" != "$session_identity" ]; then
            echo "$(date -Is) Wayland session changed; restarting Xingbao UI"
            kill -TERM "$ui_pid" 2>/dev/null || true
            break
        fi
    done

    wait "$ui_pid"
    status=$?
    echo "$(date -Is) Xingbao UI exited status=$status; waiting to recover"
    sleep 2
done
