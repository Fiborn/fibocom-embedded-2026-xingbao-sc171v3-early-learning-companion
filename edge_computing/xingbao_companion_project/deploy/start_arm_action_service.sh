#!/usr/bin/env sh
set -eu

ARM_HOST="${XINGBAO_ARM_ACTION_HOST:-127.0.0.1}"
ARM_PORT="${XINGBAO_ARM_ACTION_PORT:-8764}"
ARM_SERVICE_DIR="${XINGBAO_ARM_SERVICE_DIR:-/home/fibo/xingbao_companion_unified/components/arm_soarm101}"
ARM_SERVICE_SCRIPT="${XINGBAO_ARM_SERVICE_SCRIPT:-arm_action_server_soft_nod.py}"
ARM_SERVICE_PYTHON="/usr/bin/python3"
ARM_SERVICE_LOG="${XINGBAO_ARM_SERVICE_LOG:-/tmp/xingbao_arm_action_server.log}"
ARM_SERVICE_WAIT_SECONDS="${XINGBAO_ARM_SERVICE_WAIT_SECONDS:-20}"

is_listening() {
  ss -ltn 2>/dev/null | grep -q ":${ARM_PORT} "
}

if is_listening; then
  echo "[arm] High-level action service already listening at ${ARM_HOST}:${ARM_PORT}"
  exit 0
fi

if [ ! -f "${ARM_SERVICE_DIR}/${ARM_SERVICE_SCRIPT}" ]; then
  echo "[arm] Service script not found: ${ARM_SERVICE_DIR}/${ARM_SERVICE_SCRIPT}" >&2
  exit 7
fi

if [ ! -x "$ARM_SERVICE_PYTHON" ]; then
  ARM_SERVICE_PYTHON="${PYTHON_BIN:-/usr/bin/python3}"
fi

rm -f "$ARM_SERVICE_LOG"
cd "$ARM_SERVICE_DIR"
setsid -f "$ARM_SERVICE_PYTHON" "$ARM_SERVICE_SCRIPT" >"$ARM_SERVICE_LOG" 2>&1 </dev/null

count=0
while ! is_listening; do
  count=$((count + 1))
  if [ "$count" -ge "$ARM_SERVICE_WAIT_SECONDS" ]; then
    echo "[arm] Service did not open ${ARM_HOST}:${ARM_PORT}." >&2
    echo "[arm] Log: $ARM_SERVICE_LOG" >&2
    tail -n 80 "$ARM_SERVICE_LOG" >&2 || true
    exit 8
  fi
  sleep 1
done

echo "[arm] High-level action service ready at ${ARM_HOST}:${ARM_PORT}"
echo "[arm] Log: $ARM_SERVICE_LOG"
