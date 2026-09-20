#!/usr/bin/env bash
# Manage the one vision runtime owned by the unified Xingbao service.
# This script never starts multimodal.vision_system.app itself: doing so would
# create a second camera/event consumer that the center cannot supervise.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
ENV_FILE="${XINGBAO_ENV_FILE:-${HOME:-/home/fibo}/.config/xingbao/runtime.env}"
CONTROL_HOST="127.0.0.1"
SERVICE_MANAGER="$SCRIPT_DIR/xingbao_service_manager.sh"

load_runtime_environment() {
  if [ -r "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  fi
}

control_action() {
  local action="$1"
  local port="${XINGBAO_VISION_CONTROL_PORT:-8768}"
  XINGBAO_CONTROL_HOST="$CONTROL_HOST" \
  XINGBAO_CONTROL_PORT="$port" \
  XINGBAO_CONTROL_ACTION="$action" \
  /usr/bin/python3 - <<'PY'
import json
import os
import socket
import sys

host = os.environ["XINGBAO_CONTROL_HOST"]
port = int(os.environ["XINGBAO_CONTROL_PORT"])
action = os.environ["XINGBAO_CONTROL_ACTION"]
request = {"type": "vision_runtime_control", "action": action}
try:
    with socket.create_connection((host, port), timeout=3.0) as connection:
        connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        response_line = connection.makefile("rb").readline()
    response = json.loads(response_line.decode("utf-8"))
except (OSError, ValueError, json.JSONDecodeError) as exc:
    print("[vision] unified service control unavailable: {}".format(exc), file=sys.stderr)
    raise SystemExit(1)

print(json.dumps(response, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if response.get("ok") else 1)
PY
}

persist_runtime_setting() {
  local key="$1" value="$2" env_dir temporary
  env_dir=$(dirname -- "$ENV_FILE")
  mkdir -p "$env_dir"
  temporary=$(mktemp "$env_dir/runtime.env.XXXXXX")
  if [ -r "$ENV_FILE" ]; then
    grep -Ev "^${key}=" "$ENV_FILE" >"$temporary" || true
  fi
  printf '%s=%s\n' "$key" "$value" >>"$temporary"
  mv "$temporary" "$ENV_FILE"
  printf '[vision] saved %s=%s to %s\n' "$key" "$value" "$ENV_FILE"
}

switch_visualization() {
  local value
  printf '可视化：1) 开启  0) 关闭\n请输入 [0-1]: '
  read -r value || return 1
  case "$value" in
    1|0) persist_runtime_setting XINGBAO_VISION_VISUALIZE "$value" ;;
    *) printf '[vision] 请输入 0 或 1。\n' >&2; return 2 ;;
  esac
  printf '[vision] 配置已保存；选择 6 重启总服务后立即生效。\n'
}

switch_always_on_top() {
  local value
  printf '窗口置顶：1) 开启  0) 关闭\n请输入 [0-1]: '
  read -r value || return 1
  case "$value" in
    1|0) persist_runtime_setting XINGBAO_VISION_ALWAYS_ON_TOP "$value" ;;
    *) printf '[vision] 请输入 0 或 1。\n' >&2; return 2 ;;
  esac
  printf '[vision] 配置已保存；选择 6 重启总服务后立即生效。\n'
}

restart_total_service() {
  if [ ! -x "$SERVICE_MANAGER" ]; then
    printf '[vision] 缺少总服务管理脚本：%s\n' "$SERVICE_MANAGER" >&2
    return 1
  fi
  printf '[vision] restarting the unified Xingbao service so runtime.env is reloaded...\n'
  "$SERVICE_MANAGER" restart
}

choose_action() {
  printf '\n星宝视觉服务（由总服务统一托管）\n'
  printf '1. 启动视觉\n2. 停止视觉\n3. 仅重启视觉\n4. 切换可视化\n5. 切换窗口置顶\n6. 重启总服务\n0. 退出\n请选择 [0-6]: '
  read -r action || exit 0
  case "$action" in
    1) control_action start ;;
    2) control_action stop ;;
    3) control_action restart ;;
    4) switch_visualization ;;
    5) switch_always_on_top ;;
    6) restart_total_service ;;
    0) exit 0 ;;
    *) printf '[vision] 无效选项\n' >&2; return 2 ;;
  esac
}

load_runtime_environment
case "${1:-menu}" in
  menu) choose_action ;;
  start|stop|restart|status) control_action "$1" ;;
  restart-total) restart_total_service ;;
  *) printf 'Usage: %s [menu|start|stop|restart|status|restart-total]\n' "$0" >&2; exit 2 ;;
esac
