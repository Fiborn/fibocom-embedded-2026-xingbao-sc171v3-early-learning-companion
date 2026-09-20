# Camera Snapshot UI Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the exact camera frame inspected by Qwen as a centered rounded preview on the Wayland touch UI, then remove it when the recognition answer begins speaking.

**Architecture:** `DashScopeLLMClient` emits an in-memory snapshot-ready event immediately after its one successful capture. `XingbaoApp` turns that event into a typed voice event; `main.py` forwards it through `BoardUIClient` to the existing NDJSON desktop bridge. The bridge validates and decodes one bounded JPEG data URI on the Pygame UI thread; `DesktopApp` owns drawing and clearing the transient overlay.

**Tech Stack:** Python 3.8, DashScope-compatible Qwen, OpenCV capture, JPEG data URI, NDJSON over localhost, Pygame/SDL on native Wayland, pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-camera-snapshot-ui-overlay-design.md`

## Global Constraints

- Production touch UI is native Wayland; do not alter fullscreen, focus, geometry, or rely on X11 behavior.
- Use the already captured JPEG data URI; never make a second camera request.
- Do not write preview images to disk or print Base64/image payloads in logs.
- Validate data URI prefix, decoded byte size, dimensions and JPEG decode before changing UI state.
- Bottom camera-tool status subtitle is exactly `让我看一看`.
- Preview maximum is 62% of display width and 58% of display height; it must preserve aspect ratio and leave the bottom subtitle area visible.
- Clear the preview before the first recognition-result TTS segment is queued, on error/session end, and before a later camera preview replaces it.

---

### Task 1: Emit and forward a bounded camera snapshot event

**Files:**
- Modify: `intelligence/llm_client.py: camera tool-call branch and _emit_realtime_query_started`
- Modify: `app.py: _generate_and_speak_realtime_tts, _generate_and_speak_streaming, _emit_tts_segment_queued`
- Modify: `core/voice_events.py: VOICE_EVENT_TYPES`
- Modify: `main.py: build_voice_event_handler`
- Modify: `core/board_ui_client.py: BoardUIClient.send_ui_command`
- Test: `tests/test_dashscope_clients.py`
- Test: `tests/test_app.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces `camera_snapshot_ready` agent event: `{"type": "camera_snapshot_ready", "data_uri": str, "width": int, "height": int}` after successful `capture_current_camera_frame()` and before the image is appended to Qwen messages.
- Produces `camera_snapshot_clear` voice event with no image payload.
- Extends direct UI payload with `camera_snapshot: {"action": "show", "data_uri": str, "width": int, "height": int}` or `{"action": "clear"}`.
- `main.py` forwards the snapshot event through `BoardUIClient.send_ui_command(..., command={"name": "camera_snapshot", ...})` and does not log the data URI.

- [ ] **Step 1: Write failing LLM-event tests**

```python
def test_camera_tool_emits_same_snapshot_for_ui_and_qwen(monkeypatch):
    snapshot = CameraSnapshot("data:image/jpeg;base64,AA==", 320, 240)
    events = []
    client.on_agent_event = events.append
    monkeypatch.setattr(llm_module, "capture_current_camera_frame", lambda: snapshot)

    client.generate_reply("这是什么？", "系统提示")

    preview = next(event for event in events if event["type"] == "camera_snapshot_ready")
    assert preview["data_uri"] == snapshot.data_uri
    assert preview["width"] == 320
    assert preview["height"] == 240
    assert network.requests[1]["payload"]["messages"][-1]["content"][1]["image_url"]["url"] == snapshot.data_uri
```

- [ ] **Step 2: Run the LLM test and verify it fails**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_dashscope_clients.py::test_camera_tool_emits_same_snapshot_for_ui_and_qwen`

Expected: FAIL because no `camera_snapshot_ready` event is emitted.

- [ ] **Step 3: Emit the event and change camera subtitle copy**

```python
self._emit_agent_event({
    "type": "camera_snapshot_ready",
    "data_uri": camera_snapshot.data_uri,
    "width": camera_snapshot.width,
    "height": camera_snapshot.height,
})

# Camera status event
"subtitle": "让我看一看",
```

Emit only after successful capture and before appending the visual Qwen message. Do not print `data_uri`.

- [ ] **Step 4: Write failing app/main forwarding and clear-order tests**

```python
def test_camera_snapshot_event_forwards_a_show_command_to_ui():
    handler(VoiceEvent("camera_snapshot_ready", {
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
    }))
    assert client.calls[-1]["command"] == {
        "name": "camera_snapshot", "action": "show",
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
    }

def test_first_result_tts_queue_clears_camera_preview_before_audio():
    app._emit_tts_segment_queued(pipeline, "这是水杯。", 1)
    assert [event.type for event in events][-2:] == [
        "camera_snapshot_clear", "tts_segment_queued",
    ]
