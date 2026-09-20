# 星宝触控 UI 场景动画 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 native Wayland 触控 UI 播放 24 个星宝场景 GIF，并由 KWS、LLM、天气、夜间和空闲视觉情绪驱动。

**Architecture:** 中央服务将每轮 LLM 的受限场景标记解析为 `0..24`，通过 8765 UI 桥发送。触控 UI 在 Pygame 主线程缓存并播放 GIF，资源和命令失效时显示现有默认星宝。

**Tech Stack:** Python 3.8、Pygame/SDL Wayland、Pillow GIF decoder、NDJSON、pytest。

**Spec:** `docs/superpowers/specs/2026-08-21-touch-ui-scene-animation-design.md`

## Global Constraints

- 生产触控 UI 是 native Wayland，不能引入 X11 依赖。
- Pygame 资源创建、帧推进、绘制都只能在 UI 主线程执行。
- 场景编号仅可为 `0..24`；任意资源或解析错误回退默认静态形象。
- 对话期间直接丢弃视觉情绪的语音、字幕和 GIF 请求。

---

### Task 1: 场景目录与 LLM 场景标记

**Files:**
- Create: `core/scene_animation.py`
- Modify: `app.py`
- Test: `tests/test_scene_animation.py`

**Interfaces:** `SCENE_CATALOG`、`extract_scene_marker(text) -> (clean_text, scene_id)`、`SceneTurnSelector.select(user_text, response_text) -> (clean_text, scene_id)`。

- [ ] **Step 1: Write the failing test**

```python
def test_marker_is_hidden_and_duplicate_turn_keeps_previous_scene():
    selector = SceneTurnSelector()
    assert selector.select("我想吃面条", "好呀[[XINGBAO_SCENE:12]]") == ("好呀", 12)
    assert selector.select("我想吃面条", "继续[[XINGBAO_SCENE:3]]") == ("继续", 12)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_scene_animation.py -v`

Expected: FAIL because `core.scene_animation` does not exist.

- [ ] **Step 3: Implement the minimal protocol**

Create all 24 numbered names, strict `[[XINGBAO_SCENE:n]]` parsing, invalid/duplicate/missing marker fallback to `0`, and duplicate-input inheritance. Add the complete catalog plus rain=`19`, snow=`20` guidance to `XingbaoApp._build_turn_system_prompt()`. Strip marker before all TTS, subtitles, history and `VoiceTurnResult` uses.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_scene_animation.py -v`

Expected: PASS, including all 24 catalog entries and invalid marker fallback.

- [ ] **Step 5: Commit**

```bash
git add core/scene_animation.py app.py tests/test_scene_animation.py
git commit -m "feat: add LLM scene selection protocol"
```

### Task 2: 8765 场景命令与 GIF 播放器

**Files:**
- Create: `components/touch_ui/src/scene_animation.py`
- Create: `components/touch_ui/assets/scenes/` (24 GIF files)
- Modify: `core/board_ui_client.py`
- Modify: `tools/board_phase1_ui.py`
- Modify: `components/touch_ui/desktop.py`
- Test: `tests/test_touch_ui_scene_animation.py`

**Interfaces:** `BoardUIClient.send_xingbao_scene(scene_id, source)` 与 `SceneAnimator.set_scene(scene_id)`, `.clear_scene()`, `.draw(surface, rect, now_ms)`。

- [ ] **Step 1: Write the failing test**

```python
def test_missing_resource_keeps_default_scene(tmp_path):
    animator = SceneAnimator(tmp_path)
    assert animator.set_scene(12) is False
    assert animator.active_scene_id == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest tests/test_touch_ui_scene_animation.py -v`

Expected: FAIL because no scene animator exists.

- [ ] **Step 3: Implement bridge and renderer**

Validate `0..24` in the client; dispatch `xingbao_scene` through `tools/board_phase1_ui.py` onto the bound desktop UI thread. Copy and validate the 24 source GIFs. Decode/cache frame durations lazily, loop frames, use existing portrait rectangle, and retain current static draw if no active frame or decoder fails.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest tests/test_touch_ui_scene_animation.py -v`

