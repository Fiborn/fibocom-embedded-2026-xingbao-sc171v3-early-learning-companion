#!/usr/bin/env sh
set -eu

# Single recovery command for an on-site terminal session. The unit files are
# installed separately and remain enabled across reboots; this command starts
# the same four services without requiring Codex.
systemctl --user daemon-reload
systemctl --user reset-failed xingbao-camera.service touch-game.service xingbao-arm.service xingbao-central.service
systemctl --user start xingbao-camera.service touch-game.service xingbao-arm.service xingbao-central.service
systemctl --user --no-pager --full status xingbao-camera.service touch-game.service xingbao-arm.service xingbao-central.service