```

- [ ] **Step 5: Run forwarding/clear tests and verify they fail**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -c 'import sys,types,pytest; sys.modules["audioop"]=types.ModuleType("audioop"); raise SystemExit(pytest.main(["-q", "tests/test_app.py::test_first_result_tts_queue_clears_camera_preview_before_audio", "tests/test_main.py::test_camera_snapshot_event_forwards_a_show_command_to_ui"]))'`

Expected: FAIL because the new voice events and UI command are not handled.

- [ ] **Step 6: Implement voice-event bridging and one-shot clear state**

Add `camera_snapshot_ready` and `camera_snapshot_clear` to `VOICE_EVENT_TYPES`. Keep an app-level boolean indicating an active camera preview for the current response. When a snapshot-ready event arrives, emit the corresponding pipeline event; before the first non-empty recognition-result `tts_segment_queued`, emit `camera_snapshot_clear` and reset the boolean. Also clear on camera error and session termination. In `main.py`, send the typed show/clear command with an empty `screen_text`, preserving dialogue subtitle priority.

- [ ] **Step 7: Run Task 1 tests and commit**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -c 'import sys,types,pytest; sys.modules["audioop"]=types.ModuleType("audioop"); raise SystemExit(pytest.main(["-q", "tests/test_dashscope_clients.py", "tests/test_app.py::test_first_result_tts_queue_clears_camera_preview_before_audio", "tests/test_main.py::test_camera_snapshot_event_forwards_a_show_command_to_ui"]))'`

Expected: PASS.

```bash
git add intelligence/llm_client.py app.py core/voice_events.py main.py core/board_ui_client.py \
  tests/test_dashscope_clients.py tests/test_app.py tests/test_main.py
git commit -m "feat: forward camera snapshot previews to UI"
```

### Task 2: Add validated Wayland UI overlay state and rendering

**Files:**
- Modify: `components/touch_ui/desktop.py: DesktopApp.__init__, DesktopApp.render`
- Modify: `tools/board_phase1_ui.py: dispatch`
- Test: `tests/test_touch_ui_scene_animation.py` or new `tests/test_camera_snapshot_overlay.py`
- Test: `tests/test_board_ui_client.py`

**Interfaces:**
- `DesktopApp.set_camera_snapshot(data_uri: str, width: int, height: int) -> bool` validates/decodes and sets the transient preview surface.
- `DesktopApp.clear_camera_snapshot() -> bool` removes it idempotently.
- `DesktopApp.draw_camera_snapshot_overlay()` renders the snapshot after `draw_xingbao_animation()` and before bottom notices.
- Bridge payload accepts only `camera_snapshot.action` values `show` and `clear`.

- [ ] **Step 1: Write failing UI-state tests**

```python
def test_desktop_camera_snapshot_keeps_aspect_ratio_and_respects_subtitle_area(fake_desktop):
    assert fake_desktop.set_camera_snapshot(TEST_JPEG_URI, 640, 480) is True
    rect = fake_desktop.camera_snapshot_rect()
    assert rect.width <= int(fake_desktop.screen.get_width() * 0.62)
    assert rect.height <= int(fake_desktop.screen.get_height() * 0.58)
    assert rect.bottom < int(fake_desktop.screen.get_height() * 0.88)
    assert abs(rect.width / rect.height - 640 / 480) < 0.02

def test_invalid_camera_snapshot_does_not_replace_existing_overlay(fake_desktop):
    fake_desktop.set_camera_snapshot(TEST_JPEG_URI, 640, 480)
    previous = fake_desktop.camera_snapshot_surface
    assert fake_desktop.set_camera_snapshot("data:text/plain;base64,QQ==", 1, 1) is False
    assert fake_desktop.camera_snapshot_surface is previous
```

- [ ] **Step 2: Run UI-state tests and verify they fail**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_camera_snapshot_overlay.py`

Expected: FAIL because `DesktopApp` has no snapshot API.

- [ ] **Step 3: Implement desktop-owned overlay state**

Initialize `camera_snapshot_surface = None`, `camera_snapshot_size = None` and a decoded-byte cap of 1 MiB. In `set_camera_snapshot`, accept only `data:image/jpeg;base64,`, reject invalid base64/oversize inputs, load the bytes via `pygame.image.load(io.BytesIO(...)).convert()`, and keep prior state unchanged on failure. In `draw_camera_snapshot_overlay`, calculate `scale = min(0.62*w/source_w, 0.58*h/source_h)`, center a rounded dark panel above the subtitle safe area, clip the image to a rounded surface, and draw a subtle border. `clear_camera_snapshot` sets both fields to `None`.

- [ ] **Step 4: Write failing bridge-dispatch tests**

