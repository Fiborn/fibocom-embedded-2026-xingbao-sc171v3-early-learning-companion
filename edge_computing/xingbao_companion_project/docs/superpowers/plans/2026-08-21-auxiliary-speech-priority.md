# Auxiliary Speech Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure an active child conversation always owns TTS and ASR: external speech is discarded, except for one deduplicated drink-water reminder that may play after the conversation ends unless drinking resets its timer first.

**Architecture:** `XingbaoApp` already owns the wake-chat state and all central external speech routes. Add a thread-safe auxiliary-speech gate there. The wake loop activates it before the wake acknowledgement and clears it only after the session ends; external expression outputs and touch/read-aloud speech consult it. Screen, LED, memory, and arm outputs remain independent of the speech decision.

**Tech Stack:** Python 3.8, `threading.Event`, pytest.

**Spec:** User request in this conversation, 2026-08-21.

## Global Constraints

- Native board UI is Wayland; this change is audio-state-only and must not change window behavior.
- During a wake-chat conversation (TTS, listening, ASR, or follow-up wait), every external speech request is dropped immediately. External speech is admitted only after the conversation is paused/ended and its audio path is idle.
- `drink_water_reminder_due` is the sole exception: retain only the newest reminder and play it once when the conversation ends.
- A fresh bottle/face-overlap hydration reset invalidates and clears a queued drink reminder immediately.
- Never queue or replay touch read-aloud, game prompts, emotion, posture, or other vision reminders.
- Keep non-audio effects (screen text, LED, action, memory) active.

---

### Task 1: Cover the priority contract

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: `XingbaoApp.apply_expression_output`, `XingbaoApp.speak_game_text`.
- Produces: tests proving external speech is suppressed during a conversation and drink reminders are retained once.

- [ ] **Step 1: Write the failing tests**

```python
def test_external_game_speech_is_dropped_during_conversation(monkeypatch):
    app = XingbaoApp()
    app._voice_chat_session_active.set()
    spoken = []
    monkeypatch.setattr(app, "_speak_with_demo_cache", lambda *args, **kwargs: spoken.append(args[0]))

    assert app.speak_game_text("点一下这里", source="xingbao_desktop_read_aloud") is None
    assert spoken == []


def test_drink_reminder_is_played_once_after_conversation(monkeypatch):
    app = XingbaoApp()
    app._voice_chat_session_active.set()
    spoken = []
    monkeypatch.setattr(app, "_speak_with_demo_cache", lambda text, **kwargs: spoken.append(text))

    app.apply_expression_output(drink_output, no_tts=False)
    app.apply_expression_output(drink_output, no_tts=False)
    app._voice_chat_session_active.clear()
    app._drain_pending_drink_reminder()

    assert spoken == ["要不要喝一小口水？喝完我们继续。"]


def test_hydration_reset_clears_queued_drink_reminder(monkeypatch):
    app = XingbaoApp()
    app._voice_chat_session_active.set()
    app.apply_expression_output(drink_output, no_tts=False)
    app.clear_pending_drink_reminder()
    app._voice_chat_session_active.clear()
    app._drain_pending_drink_reminder()

    assert spoken == []
```

- [ ] **Step 2: Run the focused tests and verify they fail because the priority gate is absent**

Run: `pytest tests/test_app.py -k 'dropped_during_conversation or drink_reminder_is_played_once' -v`

Expected: FAIL because both existing routes invoke the TTS player immediately.

- [ ] **Step 3: Implement the smallest centralized gate**

```python
def _conversation_audio_active(self) -> bool:
    return self._voice_chat_session_active.is_set()

def _queue_drink_reminder(...):
    # replace, never append

def _drain_pending_drink_reminder(self) -> None:
    # take exactly one entry only while conversation is inactive

def clear_pending_drink_reminder(self) -> bool:
    # discard the pending reminder after a confirmed hydration reset
```

