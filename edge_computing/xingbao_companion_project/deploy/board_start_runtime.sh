#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
COMPANION_DIR="${XINGBAO_COMPANION_DIR:-$(dirname -- "$SCRIPT_DIR")}"

cd "$COMPANION_DIR"

PYTHON_BIN="/usr/bin/python3"
ENV_FILE="${XINGBAO_ENV_FILE:-$HOME/.config/xingbao/runtime.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

INPUT_DEVICE="${XINGBAO_INPUT_DEVICE:-0}"

"$PYTHON_BIN" tools/board_health_check.py

PREWARM_ARG=""
if [ "${XINGBAO_PREPARE_GAME_TTS_CACHE:-1}" != "0" ]; then
  PREWARM_ARG="--prewarm-game-tts-cache"
fi

"$PYTHON_BIN" -u main.py \
  --wake-chat \
  --board-audio-output \
  --streaming-asr \
  --board-ui \
  --game-speech \
  $PREWARM_ARG \
  --input-device "$INPUT_DEVICE" \
  "$@"
