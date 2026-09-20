#!/usr/bin/env bash
# Manage only the Xingbao voice process from this project.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
STATE_DIR="$PROJECT_DIR/work/runtime"
PID_FILE="$STATE_DIR/xingbao_voice_manager.pid"
LOG_FILE="$PROJECT_DIR/logs/xingbao-voice-realtime.log"

is_voice_pid() {
  local pid="$1" cwd cmdline
  [ -r "/proc/$pid/cmdline" ] || return 1
  cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
  [ "$cwd" = "$PROJECT_DIR" ] || return 1
  cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  [[ "$cmdline" == *"main.py"* && "$cmdline" == *"--wake-chat"* ]]
}

voice_pids() {
  local pid
  for pid in /proc/[0-9]*; do
    pid=${pid##*/}
    is_voice_pid "$pid" && printf '%s\n' "$pid"
  done
}

is_voice_launcher_pid() {
  local pid="$1" cmdline
  [ -r "/proc/$pid/cmdline" ] || return 1
  cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  [[ "$cmdline" == *"$SCRIPT_DIR/board_start_demo.sh"* ]]
}

voice_launcher_pids() {
  local pid
  for pid in /proc/[0-9]*; do
    pid=${pid##*/}
    is_voice_launcher_pid "$pid" && printf '%s\n' "$pid"
  done
}

stop_pid() {
  local pid="$1" attempt
  kill -TERM "$pid" 2>/dev/null || return 0
  for attempt in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.25
  done
  printf '[voice] force-stopping pid=%s\n' "$pid" >&2
  kill -KILL "$pid" 2>/dev/null || true
}

start_voice() {
  local pids pid attempt
  pids="$(voice_pids || true)"
  if [ -n "$pids" ]; then
    printf '[voice] already running (pid(s): %s)\n' "${pids//$'\n'/ }"
    return 0
  fi

  mkdir -p "$STATE_DIR" "$(dirname -- "$LOG_FILE")"
  # Keep the ASR process in lockstep with XINGBAO_ASR_BACKEND before starting
  # voice: local starts/reuses Sherpa, cloud does not consume its resources.
  "$SCRIPT_DIR/manage_local_asr.sh" ensure
  printf '[voice] starting; log: %s\n' "$LOG_FILE"
  # Reuse the reviewed board launcher so a manual voice start has the same
  # ALSA, wake-word, streaming-ASR, TTS, VAD, and barge-in-disable settings
  # as the normal central service.
  setsid /bin/sh "$SCRIPT_DIR/board_start_demo.sh" \
    </dev/null >>"$LOG_FILE" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" >"$PID_FILE"
  for attempt in $(seq 1 30); do
    pids="$(voice_pids || true)"
    if [ -n "$pids" ]; then
      printf '[voice] started (pid(s): %s)\n' "${pids//$'\n'/ }"
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  printf '[voice] failed to remain running; see %s\n' "$LOG_FILE" >&2
  return 1
}

stop_voice() {
  local pids launchers pid
  pids="$(voice_pids || true)"
  if [ -z "$pids" ]; then
    printf '[voice] not running\n'
  else
    for pid in $pids; do
      printf '[voice] stopping pid=%s\n' "$pid"
      stop_pid "$pid"
    done
  fi
  # board_start_demo.sh remains as the parent while main.py is running.
  # Stop it too, otherwise it could retain an orphaned launch session.
  launchers="$(voice_launcher_pids || true)"
  for pid in $launchers; do
    printf '[voice] stopping launcher pid=%s\n' "$pid"
    stop_pid "$pid"
  done
  rm -f "$PID_FILE"
}

restart_voice() {
  stop_voice
  start_voice
}

choose_action() {
  printf '\n星宝语音服务\n1) 启动\n2) 停止\n3) 重启\n0) 退出\n请选择 [0-3]: '
  read -r action || exit 0
  case "$action" in
    1) start_voice ;;
    2) stop_voice ;;
    3) restart_voice ;;
    0) exit 0 ;;
    *) printf '[voice] 无效选项\n' >&2; return 2 ;;
  esac
}

case "${1:-menu}" in
  menu) choose_action ;;
  start) start_voice ;;
  stop) stop_voice ;;
  restart) restart_voice ;;
  *) printf 'Usage: %s [menu|start|stop|restart]\n' "$0" >&2; exit 2 ;;
esac