Guard `apply_expression_output` and `speak_game_text` before they allocate or start external audio. Allow only `ExpressionOutput.intent == "drink_reminder"` to be retained.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest tests/test_app.py -k 'dropped_during_conversation or drink_reminder_is_played_once' -v`

Expected: PASS.

### Task 2: Preempt running auxiliary playback and drain at session end

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: existing read-aloud/game interrupt tokens and `_voice_chat_session_active`.
- Produces: an active dialogue cancels already-playing auxiliary audio; one queued drink reminder drains after a completed session.

- [ ] **Step 1: Write failing tests**

```python
def test_conversation_activation_interrupts_current_external_speech():
    app = XingbaoApp()
    token = app._begin_game_speech_turn(interrupt=False)

    app._begin_conversation_audio_priority()

    assert token.is_set()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/test_app.py -k conversation_activation_interrupts -v`

Expected: FAIL because conversation activation currently only sets an event.

- [ ] **Step 3: Implement and wire the lifecycle**

```python
def _begin_conversation_audio_priority(self) -> None:
    self._voice_chat_session_active.set()
    self._interrupt_external_speech()

def _finish_conversation_audio_priority(self) -> None:
    self._voice_chat_session_active.clear()
    self._drain_pending_drink_reminder()
```

Use these helpers before the wake acknowledgement and at every normal wake-chat session completion. Make cancellation best-effort through the existing interrupt events.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pytest tests/test_app.py -k conversation_activation_interrupts -v`

Expected: PASS.

### Task 3: Propagate a hydration-reset event

**Files:**
- Modify: `multimodal/vision_adapter.py`
- Modify: `multimodal/vision_runtime.py`
- Modify: `main.py`
- Modify: `tests/test_vision_adapter.py`

**Interfaces:**
- Consumes: each frame's `drink_reminder.overlap_now` result.
- Produces: one `vision_state` event with `payload.state == "drink_reminder_reset"` for an overlap transition; `main.py` consumes it by calling `app.clear_pending_drink_reminder()` and does not generate speech.

- [ ] **Step 1: Write a failing adapter test**

```python
def test_adapter_emits_one_hydration_reset_when_bottle_overlaps_face():
    adapter = VisionEventAdapter()

    assert adapter.update({"drink_reminder": {"overlap_now": False}}) == []
    reset_events = adapter.update({"drink_reminder": {"overlap_now": True}})
    assert [event["payload"]["state"] for event in reset_events] == ["drink_reminder_reset"]
    assert adapter.update({"drink_reminder": {"overlap_now": True}}) == []
```

- [ ] **Step 2: Run it and verify it fails**

Run: `pytest tests/test_vision_adapter.py -k hydration_reset -v`

Expected: FAIL because the adapter currently emits no hydration-reset state.

- [ ] **Step 3: Add the edge event and consume it before expression routing**

Add an adapter field that remembers the previous overlap state. Emit `drink_reminder_reset` only on `False -> True`. Allow that state through `VisionProcessBridge`; in `handle_game_event_message`, log the reset, call `app.clear_pending_drink_reminder()`, and return before the event reaches normal expression/TTS routing. Do not let the posture reminder's legacy realtime-playback preemption run while conversation priority is active.

- [ ] **Step 4: Run the focused adapter and app tests**

Run: `pytest tests/test_vision_adapter.py -k hydration_reset -v && pytest tests/test_app.py -k 'drink_reminder' -v`

Expected: PASS.

### Task 4: Regression verification

**Files:**
- Test: `tests/test_app.py`

- [ ] **Step 1: Run focused application tests**

Run: `pytest tests/test_app.py -v`

Expected: PASS.

- [ ] **Step 2: Compile edited production code**

Run: `python3 -m py_compile app.py`

Expected: exit 0.

- [ ] **Step 3: Review the final diff**

Run: `git diff -- app.py tests/test_app.py docs/superpowers/plans/2026-08-21-auxiliary-speech-priority.md`

Expected: only the centralized gate, its tests, and this plan are present.
