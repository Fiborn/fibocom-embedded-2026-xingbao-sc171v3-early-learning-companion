#!/usr/bin/env sh
set -eu

MJPG_ROOT="${XINGBAO_MJPG_ROOT:-/home/fibo/mjpg-streamer/mjpg-streamer-experimental}"
MJPG_BIN="${XINGBAO_MJPG_BIN:-$MJPG_ROOT/mjpg_streamer}"
INPUT_PLUGIN="${XINGBAO_MJPG_INPUT_PLUGIN:-$MJPG_ROOT/input_uvc.so}"
OUTPUT_PLUGIN="${XINGBAO_MJPG_OUTPUT_PLUGIN:-$MJPG_ROOT/output_http.so}"
WWW_ROOT="${XINGBAO_MJPG_WWW_ROOT:-$MJPG_ROOT/www}"
HTTP_PORT="${XINGBAO_MJPG_PORT:-8080}"
RETRY_SECONDS="${XINGBAO_CAMERA_RETRY_SECONDS:-2}"
CAMERA_DEVICE="${XINGBAO_CAMERA_DEVICE:-auto}"

child_pid=""
waiting_announced=0

stop_child() {
    if [ -n "$child_pid" ] && kill -0 "$child_pid" 2>/dev/null; then
        kill "$child_pid" 2>/dev/null || true
        wait "$child_pid" 2>/dev/null || true
    fi
    child_pid=""
}

trap 'stop_child; exit 0' INT TERM EXIT

find_camera() {
    if [ "$CAMERA_DEVICE" != "auto" ]; then
        [ -c "$CAMERA_DEVICE" ] && printf '%s\n' "$CAMERA_DEVICE"
        return
    fi
    for sys_node in /sys/class/video4linux/video*; do
        [ -e "$sys_node" ] || continue
        resolved="$(readlink -f "$sys_node/device" 2>/dev/null || true)"
        case "$resolved" in
            *"/usb"*|*"/usb-"*) ;;
            *) continue ;;
        esac
        node="/dev/$(basename "$sys_node")"
        [ -c "$node" ] || continue
        if v4l2-ctl --device="$node" --all 2>/dev/null \
            | grep -q "Video Capture"; then
            printf '%s\n' "$node"
            return
        fi
    done
}

while :; do
    device="$(find_camera || true)"
    if [ -z "$device" ]; then
        if [ "$waiting_announced" -eq 0 ]; then
            echo "[camera] waiting for a USB video-capture device" >&2
            waiting_announced=1
        fi
        sleep "$RETRY_SECONDS"
        continue
    fi

    waiting_announced=0
    echo "[camera] starting MJPEG stream from $device on port $HTTP_PORT"
    "$MJPG_BIN" \
        -i "$INPUT_PLUGIN -d $device -r 640x480" \
        -o "$OUTPUT_PLUGIN -p $HTTP_PORT -w $WWW_ROOT" &
    child_pid=$!

    while kill -0 "$child_pid" 2>/dev/null && [ -c "$device" ]; do
        sleep "$RETRY_SECONDS"
    done
    stop_child
    echo "[camera] stream stopped; waiting for camera recovery" >&2
    sleep "$RETRY_SECONDS"
done
