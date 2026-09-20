#!/usr/bin/env sh
set -eu

cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

if command -v apt-get >/dev/null 2>&1; then
  if [ "$(id -u)" = "0" ]; then
    apt-get update || true
    apt-get install -y python3-pip python3-dev python3-tk portaudio19-dev alsa-utils || true
  else
    echo "Not root; skip apt packages. If sounddevice or Tkinter fails, install python3-pip python3-dev python3-tk portaudio19-dev alsa-utils."
  fi
fi

"$PYTHON_BIN" -m pip install -r requirements.txt

if [ -f requirements-wake-word.txt ]; then
  "$PYTHON_BIN" -m pip install -r requirements-wake-word.txt || {
    echo "Wake-word dependency install failed. You can still test with --voice-once, but --wake-chat needs openwakeword."
  }
fi

if [ "${XINGBAO_INSTALL_VISION_DEPS:-0}" = "1" ]; then
  VISION_PYTHON="${XINGBAO_VISION_PYTHON:-$PYTHON_BIN}"
  if "$VISION_PYTHON" -c "import cv2, numpy" >/dev/null 2>&1; then
    echo "Vision OpenCV/Numpy dependencies are already available."
  else
    "$VISION_PYTHON" -m pip install -r requirements-vision-board.txt
  fi
  if [ "${XINGBAO_VISION_NO_OBJECTS:-1}" != "1" ]; then
    "$VISION_PYTHON" -m pip install -r requirements-vision.txt
  fi
else
  echo "Vision dependency install skipped. Set XINGBAO_INSTALL_VISION_DEPS=1 to install it."
fi

echo "Dependencies installed. Next run:"
echo "$PYTHON_BIN tools/board_health_check.py"
