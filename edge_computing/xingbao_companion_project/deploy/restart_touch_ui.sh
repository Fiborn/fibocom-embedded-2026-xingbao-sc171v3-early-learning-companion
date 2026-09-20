#!/usr/bin/env sh
# Restart only the touch UI and its local 8765 bridge.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
UI_DIR="$PROJECT_DIR/components/touch_ui"
PID_FILE="$PROJECT_DIR/work/runtime/touch_ui.pid"
LOG_FILE="$UI_DIR/logs/desktop-ui.log"

mkdir -p "$(dirname -- "$PID_FILE")" "$(dirname -- "$LOG_FILE")"

old_pid=""
if [ -r "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
fi
if [ -z "$old_pid" ] || ! kill -0 "$old_pid" 2>/dev/null; then
  old_pid="$(pgrep -f "$PROJECT_DIR/tools/board_phase1_ui.py --ui-dir $UI_DIR" || true)"
fi

if [ -n "$old_pid" ]; then
  kill -TERM "$old_pid" 2>/dev/null || true
  for _ in $(seq 1 40); do
    kill -0 "$old_pid" 2>/dev/null || break
    sleep 0.25
  done
  # The UI process owns the local bridge port.  Do not launch a second UI
  # against that port if it ignored or delayed TERM during shutdown.
  if kill -0 "$old_pid" 2>/dev/null; then
    kill -KILL "$old_pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$old_pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
fi

setsid -f sh "$UI_DIR/board_start.sh" >>"$LOG_FILE" 2>&1
sleep 2
new_pid="$(pgrep -f "$PROJECT_DIR/tools/board_phase1_ui.py --ui-dir $UI_DIR" | tail -n 1)"
printf '%s\n' "$new_pid" >"$PID_FILE"
printf 'Xingbao touch UI started (pid=%s).\n' "$new_pid"
