#!/usr/bin/env sh
set -eu

# One-command installer and starter for the reviewed Xingbao board release.
# It never overwrites runtime.env, API keys, child memory, artworks, or saves.

MODE="${1:-start}"
CENTRAL_PACKAGE="${2:-}"
TOUCH_PACKAGE="${3:-}"

BASE="/home/fibo/arm_luojiefu/xingbao/xingbao"
# The historical directory remains intact as the first rollback source.  New
# releases are immutable directories selected only by the atomic `current`
# link, so an interrupted update can never leave a partially copied program.
CENTRAL_LEGACY_DIR="$BASE/xingbao_companion"
CENTRAL_RELEASES="/home/fibo/xingbao_releases"
CENTRAL_DIR="$CENTRAL_RELEASES/current"
CENTRAL_PREVIOUS="$CENTRAL_RELEASES/previous"
CENTRAL_RUNTIME="/home/fibo/xingbao_runtime"
TOUCH_LINK="$BASE/xingbao_touch_game_bridge"
TOUCH_RELEASES="$BASE/xingbao_touch_game_bridge_releases"
TOUCH_PREVIOUS="$TOUCH_RELEASES/previous"
TOUCH_SHARED="$BASE/xingbao_touch_game_shared"
ARM_DIR="$BASE/xingbao_competition_fix_20260721_r5/project/hardware/soarm101"
ENV_FILE="/home/fibo/.config/xingbao/runtime.env"
USER_UNITS="/home/fibo/.config/systemd/user"
ONE_CLICK_HOME="/home/fibo/xingbao_one_click"
RECOVERY_HOME="/home/fibo/xingbao_recovery_backups/one_click"
PYTHON_BIN="/usr/bin/python3"
SYSTEM_PYTHON="/usr/bin/python3"

export HOME="/home/fibo"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
export DISPLAY="${DISPLAY:-:0}"

log() {
    printf '[one-click] %s\n' "$*"
}

fail() {
    printf '[one-click] RESULT=FAILED reason=%s\n' "$*" >&2
    exit 1
}

require_file() {
    [ -f "$1" ] || fail "missing_file:$1"
}

set_release_link() {
    link_path="$1"
    target_path="$2"
    temp_link="$link_path.next.$$"
    ln -s "$target_path" "$temp_link"
    mv -Tf "$temp_link" "$link_path"
}

manifest_is_valid() {
    release_dir="$1"
    [ -f "$release_dir/RELEASE_MANIFEST.json" ] || return 1
    [ -f "$release_dir/tools/release_manifest.py" ] || return 1
    "$SYSTEM_PYTHON" "$release_dir/tools/release_manifest.py" \
        "$release_dir" --verify >/dev/null 2>&1
}

activate_previous_release() {
    previous_release="$(readlink -f "$CENTRAL_PREVIOUS" 2>/dev/null || true)"
    [ -n "$previous_release" ] || fail "current_release_invalid_previous_missing"
    manifest_is_valid "$previous_release" || fail "current_release_invalid_previous_invalid"
    set_release_link "$CENTRAL_DIR" "$previous_release"
    log "Current release failed validation; rolled back to $(basename "$previous_release")"
}

ensure_active_release() {
    if manifest_is_valid "$CENTRAL_DIR"; then
        return 0
    fi
    activate_previous_release
}

prepare_runtime_directories() {
    mkdir -p "$CENTRAL_RUNTIME"
    for runtime_name in data logs work; do
        legacy_path="$CENTRAL_LEGACY_DIR/$runtime_name"
        runtime_path="$CENTRAL_RUNTIME/$runtime_name"
        if [ ! -e "$runtime_path" ]; then
            if [ -d "$legacy_path" ] && [ ! -L "$legacy_path" ]; then
                mv "$legacy_path" "$runtime_path"
            else
                mkdir -p "$runtime_path"
            fi
        fi
        if [ -e "$legacy_path" ] && [ ! -L "$legacy_path" ]; then
            fail "legacy_runtime_conflict:$legacy_path"
        fi
        if [ ! -e "$legacy_path" ]; then
            ln -s "$runtime_path" "$legacy_path"
        fi
    done
}

