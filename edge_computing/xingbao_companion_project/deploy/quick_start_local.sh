#!/usr/bin/env bash
# Start the local Xingbao stack from this project directory.
#
# This deliberately does not start xingbao-central.service: that unit belongs
# to the older xingbao_companion_unified runtime.  The voice process below is
# the current project, using the local Sherpa-ONNX streaming ASR server.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
STATE_DIR="$PROJECT_DIR/.runtime"
ENV_FILE="${XINGBAO_ENV_FILE:-$HOME/.config/xingbao/runtime.env}"
PYTHON_BIN="/usr/bin/python3"

ASR_PORT=6006
ASR_BIN="$PROJECT_DIR/tools/runtime/sherpa-onnx-v1.13.4-linux-aarch64-shared-cpu/bin/sherpa-onnx-online-websocket-server"
ASR_LIB_DIR="$PROJECT_DIR/tools/runtime/sherpa-onnx-v1.13.4-linux-aarch64-shared-cpu/lib"
MODEL_DIR="$PROJECT_DIR/models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"

mkdir -p "$LOG_DIR" "$STATE_DIR"
cd "$PROJECT_DIR"

if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

port_ready() {
  timeout 1 bash -c "</dev/tcp/127.0.0.1/$1" >/dev/null 2>&1
}

wait_for_port() {
  local port="$1" label="$2" attempt
  for attempt in $(seq 1 30); do
    if port_ready "$port"; then
      printf '[ready] %s (port %s)\n' "$label" "$port"
      return 0
    fi
    sleep 1
  done
  printf '[error] %s did not open port %s\n' "$label" "$port" >&2
  return 1
}

start_managed_services() {
  local unit
  systemctl --user daemon-reload
  # Camera, game, and arm integrations are optional on a voice/UI-only
  # workstation.  Do not prevent the local voice and ASR stack from starting
  # when an optional unit is not installed.
  for unit in xingbao-camera.service touch-game.service xingbao-arm.service; do
    if [ "$(systemctl --user show "$unit" --property=LoadState --value 2>/dev/null || true)" = "loaded" ]; then
      if ! systemctl --user reset-failed "$unit" || ! systemctl --user start "$unit"; then
        printf '[skip] optional user service could not be started: %s\n' "$unit" >&2
      fi
    else
      printf '[skip] optional user service is not installed: %s\n' "$unit"
    fi
  done
}

start_local_asr() {
  if port_ready "$ASR_PORT"; then
    printf '[ready] local Sherpa-ONNX ASR (port %s)\n' "$ASR_PORT"
    return
  fi
  if [ ! -x "$ASR_BIN" ] || [ ! -f "$MODEL_DIR/encoder.int8.onnx" ]; then
    printf '[error] local ASR runtime or model is missing\n' >&2
    return 1
  fi

  printf '[start] local Sherpa-ONNX ASR; log: %s\n' "$LOG_DIR/sherpa-onnx-streaming.log"
  setsid env LD_LIBRARY_PATH="$ASR_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$ASR_BIN" \
      --port="$ASR_PORT" --num-work-threads=2 --num-threads=2 --provider=cpu \
      --log-file="$LOG_DIR/sherpa-onnx-streaming.log" \
      --tokens="$MODEL_DIR/tokens.txt" \
      --encoder="$MODEL_DIR/encoder.int8.onnx" \
      --decoder="$MODEL_DIR/decoder.onnx" \
      --joiner="$MODEL_DIR/joiner.int8.onnx" \
      </dev/null >>"$LOG_DIR/sherpa-onnx-streaming.log" 2>&1 &
  echo $! >"$STATE_DIR/sherpa-onnx.pid"
  wait_for_port "$ASR_PORT" 'local Sherpa-ONNX ASR'
}

voice_process_running() {
  local proc pid cwd exe cmdline
  for proc in /proc/[0-9]*; do
    pid=${proc##*/}
    [ -r "$proc/cmdline" ] || continue
    cwd=$(readlink -f "$proc/cwd" 2>/dev/null || true)
    [ "$cwd" = "$PROJECT_DIR" ] || continue
    exe=$(basename "$(readlink -f "$proc/exe" 2>/dev/null || true)")
    [[ "$exe" == python* ]] || continue
    cmdline=$(tr '\0' ' ' <"$proc/cmdline")
    [[ "$cmdline" == *"main.py"* && "$cmdline" == *"--wake-chat"* ]] && return 0
  done
  return 1
}

start_local_voice() {
  if voice_process_running; then
    printf '[ready] local voice process\n'
    return
  fi

  printf '[start] local voice; log: %s\n' "$LOG_DIR/xingbao-voice-local.log"
  setsid env \
    XINGBAO_ALSA_INPUT_DEVICE="${XINGBAO_ALSA_INPUT_DEVICE:-plughw:0,0}" \
    XINGBAO_ALSA_INPUT_GAIN="${XINGBAO_ALSA_INPUT_GAIN:-1}" \
    PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" -u main.py --wake-chat --board-audio-output --streaming-asr --board-ui \
      --board-ui-host "${XINGBAO_BOARD_UI_HOST:-127.0.0.1}" \
      --board-ui-port "${XINGBAO_BOARD_UI_PORT:-8765}" \
      --game-speech --game-speech-host "${XINGBAO_GAME_EVENT_HOST:-127.0.0.1}" \
      --game-speech-port "${XINGBAO_GAME_EVENT_PORT:-8766}" \
      --input-device "${XINGBAO_INPUT_DEVICE:-0}" \
      --listen-timeout "${XINGBAO_LISTEN_TIMEOUT:-10}" \
    </dev/null >>"$LOG_DIR/xingbao-voice-local.log" 2>&1 &
  echo $! >"$STATE_DIR/xingbao-voice.pid"
  sleep 2
  voice_process_running
}

printf '[start] Xingbao local stack in %s\n' "$PROJECT_DIR"
start_managed_services
start_local_asr
start_local_voice

printf '\n[status] managed services\n'
systemctl --user --no-pager --full --plain is-active \
  xingbao-camera.service touch-game.service xingbao-arm.service
printf '[status] listening ports\n'
ss -ltn '( sport = :4445 or sport = :6006 or sport = :8765 )' || true
printf '[logs] tail -f %s %s\n' \
  "$LOG_DIR/xingbao-voice-local.log" "$LOG_DIR/sherpa-onnx-streaming.log"
