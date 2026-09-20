#!/usr/bin/env bash
# Manage only the Xingbao touch UI from this project.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
UI_DIR="$PROJECT_DIR/components/touch_ui"
UI_LAUNCHER="$SCRIPT_DIR/board_start_wayland_ui.sh"
STATE_DIR="$PROJECT_DIR/work/runtime"
PID_FILE="$STATE_DIR/touch_ui.pid"
LOG_FILE="$PROJECT_DIR/logs/xingbao-touch-ui.log"

is_ui_pid() {
  local pid="$1" cmdline
  [ -r "/proc/$pid/cmdline" ] || return 1
  cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  [[ "$cmdline" == *"$PROJECT_DIR/tools/board_phase1_ui.py"* && "$cmdline" == *"--ui-dir $UI_DIR"* ]]
}

ui_pids() {
  local pid
  for pid in /proc/[0-9]*; do
    pid=${pid##*/}
    is_ui_pid "$pid" && printf '%s\n' "$pid"
  done
}

is_ui_launcher_pid() {
  local pid="$1" cmdline
  [ -r "/proc/$pid/cmdline" ] || return 1
  cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  [[ "$cmdline" == *"$SCRIPT_DIR/board_start_wayland_ui.sh"* ]]
}

ui_launcher_pids() {
  local pid
  for pid in /proc/[0-9]*; do
    pid=${pid##*/}
    is_ui_launcher_pid "$pid" && printf '%s\n' "$pid"
  done
}

stop_pid() {
  local pid="$1" attempt
  kill -TERM "$pid" 2>/dev/null || return 0
  for attempt in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.25
  done
  printf '[ui] force-stopping pid=%s\n' "$pid" >&2
  kill -KILL "$pid" 2>/dev/null || true
}

start_ui() {
  local pids launchers pid attempt
  pids="$(ui_pids || true)"
  if [ -n "$pids" ]; then
    printf '[ui] already running (pid(s): %s)\n' "${pids//$'\n'/ }"
    return 0
  fi
  launchers="$(ui_launcher_pids || true)"
  if [ -n "$launchers" ]; then
    printf '[ui] Wayland launcher is already running (pid(s): %s)\n' "${launchers//$'\n'/ }"
    return 0
  fi

  mkdir -p "$STATE_DIR" "$(dirname -- "$LOG_FILE")"
  printf '[ui] starting; log: %s\n' "$LOG_FILE"
  # Keep this path identical to cron startup.  The compatibility launcher in
  # components/touch_ui can fall back to X11 and is not suitable for the
  # board's native Wayland session.
  setsid /bin/bash "$UI_LAUNCHER" </dev/null >>"$LOG_FILE" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" >"$PID_FILE"
  for attempt in $(seq 1 30); do
    pids="$(ui_pids || true)"
    if [ -n "$pids" ]; then
      printf '[ui] started (pid(s): %s)\n' "${pids//$'\n'/ }"
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  rm -f "$PID_FILE"
  printf '[ui] failed to reach the native Wayland UI; see %s\n' "$LOG_FILE" >&2
  return 1
}

stop_ui() {
  local pids launchers pid
  # Stop the persistent Wayland launcher first, otherwise it will respawn its
  # UI child immediately after this script terminates that child.
  launchers="$(ui_launcher_pids || true)"
  for pid in $launchers; do
    printf '[ui] stopping Wayland launcher pid=%s\n' "$pid"
    stop_pid "$pid"
  done
  pids="$(ui_pids || true)"
  if [ -z "$pids" ]; then
    printf '[ui] not running\n'
  else
    for pid in $pids; do
      printf '[ui] stopping pid=%s\n' "$pid"
      stop_pid "$pid"
    done
  fi
  rm -f "$PID_FILE"
}

restart_ui() {
  stop_ui
  start_ui
}

choose_action() {
  printf '\n星宝触控 UI\n1) 启动\n2) 停止\n3) 重启\n0) 退出\n请选择 [0-3]: '
  read -r action || exit 0
  case "$action" in
    1) start_ui ;;
    2) stop_ui ;;
    3) restart_ui ;;
    0) exit 0 ;;
    *) printf '[ui] 无效选项\n' >&2; return 2 ;;
  esac
}

case "${1:-menu}" in
  menu) choose_action ;;
  start) start_ui ;;
  stop) stop_ui ;;
  restart) restart_ui ;;
  *) printf 'Usage: %s [menu|start|stop|restart]\n' "$0" >&2; exit 2 ;;
esac
