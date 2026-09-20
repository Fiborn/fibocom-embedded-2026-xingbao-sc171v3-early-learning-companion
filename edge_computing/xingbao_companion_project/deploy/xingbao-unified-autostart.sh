#!/usr/bin/env bash
# The only Xingbao boot entry is fibo's cron @reboot rule.  This script starts
# the current-project processes directly; it deliberately does not invoke
# systemd.  Set XINGBAO_SKIP_BOOT_UI_PREP=1 for a manual, already-booted start.
set -u

export HOME=/home/fibo
export USER=fibo
export LOGNAME=fibo
export XDG_RUNTIME_DIR=/run/user/5005
export WAYLAND_DISPLAY=${XINGBAO_WAYLAND_DISPLAY:-wayland-0}
# All Xingbao runtime services use the board system Python (3.8.10).  Keep
# Miniforge last only for unrelated shell utilities, never as `python3`.
export PATH=/usr/local/bin:/usr/bin:/bin:/home/fibo/miniforge3/bin
# All cloud HTTP calls and DashScope streaming ASR/TTS WebSockets must connect
# directly.  Do this before sourcing runtime.env and before any child starts.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*'
export no_proxy='*'

PROJECT=/home/fibo/xingbao_companion_project
ENV_FILE=/home/fibo/.config/xingbao/runtime.env
STATE_DIR=/home/fibo/.local/state/xingbao-unified
LOG_FILE="$STATE_DIR/autostart.log"
# The prior launcher accidentally leaked its lock descriptor into every
# long-lived child.  A new name releases this migration from those inherited
# old locks; new children explicitly close descriptor 9 below.
LOCK_FILE="$STATE_DIR/direct-cron.lock"
GDM_BOOT_MARKER="$STATE_DIR/gdm-restarted-boot-id"
BOOT_START_DELAY_MARKER="$STATE_DIR/boot-start-delay-boot-id"
UI_BOOT_DELAY_SECONDS=30
GDM_ACTIVE_TIMEOUT_SECONDS=30

mkdir -p "$STATE_DIR"
exec >>"$LOG_FILE" 2>&1
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -Is) another unified cron recovery is already running"
    exit 0
fi

