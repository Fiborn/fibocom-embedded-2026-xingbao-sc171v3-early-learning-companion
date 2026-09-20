#!/usr/bin/env bash
# One-terminal manager for the Xingbao services in this project.
# Startup follows the same dependency order and readiness checks as the
# cron @reboot launcher; it intentionally does not restart GDM or add a boot
# delay during a manual operation.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
LAUNCHER="$SCRIPT_DIR/xingbao-unified-autostart.sh"
LOG_DIR="$PROJECT_DIR/logs"
ARM_PYTHON="/home/fibo/miniforge3/bin/python3"

if [ ! -x "$LAUNCHER" ]; then
  printf 'Missing or non-executable cron launcher: %s\n' "$LAUNCHER" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

is_xingbao_process() {
  local cmdline="$1" cwd="$2"
  # The center-owned vision child has no --wake-chat marker.  Restrict this
  # rule to this exact checkout so a different project's vision experiment is
  # never touched by the total-service manager.
  if [ "$cwd" = "$PROJECT_DIR" ] && [[ "$cmdline" == *'multimodal.vision_system.app'* ]]; then
    return 0
  fi
  case "$cmdline" in
    *'main.py'*'--wake-chat'*|*'deploy/start_camera_stream.sh'*|\
    *'arm_action_server_soft_nod.py'*|*'arm_command_server_10000.py'*|\
    *'board_start_wayland_ui.sh'*|*'tools/board_phase1_ui.py'*|\
    *'multimodal.high_five_vision_runtime'*|\
    *'/home/fibo/xingbao_web/auth_service.py'*) return 0 ;;
  esac

  # mjpg_streamer is shared system software, so limit it to Xingbao project
  # trees before treating it as a managed process.
  case "$cmdline:$cwd" in
    *'mjpg_streamer:'"$PROJECT_DIR"*|*'mjpg_streamer:/home/fibo/xingbao_companion_unified'*|\
    *'mjpg_streamer:/home/fibo/xingbao_releases/'*) return 0 ;;
  esac
  return 1
}

managed_pids() {
  local proc pid cmdline cwd
  for proc in /proc/[0-9]*; do
    pid=${proc##*/}
    [ "$pid" = "$$" ] && continue
    [ -r "$proc/cmdline" ] || continue
    cmdline=$(tr '\0' ' ' <"$proc/cmdline")
    cwd=$(readlink -f "$proc/cwd" 2>/dev/null || true)
    is_xingbao_process "$cmdline" "$cwd" && printf '%s\n' "$pid"
  done
}

stop_xingbao() {
  local -a pids=()
  local pid remaining

  mapfile -t pids < <(managed_pids)
  if [ "${#pids[@]}" -eq 0 ]; then
    printf '[stop] No Xingbao processes are running.\n'
    return 0
  fi

  printf '[stop] Stopping Xingbao PIDs: %s\n' "${pids[*]}"
  kill -TERM "${pids[@]}" 2>/dev/null || true
  for _ in $(seq 1 10); do
    remaining=0
    for pid in "${pids[@]}"; do
      kill -0 "$pid" 2>/dev/null && remaining=1
    done
    [ "$remaining" -eq 0 ] && break
    sleep 1
  done

  mapfile -t pids < <(managed_pids)
  if [ "${#pids[@]}" -gt 0 ]; then
    printf '[stop] Force-stopping remaining Xingbao PIDs: %s\n' "${pids[*]}"
    kill -KILL "${pids[@]}" 2>/dev/null || true
  fi
  printf '[stop] Xingbao services stopped.\n'
}

start_xingbao() {
  printf '[start] Starting Xingbao services from %s\n' "$PROJECT_DIR"
  # The arm driver is installed in Miniforge's Python 3.13 environment;
  # system Python 3.8 cannot import this version of LeRobot.  Check this
  # before launching so manual start reports a direct, actionable failure.
  if [ ! -x "$ARM_PYTHON" ] || ! "$ARM_PYTHON" -c 'from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig' >/dev/null 2>&1; then
    printf '[error] Mechanical-arm runtime is unavailable: %s cannot import lerobot.\n' "$ARM_PYTHON" >&2
    return 1
  fi
  # The cron launcher owns the ordered startup checks.  These variables make
  # a manual start immediate while ensuring a legacy runtime cannot retain a
  # port or device.  It is the same launcher used by cron, so its exact
  # passwordless GDM command is shared rather than duplicated here.
  env XINGBAO_SKIP_BOOT_UI_PREP=1 XINGBAO_REPLACE_LEGACY_RUNTIME=1 \
    "$LAUNCHER"
  printf '[start] Xingbao startup sequence completed.\n'
}

restart_xingbao() {
  stop_xingbao
  start_xingbao
}

show_menu() {
  printf '\n========== 星宝服务管理 ==========\n'
  printf '1. 快速运行（启动全部星宝服务）\n'
  printf '2. 快速结束（结束全部星宝服务）\n'
  printf '3. 快速重启（结束后重新启动全部服务）\n'
  printf '0. 退出\n'
  printf '请选择 [0-3]: '
}

run_choice() {
  case "$1" in
    1) start_xingbao ;;
    2) stop_xingbao ;;
    3) restart_xingbao ;;
    0) return 0 ;;
    *) printf '[error] 请输入 0、1、2 或 3。\n' >&2; return 2 ;;
  esac
}

if [ "$#" -gt 0 ]; then
  case "$1" in
    start) run_choice 1 ;;
    stop) run_choice 2 ;;
    restart) run_choice 3 ;;
    *) printf 'Usage: %s [start|stop|restart]\n' "$0" >&2; exit 2 ;;
  esac
  exit 0
fi

while true; do
  show_menu
  read -r choice || exit 0
  [ "$choice" = "0" ] && exit 0
  run_choice "$choice" || true
done
