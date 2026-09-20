# Central Vision Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the manual vision manager control the one production `VisionProcessBridge` without direct subprocess launches or duplicate visual services.

**Architecture:** A loopback NDJSON server delegates four fixed actions to a locked controller that owns the bridge. `main.py` creates this controller beside the current vision runtime and the shell manager becomes a small control client. Restart reloads shared runtime environment settings.

**Tech Stack:** Python 3.8, `socketserver`, NDJSON over loopback TCP, Bash, pytest, native Wayland headless vision runtime.

**Spec:** `docs/superpowers/specs/2026-08-21-central-vision-control-design.md`

## Global Constraints

- Bind only to `127.0.0.1`, default control port `8768`.
- Permit only `status`, `start`, `stop`, and `restart`; never accept process arguments.
- Keep `VisionProcessBridge` as the sole vision-event producer.
- Use shared `runtime.env`; board defaults are `XINGBAO_VISION_VISUALIZE=0` and `XINGBAO_VISION_ALWAYS_ON_TOP=0`.
- Preserve native Wayland operation without X11 assumptions.

### Task 1: Controller and loopback NDJSON server

**Files:** Create `core/vision_control_server.py`; test `tests/test_vision_control_server.py`.

**Interfaces:** `VisionRuntimeController(config_factory, bridge_factory).handle(action) -> dict`; `VisionControlServer(controller, host, port).start()/close()`.

- [ ] Write failing tests for: start creates one bridge, stop calls `close()` and leaves it stopped, restart closes the old bridge and calls `config_factory` again, and status returns the active bridge status.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_vision_control_server.py -k controller`; expect an import failure for the new controller.
- [ ] Implement `VisionRuntimeController` with one `threading.RLock`; whitelist `status/start/stop/restart`, discard a bridge only after `close()`, and create fresh config only during start/restart.
- [ ] Write failing NDJSON tests that send `{"type":"vision_runtime_control","action":"status"}`, reject `shell` actions and `speech_request` types, and reject a non-loopback host constructor argument.
- [ ] Implement a `socketserver.ThreadingTCPServer` with `allow_reuse_address`, 4 KiB maximum line length, one JSON response per request, and `127.0.0.1` binding only.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_vision_control_server.py`; expect PASS.
- [ ] Commit only `core/vision_control_server.py` and `tests/test_vision_control_server.py` with message `feat: add central vision control server`.

### Task 2: Center-service ownership and lifecycle

**Files:** Modify `main.py` around the existing `args.vision_runtime` branch; test `tests/test_main.py`.

**Interfaces:** The controller bridge factory constructs `VisionProcessBridge(handle_game_event_message, config=config, log_handler=write_vision_log, restart_delay_seconds=...)`. The server uses `XINGBAO_VISION_CONTROL_PORT`, default `8768`.

- [ ] Write a failing test with fake bridge/server factories showing that `--vision-runtime` starts the controller bridge and a loopback server, and that a server bind error is logged without stopping the running bridge.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_main.py -k vision_control`; expect FAIL.
- [ ] Replace direct bridge construction with controller startup. Register bridge/controller and server cleanup with `atexit`; keep the existing vision event handler and restart delay unchanged.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_main.py -k vision_control`; expect PASS.
- [ ] Commit only `main.py` and affected test file with message `feat: expose production vision runtime control`.

### Task 3: Manual manager becomes a control client

**Files:** Modify `deploy/manage_xingbao_vision_window.sh`; test `tests/test_vision_manager_script.py`; modify `/home/fibo/.config/xingbao/runtime.env` during deployment.

**Interfaces:** Each shell lifecycle action sends `{"type":"vision_runtime_control","action":ACTION}` using `/usr/bin/python3` to `127.0.0.1:${XINGBAO_VISION_CONTROL_PORT:-8768}`.

- [ ] Write failing script contract tests asserting the script contains `vision_runtime_control`, contains neither `multimodal.vision_system.app` nor `--json`, and persists both visualization environment keys.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_vision_manager_script.py`; expect FAIL against the direct launcher.
- [ ] Remove `/proc` matching and direct `setsid` launch. Implement one Python NDJSON client call for start/stop/restart/status. Keep menu options 1–4; option 4 atomically changes both `XINGBAO_VISION_VISUALIZE` and `XINGBAO_VISION_ALWAYS_ON_TOP`, then tells the user to restart.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_vision_manager_script.py`; expect PASS.
- [ ] Commit only the script and test file with message `fix: make vision manager control the central runtime`.

### Task 4: Headless deployment and recovery

**Files:** Modify runtime state and `/home/fibo/.config/xingbao/runtime.env`; verify unified logs.

- [ ] Atomically set `XINGBAO_VISION_VISUALIZE=0` and `XINGBAO_VISION_ALWAYS_ON_TOP=0` in `runtime.env`.
- [ ] Identify only processes with project working directory `/home/fibo/xingbao_companion_project` and command `multimodal.vision_system.app`; stop those exact PIDs before restarting the unified service.
- [ ] Restart via `env XINGBAO_SKIP_BOOT_UI_PREP=1 XINGBAO_REPLACE_LEGACY_RUNTIME=1 /bin/bash deploy/xingbao-unified-autostart.sh`.
- [ ] Verify ports 8765, 8766, and 8768; exactly one project vision process; command includes `--headless` and lacks `--always-on-top`; `status`, `restart`, `status` produce a changed running PID.
- [ ] Run `PYTHONPATH=. pytest -q tests/test_vision_control_server.py tests/test_vision_manager_script.py tests/test_vision_runtime.py tests/test_main.py`; document any unrelated pre-existing failures.
- [ ] Commit documentation only if the worktree allows a scoped commit: `docs/superpowers/specs/2026-08-21-central-vision-control-design.md` and this plan.
