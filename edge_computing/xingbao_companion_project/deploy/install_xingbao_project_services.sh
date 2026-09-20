#!/usr/bin/env sh
set -eu

# Install the four user services from this project. They intentionally all
# point at /home/fibo/xingbao_project, so a cold boot starts the same tree that
# is used for an on-site manual recovery.
PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
USER_UNIT_DIR="$HOME/.config/systemd/user"
LEGACY_AUTOSTART="$HOME/.config/autostart/touch-game.desktop"

# Earlier assembly experiments installed a parallel xingbao-unified service
# family.  Leaving it enabled makes it reclaim the UI bridge port and camera
# after login, which mixes an old runtime with this project.  Disable only
# those explicitly named legacy units; failures are harmless when absent.
for unit in \
    xingbao-unified-ui.service \
    xingbao-unified-camera.service \
    xingbao-unified-arm.service \
    xingbao-unified-main.service \
    xingbao-unified-hand-server.service; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
done

# The old desktop autostart points at a pre-unification release.  Keep a
# recoverable renamed copy only when it is exactly that legacy launcher.
if [ -f "$LEGACY_AUTOSTART" ] && grep -q 'xingbao_touch_game' "$LEGACY_AUTOSTART"; then
    mv "$LEGACY_AUTOSTART" "$LEGACY_AUTOSTART.legacy-disabled"
fi

mkdir -p "$USER_UNIT_DIR"
for unit in xingbao-central.service touch-game.service xingbao-arm.service xingbao-camera.service; do
    install -m 0644 "$PROJECT_ROOT/deploy/systemd/$unit" "$USER_UNIT_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user enable xingbao-camera.service touch-game.service xingbao-arm.service xingbao-central.service
