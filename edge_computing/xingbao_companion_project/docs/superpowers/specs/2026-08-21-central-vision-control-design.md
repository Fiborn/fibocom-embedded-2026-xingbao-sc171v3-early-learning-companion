# Central Vision Control Design

## Goal

Make the production center service the only owner of the monocular vision
runtime, while allowing the visual-service management script to start, stop,
restart, and inspect that same runtime without creating a second process.

## Constraints

- The board uses native Wayland; vision must run headlessly when visualization
  is disabled and must not depend on X11 behavior.
- Vision events must continue to flow through `VisionProcessBridge` into the
  center service.
- The control interface listens only on `127.0.0.1` and accepts only a small,
  fixed command whitelist.
- `~/.config/xingbao/runtime.env` is the shared source of visualization
  configuration for cron startup, total-service startup, and manual control.
- The deployed default for this board is no vision window:
  `XINGBAO_VISION_VISUALIZE=0` and `XINGBAO_VISION_ALWAYS_ON_TOP=0`.

## Architecture

`main.py` constructs one `VisionRuntimeController` around the existing
`VisionProcessBridge`. The controller serializes `status`, `start`, `stop`,
and `restart` under one lock. Start and restart build a fresh
`VisionRuntimeConfig` from the current process environment; stop calls
`VisionProcessBridge.close()` and records the intentionally stopped state so
the bridge's ordinary failure-restart behavior cannot recreate it.

A new loopback NDJSON `VisionControlServer` exposes those four operations on a
dedicated configurable port (default `8768`). Each request has the form:

```json
{"type":"vision_runtime_control","action":"restart"}
```

Responses are single-line JSON with `ok`, `action`, and a redacted runtime
status. Unknown message types, unknown actions, malformed JSON, oversized
lines, and non-loopback binding requests are rejected. No request can inject a
command, path, environment variable, or model argument.

The control server starts alongside the existing center game-speech service
when `--vision-runtime` is enabled, and it closes with the center process.
Vision event delivery remains unchanged because the controller always starts
the same bridge with `handle_game_event_message`.

## Manual Script

`deploy/manage_xingbao_vision_window.sh` becomes a loopback client instead of
a direct launcher. Its Start, Stop, Restart, and Status operations send the
whitelisted IPC action to the center service. Its visualization toggle edits
only `XINGBAO_VISION_VISUALIZE` and `XINGBAO_VISION_ALWAYS_ON_TOP` in
`runtime.env`; a subsequent restart command applies the new shared settings.
The script no longer identifies processes by `--json`, starts Python directly,
or embeds model, cadence, hand, hydration, or event-forwarding arguments.

## Deployment and Recovery

Before enabling the controller, set both visualization environment variables
to `0`. Stop every verified project-local
`multimodal.vision_system.app` process, including known orphan processes, then
restart the center service once. The controller must then report exactly one
headless vision process whose command contains `--headless` and does not
contain `--always-on-top`.

## Verification

- Unit tests cover controller start/stop/restart/status behavior and fresh
  configuration loading.
- Server tests cover valid loopback NDJSON requests and rejection of malformed
  or unsupported commands.
- Script tests verify no legacy direct launch arguments remain and the script
  targets the control endpoint.
- Board verification checks one running headless vision child, no duplicate
  project vision processes, central port `8766`, control port `8768`, and
  preserved vision event delivery.
