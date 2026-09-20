#!/usr/bin/env sh
# Restart the board voice service with realtime WebSocket TTS enabled.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/work/runtime/xingbao_voice.pid"
LOG_FILE="$PROJECT_DIR/logs/xingbao-voice-realtime.log"
ENV_FILE="${XINGBAO_ENV_FILE:-$HOME/.config/xingbao/runtime.env}"

mkdir -p "$(dirname -- "$PID_FILE")" "$(dirname -- "$LOG_FILE")"
cd "$PROJECT_DIR"

old_pid=""
if [ -r "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
fi
if [ -z "$old_pid" ] || ! kill -0 "$old_pid" 2>/dev/null; then
  old_pid="$(pgrep -f '^/usr/bin/python3(\\.8)? -u main.py --wake-chat' || true)"
fi

if [ -n "$old_pid" ]; then
  kill -TERM "$old_pid" 2>/dev/null || true
  for _ in $(seq 1 40); do
    kill -0 "$old_pid" 2>/dev/null || break
    sleep 0.25
  done
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi
export XINGBAO_ALSA_INPUT_DEVICE="${XINGBAO_ALSA_INPUT_DEVICE:-plughw:CARD=Device,DEV=0}"
export XINGBAO_ALSA_INPUT_GAIN="${XINGBAO_ALSA_INPUT_GAIN:-4.0}"

printf '\n[%s] restarting realtime voice service\n' "$(date -Iseconds)" >>"$LOG_FILE"
setsid -f /usr/bin/python3 -u main.py \
  --wake-chat \
  --board-audio-output \
  --realtime-tts \
  --streaming-asr \
  --board-ui \
  --board-ui-host 127.0.0.1 \
  --board-ui-port 8765 \
  --game-speech \
  --game-speech-host 127.0.0.1 \
  --game-speech-port 8766 \
  --input-device "${XINGBAO_INPUT_DEVICE:-1}" \
  --listen-timeout 10 \
  </dev/null >>"$LOG_FILE" 2>&1

sleep 1
new_pid="$(pgrep -f '^/usr/bin/python3(\\.8)? -u main.py --wake-chat' | tail -n 1)"
printf '%s\n' "$new_pid" >"$PID_FILE"
printf 'Xingbao realtime voice service started (pid=%s).\n' "$new_pid"
