#!/usr/bin/env bash
# Quickly start the Xingbao services from this project after the board is up.
# Unlike the cron launcher, this does not wait for boot stabilization or
# restart GDM; it keeps the same idempotent service order and readiness checks.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"

if [ ! -x "$PROJECT_DIR/deploy/xingbao-unified-autostart.sh" ]; then
  printf 'Missing launcher: %s\n' "$PROJECT_DIR/deploy/xingbao-unified-autostart.sh" >&2
  exit 1
fi

cd "$PROJECT_DIR"
exec env XINGBAO_SKIP_BOOT_UI_PREP=1 XINGBAO_REPLACE_LEGACY_RUNTIME=1 \
  "$PROJECT_DIR/deploy/xingbao-unified-autostart.sh"
