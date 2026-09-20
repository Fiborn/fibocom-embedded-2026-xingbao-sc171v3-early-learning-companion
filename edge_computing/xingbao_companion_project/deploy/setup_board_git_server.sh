#!/usr/bin/env sh
set -eu

# This script is intentionally gated. The board competition runtime must be
# audited before a shared Git server is created, and this script must never be
# used as a shortcut to declare a local PC branch authoritative.
if [ "${XINGBAO_BOARD_BASELINE_AUDITED:-}" != "YES" ]; then
  echo "Refusing setup: complete and approve the board baseline audit first." >&2
  echo "Then rerun with XINGBAO_BOARD_BASELINE_AUDITED=YES." >&2
  exit 2
fi

GIT_BASE="${XINGBAO_BOARD_GIT_BASE:-/home/fibo/xingbao_git}"
REPO_PATH="$GIT_BASE/xingbao-companion.git"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
HOOK_SOURCE="$SCRIPT_DIR/hooks/xingbao-pre-receive"

case "$GIT_BASE" in
  /home/fibo/xingbao_git|/home/fibo/xingbao_git/*)
    ;;
  *)
    echo "Refusing unsafe Git base outside /home/fibo/xingbao_git: $GIT_BASE" >&2
    exit 2
    ;;
esac

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed on the board." >&2
  exit 2
fi

mkdir -p "$GIT_BASE"
if [ ! -d "$REPO_PATH" ]; then
  git init --bare "$REPO_PATH"
fi

git --git-dir="$REPO_PATH" config receive.denyNonFastForwards true
git --git-dir="$REPO_PATH" config receive.denyDeletes true
git --git-dir="$REPO_PATH" config core.sharedRepository group

if [ ! -f "$HOOK_SOURCE" ]; then
  echo "Missing server hook template: $HOOK_SOURCE" >&2
  exit 2
fi
HOOK_PATH="$REPO_PATH/hooks/pre-receive"
cp "$HOOK_SOURCE" "$HOOK_PATH"
chmod 0755 "$HOOK_PATH"

echo "Board Git repository ready: $REPO_PATH"
echo "Remote URL: fibo@<current-board-host>:$REPO_PATH"
echo "Replace <current-board-host> with the address discovered on the current network."
echo "Do not push local main as the board baseline. Import the audited board snapshot first."
