#!/usr/bin/env bash
# Restart the local Xingbao stack in a defined order.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

"$SCRIPT_DIR/quick_stop_local.sh"
exec "$SCRIPT_DIR/quick_start_local.sh"
