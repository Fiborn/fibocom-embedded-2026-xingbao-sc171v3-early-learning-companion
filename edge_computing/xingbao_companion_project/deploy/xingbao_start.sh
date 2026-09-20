#!/usr/bin/env sh
set -eu

# Stable operator entry point for the frozen competition release.  It always
# resolves the active immutable release through `current`, so it remains valid
# after a restart, rollback, or a future signed release switch.
CENTRAL_CURRENT="/home/fibo/xingbao_releases/current"
START_SCRIPT="$CENTRAL_CURRENT/deploy/board_one_click_deploy.sh"

[ -f "$START_SCRIPT" ] || {
  echo "[xingbao] active release start script not found: $START_SCRIPT" >&2
  exit 1
}

exec /bin/sh "$START_SCRIPT" start
