#!/usr/bin/env sh
set -eu

UI_DIR="/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge"
COMPANION_DIR="/home/fibo/xingbao_releases/current"
UI_PYTHON="/usr/bin/python3"
UI_WRAPPER="$COMPANION_DIR/tools/board_phase1_ui.py"
FIBO_UID="$(id -u fibo)"
FIBO_RUNTIME="/run/user/$FIBO_UID"
WESTON_RUNTIME="/run/user/root"
ENV_FILE="${XINGBAO_ENV_FILE:-/home/fibo/.config/xingbao/runtime.env}"

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script after: adb root" >&2
    exit 2
fi

if [ ! -S "$WESTON_RUNTIME/wayland-0" ]; then
    echo "[display] Weston physical display is not ready." >&2
    exit 3
fi

pkill -f '[m]ain.py.*--wake-chat' 2>/dev/null || true
pkill -f '[d]esktop.py' 2>/dev/null || true
pkill -f '[b]oard_phase1_ui.py' 2>/dev/null || true
pkill -f '[v]ision_system.app' 2>/dev/null || true
pkill -f '[k]win_x11' 2>/dev/null || true
pkill -f '[X]wayland :0' 2>/dev/null || true
fuser -k 8765/tcp 2>/dev/null || true
fuser -k 8766/tcp 2>/dev/null || true
rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock
rm -f /tmp/xwayland-xingbao.log /tmp/kwin-xingbao.log
rm -f /tmp/xingbao_ui_start.log /tmp/xingbao_central_start.log /tmp/xingbao_arm_action_server.log

setsid -f sh -c "exec env XDG_RUNTIME_DIR=$WESTON_RUNTIME WAYLAND_DISPLAY=wayland-0 Xwayland :0 -ac -noreset >/tmp/xwayland-xingbao.log 2>&1 </dev/null"

count=0
while [ ! -S /tmp/.X11-unix/X0 ]; do
    count=$((count + 1))
    if [ "$count" -ge 20 ]; then
        echo "[display] XWayland did not become ready." >&2
        cat /tmp/xwayland-xingbao.log >&2 || true
        exit 4
    fi
    sleep 1
done

runuser -u fibo -- sh -c "setsid -f env DISPLAY=:0 XDG_RUNTIME_DIR=$FIBO_RUNTIME kwin_x11 --replace >/tmp/kwin-xingbao.log 2>&1 </dev/null"
sleep 2

if [ ! -f "$UI_WRAPPER" ]; then
    echo "[ui] Missing restored UI wrapper: $UI_WRAPPER" >&2
    exit 5
fi

runuser -u fibo -- sh -c "cd '$COMPANION_DIR' && setsid -f env DISPLAY=:0 SDL_VIDEODRIVER=x11 '$UI_PYTHON' '$UI_WRAPPER' --ui-dir '$UI_DIR' >/tmp/xingbao_ui_start.log 2>&1 </dev/null"

count=0
while ! /usr/bin/python3 - <<'PY' >/dev/null 2>&1
import json
import socket

message = {
    "version": "1.0",
    "request_id": "board-start-ready-check",
    "type": "assistant_output",
    "source": "board_start",
    "target": "desktop_ui",
    "payload": {
        "screen_expression": {"name": "neutral", "duration_ms": 500},
    },
}
with socket.create_connection(("127.0.0.1", 8765), timeout=2.0) as sock:
    sock.settimeout(2.0)
    sock.sendall((json.dumps(message) + "\n").encode("utf-8"))
    response = json.loads(sock.makefile("r", encoding="utf-8").readline())
    if not response.get("ok"):
        raise SystemExit(1)
PY
do
    count=$((count + 1))
    if [ "$count" -ge 90 ]; then
        echo "[ui] Desktop did not enter its frame loop." >&2
        tail -n 80 /tmp/xingbao_ui_start.log >&2 || true
        exit 5
    fi
    sleep 2
done

runuser -u fibo -- sh -c "cd '$COMPANION_DIR' && HOME=/home/fibo sh deploy/start_arm_action_service.sh"

runuser -u fibo -- sh -c "cd '$COMPANION_DIR' && HOME=/home/fibo setsid -f sh -c 'exec sh deploy/board_start_demo.sh >/tmp/xingbao_central_start.log 2>&1 </dev/null'"

count=0
while ! ss -ltn 2>/dev/null | grep -q ':8766 '; do
    count=$((count + 1))
    if [ "$count" -ge 60 ]; then
        echo "[voice] Central service did not become ready." >&2
        tail -n 100 /tmp/xingbao_central_start.log >&2 || true
        exit 6
    fi
    sleep 1
done

echo "[ready] display=:0 ui=127.0.0.1:8765 voice=127.0.0.1:8766 arm=127.0.0.1:8764 vision=central-managed"
echo "[logs] /tmp/xingbao_ui_start.log /tmp/xingbao_central_start.log /tmp/xingbao_arm_action_server.log"