```python
def test_camera_snapshot_show_command_runs_on_ui_thread(board_runtime):
    response = dispatch({"payload": {"camera_snapshot": {
        "action": "show", "data_uri": TEST_JPEG_URI, "width": 640, "height": 480,
    }}})
    assert response["results"][0]["action"] == "camera_snapshot_show"
    assert board_runtime.desktop.received_snapshot[1:] == (640, 480)

def test_camera_snapshot_clear_command_is_idempotent(board_runtime):
    response = dispatch({"payload": {"camera_snapshot": {"action": "clear"}}})
    assert response["ok"] is True
```

- [ ] **Step 5: Run bridge tests and verify they fail**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_board_ui_client.py::test_camera_snapshot_show_command_runs_on_ui_thread tests/test_board_ui_client.py::test_camera_snapshot_clear_command_is_idempotent`

Expected: FAIL because `camera_snapshot` is not dispatched.

- [ ] **Step 6: Implement bridge validation and dispatch**

Before normal UI-command forwarding, read `payload["camera_snapshot"]`. For `show`, enforce integer positive dimensions and pass the data URI unchanged only to `desktop.set_camera_snapshot` through `board_runtime.submit`; return action `camera_snapshot_show` and never echo the URI. For `clear`, call `desktop.clear_camera_snapshot` through the same UI-thread submission and return action `camera_snapshot_clear`. Reject other actions or malformed payloads with `ok: false` without changing the overlay.

- [ ] **Step 7: Run Task 2 tests and commit**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_camera_snapshot_overlay.py tests/test_board_ui_client.py`

Expected: PASS.

```bash
git add components/touch_ui/desktop.py tools/board_phase1_ui.py \
  tests/test_camera_snapshot_overlay.py tests/test_board_ui_client.py
git commit -m "feat: render camera snapshot overlay on touch UI"
```

### Task 3: Verify end-to-end event ordering and deploy safely

**Files:**
- Modify: only files required by test corrections from Tasks 1–2
- Test: `tests/test_dashscope_clients.py`
- Test: `tests/test_app.py`
- Test: `tests/test_main.py`
- Test: `tests/test_camera_snapshot_overlay.py`

**Interfaces:**
- Consumes the Task 1 snapshot show/clear events and Task 2 desktop APIs.
- Produces a live central process and native Wayland UI that accept snapshot overlay commands.

- [ ] **Step 1: Write the end-to-end ordering test**

```python
def test_camera_preview_shows_before_prompt_and_clears_before_result_tts(events):
    types = [event.type for event in events]
    assert types.index("camera_snapshot_ready") < types.index("realtime_query_started")
    assert types.index("camera_snapshot_clear") < types.index("tts_segment_queued")
```

- [ ] **Step 2: Run it and verify it fails before ordering implementation is complete**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -c 'import sys,types,pytest; sys.modules["audioop"]=types.ModuleType("audioop"); raise SystemExit(pytest.main(["-q", "tests/test_app.py::test_camera_preview_shows_before_prompt_and_clears_before_result_tts"]))'`

Expected: FAIL if the event order is wrong or a clear event is missing.

- [ ] **Step 3: Adjust only event order/state handling necessary to pass**

Keep snapshot-ready emission immediately after capture. Ensure clearing happens at the first answer TTS queue boundary rather than when the LLM tool decision or image upload starts.

- [ ] **Step 4: Run focused regression and static checks**

Run:

```bash
PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -c 'import sys,types,pytest; sys.modules["audioop"]=types.ModuleType("audioop"); raise SystemExit(pytest.main(["-q", "tests/test_dashscope_clients.py", "tests/test_camera_inspection.py", "tests/test_app.py", "tests/test_main.py", "tests/test_camera_snapshot_overlay.py", "tests/test_board_ui_client.py"]))'
/usr/bin/python3 -m py_compile app.py main.py intelligence/llm_client.py core/board_ui_client.py tools/board_phase1_ui.py components/touch_ui/desktop.py
git diff --check
```

Expected: focused tests pass, compilation succeeds, and the diff is whitespace-clean. If unrelated pre-existing failures block the broad selected suite, record their exact test names and run the feature-specific subset separately.

- [ ] **Step 5: Restart and health-check using the canonical Wayland route**

Run:

```bash
env XINGBAO_SKIP_BOOT_UI_PREP=1 XINGBAO_REPLACE_LEGACY_RUNTIME=1 \
  bash deploy/xingbao-unified-autostart.sh
```

Then verify the central PID from `/home/fibo/.local/state/xingbao-unified/central.pid` is alive, port `8766` is open, and `/home/fibo/.local/state/xingbao-unified/autostart.log` records a ready central service. Do not infer UI behavior from X11.

- [ ] **Step 6: Commit final verification fixes**

```bash
git add app.py main.py intelligence/llm_client.py core/voice_events.py core/board_ui_client.py \
  components/touch_ui/desktop.py tools/board_phase1_ui.py tests
git commit -m "test: verify camera snapshot overlay flow"
```
