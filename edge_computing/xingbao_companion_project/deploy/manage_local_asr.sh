#!/usr/bin/env bash
# Ensure the optional local Sherpa-ONNX streaming ASR matches runtime.env.
#
# XINGBAO_ASR_BACKEND=local starts (or reuses) the local service.
# XINGBAO_ASR_BACKEND=cloud leaves it stopped so the board does not reserve
# CPU and memory for a recognizer that the voice process will not use.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
ENV_FILE="${XINGBAO_ENV_FILE:-${HOME:-/home/fibo}/.config/xingbao/runtime.env}"
STATE_DIR="$PROJECT_DIR/work/runtime"
LOG_DIR="$PROJECT_DIR/logs"
ASR_PORT="${XINGBAO_LOCAL_ASR_PORT:-6006}"
ASR_BIN="$PROJECT_DIR/tools/runtime/sherpa-onnx-v1.13.4-linux-aarch64-shared-cpu/bin/sherpa-onnx-online-websocket-server"
ASR_LIB_DIR="$PROJECT_DIR/tools/runtime/sherpa-onnx-v1.13.4-linux-aarch64-shared-cpu/lib"
MODEL_DIR="$PROJECT_DIR/models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
PID_FILE="$STATE_DIR/sherpa-onnx.pid"
LOG_FILE="$LOG_DIR/sherpa-onnx-streaming.log"

if [ -r "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

XINGBAO_ASR_BACKEND="${XINGBAO_ASR_BACKEND:-cloud}"
case "$XINGBAO_ASR_BACKEND" in
    local|cloud) ;;
    *) echo "[asr] XINGBAO_ASR_BACKEND must be local or cloud" >&2; exit 2 ;;
esac

port_ready() {
    timeout 1 bash -c "</dev/tcp/127.0.0.1/$ASR_PORT" >/dev/null 2>&1
}

local_asr_pids() {
    local proc pid executable cwd
    for proc in /proc/[0-9]*; do
        pid=${proc##*/}
        [ "$pid" = "$$" ] && continue
        executable=$(readlink -f "$proc/exe" 2>/dev/null || true)
        case "$executable" in
            "$ASR_BIN"|*/sherpa-onnx-online-websocket-server) ;;
            *) continue ;;
        esac
        cwd=$(readlink -f "$proc/cwd" 2>/dev/null || true)
        [ "$cwd" = "$PROJECT_DIR" ] && printf '%s\n' "$pid"
    done
}

wait_for_port() {
    local attempt
    for attempt in $(seq 1 30); do
        if port_ready; then
            printf '[asr] local Sherpa-ONNX ready (port %s)\n' "$ASR_PORT"
            return 0
        fi
        sleep 1
    done
    printf '[asr] local Sherpa-ONNX did not open port %s\n' "$ASR_PORT" >&2
    return 1
}

stop_local_asr() {
    local pids pid
    pids="$(local_asr_pids || true)"
    [ -n "$pids" ] || return 0
    printf '[asr] cloud backend selected; stopping unused local ASR (pid(s): %s)\n' "${pids//$'\n'/ }"
    for pid in $pids; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    for _ in $(seq 1 10); do
        [ -z "$(local_asr_pids || true)" ] && break
        sleep 1
    done
    pids="$(local_asr_pids || true)"
    for pid in $pids; do
        kill -KILL "$pid" 2>/dev/null || true
    done
    rm -f "$PID_FILE"
}

start_local_asr() {
    if port_ready; then
        printf '[asr] local ASR already ready (port %s); reusing it\n' "$ASR_PORT"
        return 0
    fi
    if [ ! -x "$ASR_BIN" ] || [ ! -f "$MODEL_DIR/encoder.int8.onnx" ]; then
        printf '[asr] local ASR runtime or model is missing\n' >&2
        return 1
    fi
    mkdir -p "$STATE_DIR" "$LOG_DIR"
    printf '[asr] starting local Sherpa-ONNX; log: %s\n' "$LOG_FILE"
    setsid env LD_LIBRARY_PATH="$ASR_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$ASR_BIN" \
        --port="$ASR_PORT" --num-work-threads=2 --num-threads=2 --provider=cpu \
        --log-file="$LOG_FILE" \
        --tokens="$MODEL_DIR/tokens.txt" \
        --encoder="$MODEL_DIR/encoder.int8.onnx" \
        --decoder="$MODEL_DIR/decoder.onnx" \
        --joiner="$MODEL_DIR/joiner.int8.onnx" \
        </dev/null >>"$LOG_FILE" 2>&1 &
    printf '%s\n' "$!" >"$PID_FILE"
    wait_for_port
}

case "${1:-ensure}" in
    ensure)
        if [ "$XINGBAO_ASR_BACKEND" = local ]; then
            start_local_asr
        else
            stop_local_asr
            printf '[asr] cloud backend selected; local ASR is not started\n'
        fi
        ;;
    stop) stop_local_asr ;;
    *) printf 'Usage: %s [ensure|stop]\n' "$0" >&2; exit 2 ;;
esac