link_release_runtime() {
    release_dir="$1"
    for runtime_name in data logs work; do
        release_runtime="$release_dir/$runtime_name"
        rm -rf -- "$release_runtime"
        ln -s "$CENTRAL_RUNTIME/$runtime_name" "$release_runtime"
    done
}

stop_unmanaged_project_processes() {
    for proc_dir in /proc/[0-9]*; do
        [ -d "$proc_dir" ] || continue
        pid="${proc_dir#/proc/}"
        cwd="$(readlink -f "$proc_dir/cwd" 2>/dev/null || true)"
        case "$cwd" in
            "$BASE"/*) ;;
            *) continue ;;
        esac
        command_line="$(tr '\000' ' ' <"$proc_dir/cmdline" 2>/dev/null || true)"
        case "$command_line" in
            *main.py*|*board_phase1_ui.py*|*arm_action_server_soft_nod.py*|*start_camera_stream.sh*)
                kill -TERM "$pid" 2>/dev/null || true
                ;;
        esac
    done
    sleep 2
}

wait_port() {
    port="$1"
    attempts="$2"
    count=0
    while ! ss -ltn 2>/dev/null | grep -q ":$port "; do
        count=$((count + 1))
        if [ "$count" -ge "$attempts" ]; then
            return 1
        fi
        sleep 1
    done
}

verify_sidecar_hash() {
    package="$1"
    sidecar="$package.sha256"
    require_file "$package"
    require_file "$sidecar"
    expected="$(awk 'NR == 1 {print $1}' "$sidecar")"
    actual="$(sha256sum "$package" | awk '{print $1}')"
    [ -n "$expected" ] || fail "empty_sha256:$sidecar"
    [ "$actual" = "$expected" ] || fail "sha256_mismatch:$package"
    log "SHA256 verified: $(basename "$package")"
}

extract_zip() {
    package="$1"
    destination="$2"
    mkdir -p "$destination"
    "$SYSTEM_PYTHON" - "$package" "$destination" <<'PY'
import sys
import zipfile
from pathlib import Path

package = Path(sys.argv[1])
destination = Path(sys.argv[2])
with zipfile.ZipFile(package) as archive:
    bad = archive.testzip()
    if bad:
        raise SystemExit(f"zip_crc_error:{bad}")
    archive.extractall(destination)
PY
}

backup_runtime_metadata() {
    stamp="$1"
    backup="$RECOVERY_HOME/$stamp"
    active_central="$(readlink -f "$CENTRAL_DIR" 2>/dev/null || true)"
    if [ -z "$active_central" ]; then
        active_central="$CENTRAL_LEGACY_DIR"
    fi
    mkdir -p "$backup/user_units"
    chmod 700 "$backup" "$backup/user_units"
    if [ -f "$ENV_FILE" ]; then
        cp "$ENV_FILE" "$backup/runtime.env"
        chmod 600 "$backup/runtime.env"
    fi
    for unit in touch-game.service xingbao-arm.service xingbao-camera.service xingbao-central.service; do
        if [ -f "$USER_UNITS/$unit" ]; then
            cp "$USER_UNITS/$unit" "$backup/user_units/$unit"
        fi
    done
    readlink -f "$TOUCH_LINK" >"$backup/previous_touch_release.txt" 2>/dev/null || true
    {
        for path in \
            "$active_central/app.py" \
            "$active_central/main.py" \
            "$active_central/core/board_ui_client.py" \
            "$active_central/core/game_speech_server.py" \
            "$active_central/tools/board_phase1_ui.py"; do
            [ -f "$path" ] && sha256sum "$path"
        done
    } >"$backup/before.sha256"
    printf '%s\n' "$active_central" >"$backup/previous_central_release.txt"
    log "Recovery metadata: $backup"
}

install_release() {
    [ "$(id -un)" = "fibo" ] || fail "run_as_fibo"
    require_file "$ENV_FILE"
    verify_sidecar_hash "$CENTRAL_PACKAGE"
    verify_sidecar_hash "$TOUCH_PACKAGE"
    require_file "$ARM_DIR/arm_action_server_soft_nod.py"

    stamp="$(date +%Y%m%d_%H%M%S)"
    staging="$ONE_CLICK_HOME/staging/$stamp"
    central_stage="$staging/central"
    touch_stage="$staging/touch"
    new_central_release=""
    new_touch_release="$TOUCH_RELEASES/one-click-$stamp"
    # Preserve the actual release that was running immediately before this
    # install as the first rollback target.  The older `previous` link may
    # point to a much older build and must not outrank the live baseline.
    active_central_before="$(readlink -f "$CENTRAL_DIR" 2>/dev/null || true)"

    backup_runtime_metadata "$stamp"
    log "Extracting reviewed packages..."
    extract_zip "$CENTRAL_PACKAGE" "$central_stage"
    extract_zip "$TOUCH_PACKAGE" "$touch_stage"

    central_payload="$central_stage/xingbao_companion"
    require_file "$central_payload/main.py"
    require_file "$central_payload/tools/board_phase1_ui.py"
    require_file "$central_payload/deploy/systemd/xingbao-central.service"
    require_file "$central_payload/deploy/xingbao_start.sh"
    require_file "$central_payload/RELEASE_MANIFEST.json"
    require_file "$central_payload/tools/release_manifest.py"
    require_file "$touch_stage/desktop.py"
    require_file "$touch_stage/src/app.py"
    manifest_is_valid "$central_payload" || fail "central_release_manifest_invalid"
    release_id="$("$SYSTEM_PYTHON" "$central_payload/tools/release_manifest.py" \
        "$central_payload" --print-release-id)"
    case "$release_id" in
        ""|*[!A-Za-z0-9._-]*) fail "unsafe_release_id:$release_id" ;;
    esac
    new_central_release="$CENTRAL_RELEASES/$release_id-$stamp"

    current_touch="$(readlink -f "$TOUCH_LINK" 2>/dev/null || true)"
    saves_source=""
    if [ -n "$current_touch" ] && [ -d "$current_touch/saves" ]; then
        saves_source="$current_touch/saves"
    elif [ -d "$TOUCH_SHARED/saves" ]; then
        saves_source="$TOUCH_SHARED/saves"
    fi
    [ -n "$saves_source" ] || fail "touch_saves_not_found"

    log "Stopping supervised services..."
    systemctl --user stop xingbao-central.service touch-game.service xingbao-arm.service xingbao-camera.service 2>/dev/null || true
    stop_unmanaged_project_processes

    # Older installations used TOUCH_LINK as a normal directory.  Preserve
    # that entire directory before changing the path into an atomic symlink;
    # this avoids overwriting it and provides a concrete touch-side rollback.
    mkdir -p "$TOUCH_RELEASES"
    if [ -d "$TOUCH_LINK" ] && [ ! -L "$TOUCH_LINK" ]; then
        legacy_touch="$TOUCH_RELEASES/legacy-$stamp"
        mv "$TOUCH_LINK" "$legacy_touch"
        current_touch="$legacy_touch"
        if [ -d "$legacy_touch/saves" ]; then
            saves_source="$legacy_touch/saves"
        fi
    fi

    log "Activating an immutable central release without deleting runtime data..."
    mkdir -p "$CENTRAL_RELEASES"
    prepare_runtime_directories
    mv "$central_payload" "$new_central_release"
    link_release_runtime "$new_central_release"
    manifest_is_valid "$new_central_release" || fail "central_release_post_link_invalid"
    previous_central="$active_central_before"
    if [ -n "$previous_central" ] && [ -d "$previous_central" ]; then
        :
    elif [ -L "$CENTRAL_PREVIOUS" ] && [ -d "$(readlink -f "$CENTRAL_PREVIOUS" 2>/dev/null || true)" ]; then
        previous_central="$(readlink -f "$CENTRAL_PREVIOUS")"
    elif [ -d "$CENTRAL_LEGACY_DIR" ] && [ ! -f "$CENTRAL_LEGACY_DIR/RELEASE_MANIFEST.json" ]; then
        # Complete a first-release migration that was interrupted before the
        # historical directory could be registered as the rollback target.
        previous_central="$CENTRAL_LEGACY_DIR"
    elif [ -L "$CENTRAL_DIR" ] && [ -d "$(readlink -f "$CENTRAL_DIR" 2>/dev/null || true)" ]; then
        previous_central="$(readlink -f "$CENTRAL_DIR")"
    else
        previous_central="$CENTRAL_LEGACY_DIR"
    fi
    if [ -d "$previous_central" ]; then
        if ! manifest_is_valid "$previous_central"; then
            "$SYSTEM_PYTHON" "$new_central_release/tools/release_manifest.py" \
                "$previous_central" --create >/dev/null
        fi
        manifest_is_valid "$previous_central" || fail "previous_central_manifest_invalid"
        set_release_link "$CENTRAL_PREVIOUS" "$previous_central"
    fi
    set_release_link "$CENTRAL_DIR" "$new_central_release"

    log "Creating an immutable touch release and carrying forward saves..."
    mkdir -p "$new_touch_release"
    cp -a "$touch_stage/." "$new_touch_release/"
    rm -rf -- "$new_touch_release/saves"
    mkdir -p "$TOUCH_SHARED/saves" "$TOUCH_SHARED/logs"
    if [ "$saves_source" != "$TOUCH_SHARED/saves" ]; then
        cp -an "$saves_source/." "$TOUCH_SHARED/saves/" 2>/dev/null || true
    fi
    ln -s "$TOUCH_SHARED/saves" "$new_touch_release/saves"
    rm -rf -- "$new_touch_release/logs"
    ln -s "$TOUCH_SHARED/logs" "$new_touch_release/logs"
    if [ -n "$current_touch" ] && [ -d "$current_touch" ]; then
        set_release_link "$TOUCH_PREVIOUS" "$current_touch"
    fi
    set_release_link "$TOUCH_LINK" "$new_touch_release"

    mkdir -p "$USER_UNITS"
    for unit in touch-game.service xingbao-arm.service xingbao-camera.service xingbao-central.service; do
        install -m 0644 "$new_central_release/deploy/systemd/$unit" "$USER_UNITS/$unit"
    done
    # This stable path survives release-directory changes.  If remote tooling
    # is unavailable after a reboot, the operator only needs this one command:
    #   sh /home/fibo/xingbao_start.sh
    install -m 0755 "$new_central_release/deploy/xingbao_start.sh" "$HOME/xingbao_start.sh"
    chmod +x \
        "$new_central_release/deploy/start_camera_stream.sh" \
        "$new_central_release/deploy/board_one_click_deploy.sh"
    systemctl --user daemon-reload
    systemctl --user reenable \
        touch-game.service \
        xingbao-arm.service \
        xingbao-camera.service \
        xingbao-central.service >/dev/null

    printf 'timestamp=%s\nrelease_id=%s\ncentral_release=%s\nprevious_central_release=%s\ncentral_sha256=%s\ncentral_manifest_sha256=%s\ntouch_sha256=%s\ntouch_release=%s\n' \
        "$stamp" \
        "$release_id" \
        "$new_central_release" \
        "$previous_central" \
        "$(sha256sum "$CENTRAL_PACKAGE" | awk '{print $1}')" \
        "$(sha256sum "$new_central_release/RELEASE_MANIFEST.json" | awk '{print $1}')" \
        "$(sha256sum "$TOUCH_PACKAGE" | awk '{print $1}')" \
        "$new_touch_release" \
        >"$ONE_CLICK_HOME/installed_release.txt"

    rm -rf -- "$staging"
    log "Reviewed release installed. Runtime data and saves were preserved."
}

usb_camera_present() {
    for node in /sys/class/video4linux/video*; do
        [ -e "$node" ] || continue
        resolved="$(readlink -f "$node/device" 2>/dev/null || true)"
        case "$resolved" in
            *"/usb"*|*"/usb-"*) ;;
            *) continue ;;
        esac
        device="/dev/$(basename "$node")"
        [ -c "$device" ] || continue
        if v4l2-ctl --device="$device" --all 2>/dev/null | grep -q "Video Capture"; then
            return 0
        fi
    done
    return 1
}

check_camera_frame() {
    timeout 20 "$SYSTEM_PYTHON" - <<'PY'
import cv2

capture = cv2.VideoCapture("http://127.0.0.1:8080/?action=stream")
ok, frame = capture.read()
capture.release()
if not ok or frame is None or frame.size == 0:
    raise SystemExit(1)
print(f"[one-click] camera_frame={frame.shape[1]}x{frame.shape[0]}")
PY
}

start_and_check() {
    ensure_active_release
    require_file "$CENTRAL_DIR/main.py"
    require_file "$CENTRAL_DIR/tools/board_phase1_ui.py"
    require_file "$ENV_FILE"
    require_file "$ARM_DIR/arm_action_server_soft_nod.py"

    log "Starting UI, arm safety service, and camera supervisor..."
    systemctl --user daemon-reload
    systemctl --user enable \
        touch-game.service \
        xingbao-arm.service \
        xingbao-camera.service \
        xingbao-central.service >/dev/null
    systemctl --user restart touch-game.service xingbao-arm.service xingbao-camera.service

    wait_port 8765 90 || fail "ui_port_8765_timeout"
    wait_port 8764 45 || fail "arm_port_8764_timeout"

    log "Starting central voice, game speech, and visual perception..."
    systemctl --user restart xingbao-central.service
    wait_port 8766 90 || fail "central_port_8766_timeout"

    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    [ -n "${DASHSCOPE_API_KEY:-}" ] || fail "DASHSCOPE_API_KEY_not_set"

    cd "$CENTRAL_DIR"
    "$SYSTEM_PYTHON" tools/release_manifest.py . --verify \
        >/tmp/xingbao_one_click_release.json \
        || fail "active_release_manifest_invalid"
    "$SYSTEM_PYTHON" tools/board_health_check.py >/tmp/xingbao_one_click_health.json \
        || fail "board_health_check_failed"

    tool_count="$($SYSTEM_PYTHON -c 'import json; print(len(json.load(open("config/kids_visual_tools_registry.json", encoding="utf-8"))["tools"]))')"
    [ "$tool_count" = "85" ] || fail "toolbox_count:$tool_count"

    for service in touch-game.service xingbao-arm.service xingbao-camera.service xingbao-central.service; do
        systemctl --user is-active --quiet "$service" || fail "service_inactive:$service"
    done

    camera_status="ready"
    if usb_camera_present; then
        if ! wait_port 8080 45; then
            camera_status="stream_timeout"
        elif ! check_camera_frame; then
            camera_status="frame_failed"
        fi
    else
        camera_status="usb_camera_missing"
    fi

    log "UI=ready ARM=ready CENTRAL=ready TOOLBOX=85 CAMERA=$camera_status"
    if [ "$camera_status" = "ready" ]; then
        printf '[one-click] RESULT=READY all_features=available\n'
        return 0
    fi

    printf '[one-click] RESULT=DEGRADED reason=%s\n' "$camera_status" >&2
    printf '[one-click] 请插紧USB摄像头，然后重新执行同一条命令。\n' >&2
    return 2
}

case "$MODE" in
    install)
        [ -n "$CENTRAL_PACKAGE" ] || fail "central_package_argument_missing"
        [ -n "$TOUCH_PACKAGE" ] || fail "touch_package_argument_missing"
        install_release
        start_and_check
        ;;
    start)
        start_and_check
        ;;
    *)
        fail "unsupported_mode:$MODE"
        ;;
esac