Expected: PASS for payload validation, missing-resource fallback and duration-based frame advance.

- [ ] **Step 5: Commit**

```bash
git add components/touch_ui core/board_ui_client.py tools/board_phase1_ui.py tests/test_touch_ui_scene_animation.py
git commit -m "feat: render Xingbao scene GIFs"
```

### Task 3: KWS、LLM、天气与夜间状态

**Files:**
- Modify: `app.py`
- Modify: `core/scene_animation.py`
- Test: `tests/test_scene_animation.py`

**Interfaces:** `ScenePriorityController.on_wake()`, `.on_llm_scene(scene_id)`, `.on_session_end()`, `.poll_idle(now)`。

- [ ] **Step 1: Write the failing test**

```python
def test_night_returns_after_ten_idle_minutes():
    state = ScenePriorityController()
    state.on_session_end(at_2330)
    assert state.poll_idle(at_2330_plus_9m59s) == 0
    assert state.poll_idle(at_2330_plus_10m) == 22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_scene_animation.py -v`

Expected: FAIL because the controller does not exist.

- [ ] **Step 3: Implement lifecycle calls**

At KWS detection send scene `1` before acknowledgement. After every final LLM reply send selected non-zero scene; explicit rainy/snowy weather result wins with `19`/`20`. At session end start a 10-minute guard; when local time is at least 23:00 and no later wake occurred, send `22`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_scene_animation.py -v`

Expected: PASS for KWS override, weather mapping and night timing.

- [ ] **Step 5: Commit**

```bash
git add app.py core/scene_animation.py tests/test_scene_animation.py
git commit -m "feat: orchestrate voice scene animations"
```

### Task 4: 视觉情绪隔离与空闲映射

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py`

**Interfaces:** `scene_for_idle_vision_emotion(emotion)` maps happiness=`2`, sadness/anger=`3`; active dialogue returns a dropped event before all side effects.

- [ ] **Step 1: Write the failing test**

```python
def test_idle_anger_maps_to_heart_scene():
    assert scene_for_idle_vision_emotion("anger") == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_main.py -k emotion -v`

Expected: FAIL because the scene mapping function is missing.

- [ ] **Step 3: Implement the event gate**

At `child_emotion_detected`, check `app._conversation_audio_active()` before coordinator, speech, subtitle and UI calls. Return immediately when active; when idle issue the mapped best-effort scene command and retain existing approved idle emotion behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_main.py -k emotion -v`

Expected: PASS: no active-dialogue effect; idle happiness uses `2`; sadness and anger use `3`.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: gate vision emotion scenes during dialogue"
```

### Task 5: Wayland board verification

**Files:**
- Test: `tests/test_scene_animation.py`, `tests/test_touch_ui_scene_animation.py`, `tests/test_main.py`

- [ ] **Step 1: Validate resources and focused suite**

Run: `find components/touch_ui/assets/scenes -maxdepth 1 -name '*.gif' -printf '%f\\n' | sort`

Expected: exactly 24 numbered files.

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest tests/test_scene_animation.py tests/test_touch_ui_scene_animation.py -v`

Expected: PASS.

- [ ] **Step 2: Compile production paths**

Run: `/usr/bin/python3 -m py_compile app.py main.py core/scene_animation.py core/board_ui_client.py components/touch_ui/desktop.py components/touch_ui/src/scene_animation.py tools/board_phase1_ui.py`

Expected: exit code 0.

- [ ] **Step 3: Restart and probe native Wayland services**

Run: `bash deploy/xingbao_service_manager.sh restart`

Check: `pgrep -af 'main.py|board_phase1_ui.py|vision_system.app'` and `/home/fibo/.local/state/xingbao-unified/autostart.log`.

Expected: UI, central and vision processes are healthy; send bridge scene `1`, `12`, then `0` and restore the appropriate idle scene.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-08-21-touch-ui-scene-animation.md
git commit -m "docs: add scene animation implementation plan"
```