if [ -r "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

echo "$(date -Is) unified direct-cron startup begin"

port_ready() {
    timeout 1 bash -c "</dev/tcp/127.0.0.1/$1" >/dev/null 2>&1
}

wait_for_port() {
    local port="$1"
    local label="$2"
    local max_attempts="${3:-60}"
    local attempt
    for attempt in $(seq 1 "$max_attempts"); do
        if port_ready "$port"; then
            echo "$(date -Is) ready $label port=$port"
            return 0
        fi
        sleep 1
    done
    echo "$(date -Is) ERROR unavailable $label port=$port"
    return 1
}

wayland_pygame_ready() {
    [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] || return 1
    env -u DISPLAY \
        XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
        WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
        SDL_VIDEODRIVER=wayland \
        PYTHONPATH=/home/fibo/.local/lib/python3.8/site-packages \
        /usr/bin/python3 -c 'import pygame; pygame.display.init(); assert pygame.display.get_driver() == "wayland"; pygame.display.quit()' \
        >/dev/null 2>&1
}

wait_for_wayland() {
    local attempt
    for attempt in $(seq 1 180); do
        if wayland_pygame_ready; then
            echo "$(date -Is) native Wayland UI session ready after ${attempt}s"
            return 0
        fi
        sleep 1
    done
    echo "$(date -Is) ERROR native Wayland UI session did not become ready"
    return 1
}

restart_gdm_once_per_boot() {
    local boot_id attempt gdm_state previous_state
    boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
    if [ -n "$boot_id" ] && [ -r "$GDM_BOOT_MARKER" ] && [ "$(cat "$GDM_BOOT_MARKER")" = "$boot_id" ]; then
        echo "$(date -Is) GDM already restarted for this boot"
        return 0
    fi
    echo "$(date -Is) restarting GDM before Wayland UI startup"
    # The board installs a sudoers rule limited to exactly this command.  No
    # password or broad administrator access is stored in cron or the project.
    # Keep this invocation identical to the narrowly scoped sudoers rule in
    # /etc/sudoers.d/xingbao-gdm-restart.  sudo command matching is exact:
    # neither /bin/systemctl nor gdm3.service matches that rule.
    if ! sudo -n /usr/bin/systemctl restart gdm3; then
        echo "$(date -Is) ERROR gdm3 restart command failed; UI startup aborted"
        return 1
    fi

    echo "$(date -Is) gdm3 restart command succeeded; waiting for state=active"
    previous_state=""
    for attempt in $(seq 1 "$GDM_ACTIVE_TIMEOUT_SECONDS"); do
        gdm_state=$(/bin/systemctl is-active gdm3.service 2>&1 || true)
        if [ "$gdm_state" = "active" ]; then
            echo "$(date -Is) gdm3 restart succeeded state=active after ${attempt}s"
            if [ -n "$boot_id" ]; then
                printf '%s\n' "$boot_id" >"$GDM_BOOT_MARKER"
            fi
            return 0
        fi
        if [ "$gdm_state" != "$previous_state" ]; then
            echo "$(date -Is) waiting for gdm3 state=${gdm_state:-unknown} attempt=${attempt}/${GDM_ACTIVE_TIMEOUT_SECONDS}"
            previous_state="$gdm_state"
        fi
        sleep 1
    done

    gdm_state=$(/bin/systemctl is-active gdm3.service 2>&1 || true)
    echo "$(date -Is) ERROR gdm3 restart did not reach state=active within ${GDM_ACTIVE_TIMEOUT_SECONDS}s final_state=${gdm_state:-unknown}; UI startup aborted"
    return 1
}

delay_startup_once_per_boot() {
    local boot_id
    boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
    if [ -n "$boot_id" ] && [ -r "$BOOT_START_DELAY_MARKER" ] && [ "$(cat "$BOOT_START_DELAY_MARKER")" = "$boot_id" ]; then
        echo "$(date -Is) boot startup delay already completed for this boot"
        return 0
    fi

    # The requested 30-second boot delay is intentionally before the GDM
    # restart. There is no fixed wait after GDM: wait_for_wayland below
    # proceeds immediately once native Wayland/Pygame is actually ready.
    echo "$(date -Is) delaying unified startup ${UI_BOOT_DELAY_SECONDS}s for boot stabilization"
    sleep "$UI_BOOT_DELAY_SECONDS"
    if [ -n "$boot_id" ]; then
        printf '%s\n' "$boot_id" >"$BOOT_START_DELAY_MARKER"
    fi
}

process_running() {
    pgrep -f "$1" >/dev/null 2>&1
}

stop_legacy_project_processes() {
    local legacy_project=/home/fibo/xingbao_companion_unified
    local release_root=/home/fibo/xingbao_releases
    local proc pid cwd remaining
    local -a pids=()

    [ -d "$legacy_project" ] || return 0
    for proc in /proc/[0-9]*; do
        pid=${proc##*/}
        cwd=$(readlink -f "$proc/cwd" 2>/dev/null || true)
        case "$cwd" in
            "$legacy_project"|"$legacy_project"/*|"$release_root"/*) pids+=("$pid") ;;
        esac
    done
    [ "${#pids[@]}" -gt 0 ] || return 0

    echo "$(date -Is) replacing legacy runtime pids=${pids[*]}"
    kill -TERM "${pids[@]}" 2>/dev/null || true
    for _ in $(seq 1 8); do
        remaining=0
        for pid in "${pids[@]}"; do
            kill -0 "$pid" 2>/dev/null && remaining=1
        done
        [ "$remaining" -eq 0 ] && return 0
        sleep 1
    done
    echo "$(date -Is) force-stopping remaining legacy runtime processes"
    kill -KILL "${pids[@]}" 2>/dev/null || true
}

restart_touch_ui() {
    local pids pid
    pids=$(pgrep -f 'board_start_wayland_ui\.sh|tools/board_phase1_ui\.py' || true)
    [ -n "$pids" ] || return 0
    for pid in $pids; do
        # A caller may itself contain these literal script names (for example
        # an automated diagnostic command). Never terminate this launcher or
        # the shell that invoked it.
        [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ] && continue
        echo "$(date -Is) restarting touch UI pid=$pid"
        kill -TERM "$pid" 2>/dev/null || true
    done
    sleep 2
}

start_process() {
    local label="$1"
    shift
    echo "$(date -Is) starting $label"
    setsid "$@" 9>&- >>"$STATE_DIR/$label.log" 2>&1 </dev/null &
    echo "$!" >"$STATE_DIR/$label.pid"
}

ensure_port_process() {
    local label="$1"
    local port="$2"
    local pattern="$3"
    local max_attempts="$4"
    shift 4
    if port_ready "$port"; then
        echo "$(date -Is) already-ready $label port=$port"
        return 0
    fi
    if process_running "$pattern"; then
        echo "$(date -Is) waiting-existing $label port=$port"
    else
        start_process "$label" "$@"
    fi
    wait_for_port "$port" "$label" "$max_attempts"
}

if [ ! -d "$PROJECT" ]; then
    echo "$(date -Is) ERROR missing project directory: $PROJECT"
    exit 10
fi

if [ "${XINGBAO_SKIP_BOOT_UI_PREP:-0}" != "1" ]; then
    if ! delay_startup_once_per_boot; then
        exit 20
    fi
    if ! restart_gdm_once_per_boot; then
        exit 21
    fi
else
    echo "$(date -Is) manual startup: skipping boot delay and GDM restart"
fi
if ! wait_for_wayland; then
    exit 22
fi

cd "$PROJECT"

# One runtime.env switch controls both the voice backend and the optional
# Sherpa server.  Do this before central voice starts so local mode never
# races its first recognition request, while cloud mode releases stale ASR.
"$PROJECT/deploy/manage_local_asr.sh" ensure || exit 30

if [ "${XINGBAO_REPLACE_LEGACY_RUNTIME:-0}" = "1" ]; then
    stop_legacy_project_processes
    restart_touch_ui
fi

# Fixed dependency order.  Each process is launched directly by cron, not
# through a service manager: camera -> arm -> six-point bridge -> UI ->
# central voice/game (which owns the unified vision process) -> auth. The optional vision
# visualization window is intentionally controlled separately.
ensure_port_process camera 4445 'deploy/start_camera_stream.sh' 90 \
    /bin/sh "$PROJECT/deploy/start_camera_stream.sh" || exit 31

ensure_port_process arm 8764 'arm_action_server_soft_nod.py' 90 \
    /bin/sh -c "cd '$PROJECT/components/arm_soarm101' && exec /home/fibo/miniforge3/bin/python3 arm_action_server_soft_nod.py" || exit 32

ensure_port_process hand-server 10000 'soarm101_module/arm_command_server_10000.py' 60 \
    /bin/sh -c "cd '$PROJECT' && exec /usr/bin/python3 -u soarm101_module/arm_command_server_10000.py" || exit 33

ensure_port_process ui 8765 'board_start_wayland_ui.sh' 120 \
    /bin/bash "$PROJECT/deploy/board_start_wayland_ui.sh" || exit 34

ensure_port_process central 8766 'main.py --wake-chat' 120 \
    /bin/sh -c "cd '$PROJECT' && exec /bin/sh deploy/board_start_demo.sh" || exit 35

ensure_port_process auth 8787 '/home/fibo/xingbao_web/auth_service.py' 30 \
    /usr/bin/python3 /home/fibo/xingbao_web/auth_service.py || exit 36

if /usr/bin/python3 "$PROJECT/tools/board_health_check.py" \
    --host 127.0.0.1 --port 8765 --timeout 8 --skip-ui --skip-wake-model; then
    echo "$(date -Is) unified direct-cron startup verified"
else
    # The optional sounddevice import can block while ALSA is owned by the
    # already-running companion.  Core process and port readiness above are
    # authoritative for cron; keep this as a diagnostic warning only.
    echo "$(date -Is) WARN non-UI diagnostic health check failed; core runtime remains active"
fi
exit 0
