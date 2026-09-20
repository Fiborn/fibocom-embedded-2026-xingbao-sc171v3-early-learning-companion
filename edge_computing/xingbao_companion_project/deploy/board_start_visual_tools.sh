#!/usr/bin/env sh
set -eu

cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if [ "$#" -gt 0 ]; then
  exec "$PYTHON_BIN" main.py --kids-visual-tool "$1"
fi

exec "$PYTHON_BIN" main.py --kids-visual-tools
