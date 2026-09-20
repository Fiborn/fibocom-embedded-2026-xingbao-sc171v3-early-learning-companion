#!/usr/bin/env bash
# Stop only the local Xingbao stack started from this project directory.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
STATE_DIR="$PROJECT_DIR/.runtime"

pid_is_project_process() {
  local pid="$1" kind="$2" cwd cmdline
  [ -r "/proc/$pid/cmdline" ] || return 1
  cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
  [ "$cwd" = "$PROJECT_DIR" ] || return 1
  cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  case "$kind" in
    voice) [[ "$cmdline" == *"main.py"* && "$cmdline" == *"--wake-chat"* ]] ;;
    asr) [[ "$cmdline" == *"sherpa-onnx-online-websocket-server"* ]] ;;
    *) return 1 ;;
  esac
}

stop_pid() {
  local pid="$1" label="$2" attempt
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  printf '[stop] %s (pid %s)\n' "$label" "$pid"
  kill -TERM "$pid" 2>/dev/null || true
  for attempt in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  printf '[stop] %s did not exit after 10 seconds; sending KILL\n' "$label" >&2
  kill -KILL "$pid" 2>/dev/null || true
}

stop_kind() {
  # Assign separately: with `set -u`, expanding `$kind` in the same `local`
  # declaration happens before `kind` has been assigned in Bash.
  local kind label pid_file pid
  kind="$1"
  label="$2"
  pid_file="$STATE_DIR/$kind.pid"
  if [ -r "$pid_file" ]; then
    pid=$(tr -dc '0-9' <"$pid_file")
    if [ -n "$pid" ] && pid_is_project_process "$pid" "$kind"; then
      stop_pid "$pid" "$label"
    fi
    rm -f "$pid_file"
  fi

  # A process started manually before this helper has no pid file.  Limit the
  # fallback to processes whose working directory is exactly this project.
  for pid in /proc/[0-9]*; do
    pid=${pid##*/}
    if pid_is_project_process "$pid" "$kind"; then
      stop_pid "$pid" "$label"
    fi
  done
}

printf '[stop] Xingbao local stack in %s\n' "$PROJECT_DIR"
stop_kind voice 'local voice'
stop_kind asr 'local Sherpa-ONNX ASR'

systemctl --user stop xingbao-arm.service touch-game.service xingbao-camera.service

printf '\n[status] managed services\n'
systemctl --user --no-pager --full --plain is-active \
  xingbao-camera.service touch-game.service xingbao-arm.service || true
printf '[status] local listening ports\n'
ss -ltn '( sport = :4445 or sport = :6006 or sport = :8765 )' || true
