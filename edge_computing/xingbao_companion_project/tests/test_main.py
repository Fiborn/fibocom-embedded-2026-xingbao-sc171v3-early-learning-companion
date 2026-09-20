from __future__ import annotations

from pathlib import Path

from core.voice_events import VoiceEvent
from main import (
    BOARD_APLAY_OUTPUT_DEVICE,
    arm_action_for_touch_event,
    build_voice_event_handler,
    format_voice_event,
    is_posture_vision_event,
    main,
    start_managed_vision_runtime,
    vision_emotion_memory_update,
)


def test_board_start_demo_enables_verified_low_latency_voice_path() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "deploy" / "board_start_demo.sh"
    ).read_text(encoding="utf-8")

    for flag in (
        "--realtime-tts",
        "--streaming-asr",
        "--low-latency-voice",
    ):
        assert flag in script


def test_touch_events_map_only_to_reviewed_high_level_arm_actions() -> None:
    assert arm_action_for_touch_event("answer_correct") == "nod"
    assert arm_action_for_touch_event("task_completed") == "nod"
    assert arm_action_for_touch_event("game_started") == "nod"
    assert arm_action_for_touch_event("drawing_started") == "nod"
    assert arm_action_for_touch_event("toolbox_result_saved") == "nod"
    assert arm_action_for_touch_event("touch_shake_head") == "shake_head"
    assert arm_action_for_touch_event("drawing_completed") == "bow"
    assert arm_action_for_touch_event("artwork_completed") == "bow"
    assert arm_action_for_touch_event("game_completed") == ""
    assert arm_action_for_touch_event("challenge_completed") == ""
    assert arm_action_for_touch_event("touch_mouth") == "mouth"
    assert arm_action_for_touch_event("touch_bow") == "bow"
    assert arm_action_for_touch_event("high_five_requested") == "high_five"
    assert arm_action_for_touch_event("handshake_requested") == "high_five"
    assert arm_action_for_touch_event("game_state_sync") == ""


def test_touch_high_five_maps_to_reviewed_arm_motion() -> None:
    assert arm_action_for_touch_event("high_five_requested") == "high_five"
    assert arm_action_for_touch_event("touch_high_five") == "high_five"
    assert arm_action_for_touch_event("handshake_requested") == "high_five"


def test_only_distance_vision_states_use_posture_demo_path() -> None:
    assert is_posture_vision_event(
        {"type": "vision_state", "payload": {"state": "face_too_close"}}
    )


def test_managed_vision_runtime_starts_loopback_control_without_stopping_bridge():
    created = []

    class FakeBridge:
        def __init__(self, config):
            self.config = config
            self.closed = False

        def start(self):
            return {"ok": True, "pid": self.config["pid"]}

        def close(self):
            self.closed = True

        def status(self):
            return {"running": not self.closed, "pid": self.config["pid"]}

    class FakeServer:
        def __init__(self, controller, host, port):
            self.controller = controller
            self.host = host
            self.port = port
            self.started = False

        def start(self):
            self.started = True
            return self

        def close(self):
            pass

    result = start_managed_vision_runtime(
        event_handler=lambda _event: None,
        log_handler=lambda _line: None,
        restart_delay_seconds=2.0,
        config_factory=lambda: {"pid": 5150},
        bridge_factory=lambda _handler, config, _logger, _delay: created.append(FakeBridge(config)) or created[-1],
        control_server_factory=FakeServer,
        control_port=9876,
    )

    assert result["startup"] == {"ok": True, "action": "start", "running": True, "pid": 5150}
    assert result["server"].host == "127.0.0.1"
    assert result["server"].port == 9876
    assert result["server"].started is True
    assert created[0].closed is False
    assert not is_posture_vision_event(
        {
            "type": "vision_state",
            "payload": {
                "state": "child_emotion_detected",
                "emotion": "happiness",
            },
        }
    )
    assert not is_posture_vision_event(
        {"type": "vision_state", "payload": {"state": "drink_water_reminder_due"}}
    )


def test_thresholded_vision_emotion_maps_to_safe_recent_mood_memory() -> None:
    assert vision_emotion_memory_update(
        {
            "type": "vision_state",
            "payload": {
                "state": "child_emotion_detected",
                "emotion": "sadness",
                "confidence": 0.87,
            },
        }
    ) == {"recent_mood": "sadness"}
    assert vision_emotion_memory_update(
        {
            "type": "vision_state",
            "payload": {
                "state": "child_emotion_detected",
                "emotion": "sadness",
                "confidence": 0.40,
            },
        }
    ) is None
    assert vision_emotion_memory_update(
        {
            "type": "vision_state",
            "payload": {
                "state": "face_too_close",
                "emotion": "sadness",
                "confidence": 0.95,
            },
        }
    ) is None


def test_format_voice_event_redacts_asr_transcript_but_keeps_its_length() -> None:
    event = VoiceEvent("asr_final", {"text": "你好星宝"})

    assert format_voice_event(event) == '[voice] asr_final {"text_chars": 4}'


def test_format_voice_event_never_logs_camera_snapshot_data_uri() -> None:
    event = VoiceEvent("camera_snapshot_ready", {
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
    })

    assert format_voice_event(event) == '[voice] camera_snapshot_ready {"height": 240, "width": 320}'


def test_streaming_asr_partial_replaces_listening_prompt_on_board_ui() -> None:
    class FakeBoardUI:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def send_ui_command(self, command, **kwargs):
            self.calls.append({"command": command, **kwargs})
            return {"ok": True}

    board_ui = FakeBoardUI()
    handler = build_voice_event_handler(
        show_voice_events=False,
        board_ui_client=board_ui,  # type: ignore[arg-type]
    )

    handler(VoiceEvent("asr_partial", {"text": "你好"}))
    handler(VoiceEvent("asr_partial", {"text": "你好"}))
    handler(VoiceEvent("asr_partial", {"text": "你好星宝"}))

    assert [call["screen_text"] for call in board_ui.calls] == ["你好", "你好星宝"]
    assert all(call["expression"] == "curious" for call in board_ui.calls)


def test_camera_inspection_event_shows_dialogue_subtitle_without_waiting_tts() -> None:
    class FakeBoardUI:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def send_ui_command(self, command, **kwargs):
            self.calls.append({"command": command, **kwargs})
            return {"ok": True}

    board_ui = FakeBoardUI()
    handler = build_voice_event_handler(
        show_voice_events=False,
        board_ui_client=board_ui,  # type: ignore[arg-type]
    )

    handler(
        VoiceEvent(
            "realtime_query_started",
            {
                "tools": ["inspect_current_camera"],
                "subtitle": "让我看一看",
                "voice_prompt": "",
            },
        )
    )

    assert [call["screen_text"] for call in board_ui.calls] == ["让我看一看"]
    assert board_ui.calls[0]["subtitle_priority"] == "dialogue"


def test_camera_snapshot_event_forwards_a_show_command_to_ui() -> None:
    class FakeBoardUI:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def send_ui_command(self, command, **kwargs):
            self.calls.append({"command": command, **kwargs})
            return {"ok": True}

    board_ui = FakeBoardUI()
    handler = build_voice_event_handler(
        show_voice_events=False,
        board_ui_client=board_ui,  # type: ignore[arg-type]
    )

    handler(VoiceEvent("camera_snapshot_ready", {
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
    }))

    assert board_ui.calls[-1]["command"] == {
        "name": "camera_snapshot", "action": "show",
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
        "mirror": True,
    }
    assert board_ui.calls[-1]["screen_text"] == ""


def test_camera_snapshot_event_preserves_unmirrored_web_image() -> None:
    class FakeBoardUI:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def send_ui_command(self, command, **kwargs):
            self.calls.append({"command": command, **kwargs})
            return {"ok": True}

    board_ui = FakeBoardUI()
    handler = build_voice_event_handler(
        show_voice_events=False,
        board_ui_client=board_ui,  # type: ignore[arg-type]
    )

    handler(VoiceEvent("camera_snapshot_ready", {
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
        "mirror": False,
    }))

    assert board_ui.calls[-1]["command"]["mirror"] is False


def test_voice_event_accepts_whitelisted_arm_queue_notice() -> None:
    event = VoiceEvent("arm_action_queued", {"arm_action": "shake_head"})

    assert event.data["arm_action"] == "shake_head"


def test_main_checks_realtime_tts_prerequisites(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--check-realtime-tts"])
    monkeypatch.setattr(
        "main.check_realtime_tts_ready",
        lambda: {
            "status": "ready",
            "model": "cosyvoice-v3-flash",
            "voice": "longanyang",
            "sample_rate": 22050,
        },
    )

    assert main() == 0
    output = capsys.readouterr().out
    assert '"status": "ready"' in output
    assert '"sample_rate": 22050' in output


def test_main_runs_expression_demo(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_expression_demo(self, **kwargs) -> str:
            assert kwargs == {
                "apply_output": False,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
            }
            return "expression demo ok"

    monkeypatch.setattr("sys.argv", ["main.py", "--expression-demo"])
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    assert "expression demo ok" in capsys.readouterr().out


def test_main_handles_expression_event_json(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_expression_event_json(
            self, raw_event_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_event_json == '{"type":"touch_event"}'
            assert kwargs == {
                "apply_output": False,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
            }
            return {"intent": "greet", "tts": True}

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--expression-event-json", '{"type":"touch_event"}'],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "greet"' in output
    assert '"tts": true' in output


def test_main_handles_coordinate_text(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_coordinated_text(self, user_text: str, **kwargs) -> dict[str, object]:
            assert user_text == "星宝我要玩游戏啦"
            assert kwargs == {
                "apply_output": True,
                "launch_tools": False,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
                "board_ui_client": None,
            }
            return {
                "plan": {"intent": {"intent": "open_tool"}},
                "tool_launch_status": "ready",
                "tool_launched": False,
            }

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--coordinate-text", "星宝我要玩游戏啦", "--coordinate-apply"],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"tool_launch_status": "ready"' in output
    assert '"intent": "open_tool"' in output


def test_main_lists_migrated_kids_visual_tools(monkeypatch, capsys) -> None:
    class FakeApp:
        def list_kids_visual_tools(self) -> list[dict[str, object]]:
            return [{"title": "儿童画板", "slug": "draw"}]

    monkeypatch.setattr("sys.argv", ["main.py", "--list-kids-visual-tools"])
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"slug": "draw"' in output


def test_main_launches_migrated_kids_visual_tool(monkeypatch, capsys) -> None:
    class FakeApp:
        def launch_kids_visual_tools(self, tool: str | None = None, *, wait: bool) -> dict[str, object]:
            assert tool == "draw"
            assert wait is True
            return {"ok": True, "returncode": 0}

    monkeypatch.setattr("sys.argv", ["main.py", "--kids-visual-tool", "draw"])
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"ok": true' in output


def test_main_handles_coordinate_event_json(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_coordinated_event_json(
            self, raw_event_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_event_json == '{"type":"game_event"}'
            assert kwargs == {
                "apply_output": True,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
                "board_ui_client": None,
            }
            return {
                "plan": {"intent": {"intent": "game_event"}},
                "trace": [{"type": "voice.speak", "status": "planned"}],
            }

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--coordinate-event-json", '{"type":"game_event"}', "--coordinate-apply"],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "game_event"' in output
    assert '"voice.speak"' in output


def test_main_handles_coordinate_state_json(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_coordinated_state_json(
            self, raw_state_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_state_json == '{"type":"vision_state"}'
            assert kwargs == {
                "apply_output": True,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
                "board_ui_client": None,
            }
            return {
                "plan": {"intent": {"intent": "vision_state"}},
                "trace": [{"type": "voice.speak", "status": "planned"}],
            }

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--coordinate-state-json", '{"type":"vision_state"}', "--coordinate-apply"],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "vision_state"' in output
    assert '"voice.speak"' in output


def test_main_handles_game_command_json(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_game_command_json(
            self, raw_command_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_command_json == '{"type":"game_command"}'
            assert kwargs == {
                "apply_output": True,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
                "board_ui_client": None,
            }
            return {
                "game_response": {"intent": "get_hint"},
                "trace": [{"type": "voice.speak", "status": "planned"}],
            }

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--game-command-json", '{"type":"game_command"}', "--coordinate-apply"],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "get_hint"' in output
    assert '"voice.speak"' in output


def test_main_handles_coordinate_color_block_command(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_coordinated_color_block_command(
            self, command_text: str, **kwargs
        ) -> dict[str, object]:
            assert command_text == "red"
            assert kwargs == {
                "apply_output": True,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
                "board_ui_client": None,
            }
            return {
                "plan": {"expression_output": {"intent": "game_feedback"}},
                "trace": [{"type": "voice.speak", "status": "planned"}],
            }

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--coordinate-color-block-command", "red", "--coordinate-apply"],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "game_feedback"' in output
    assert '"voice.speak"' in output


def test_main_can_route_expression_event_through_growth_guidance(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_expression_event_json(
            self, raw_event_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_event_json == '{"type":"dialogue_event"}'
            assert kwargs == {
                "apply_output": False,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
                "use_growth_guidance": True,
            }
            return {"intent": "expression_scaffold", "source": "growth_guidance"}

    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--expression-event-json",
            '{"type":"dialogue_event"}',
            "--growth-guidance",
        ],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "expression_scaffold"' in output
    assert '"source": "growth_guidance"' in output


def test_main_handles_expression_event_file(monkeypatch, capsys, tmp_path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text('{"type":"vision_event"}', encoding="utf-8")

    class FakeApp:
        def run_expression_event_json(
            self, raw_event_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_event_json == '{"type":"vision_event"}'
            assert kwargs == {
                "apply_output": False,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
            }
            return {"intent": "eye_distance", "priority": 3}

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--expression-event-file", str(event_path)],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"intent": "eye_distance"' in output
    assert '"priority": 3' in output


def test_main_applies_expression_event_file(monkeypatch, capsys, tmp_path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text('{"type":"vision_event"}', encoding="utf-8")

    class FakeApp:
        def run_expression_event_json(
            self, raw_event_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_event_json == '{"type":"vision_event"}'
            assert kwargs == {
                "apply_output": True,
                "no_tts": True,
                "local_tts_fallback": False,
                "output_device": None,
            }
            return {
                "output": {"intent": "eye_distance"},
                "action": {"screen_expression": "caring"},
                "tts_played": False,
            }

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--expression-event-file", str(event_path), "--expression-apply"],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"output": {"intent": "eye_distance"}' in output
    assert '"tts_played": false' in output


def test_main_expression_speak_enables_tts(monkeypatch, capsys) -> None:
    class FakeApp:
        def run_expression_event_json(
            self, raw_event_json: str, **kwargs
        ) -> dict[str, object]:
            assert raw_event_json == '{"type":"touch_event"}'
            assert kwargs == {
                "apply_output": True,
                "no_tts": False,
                "local_tts_fallback": True,
                "output_device": 3,
            }
            return {"output": {"intent": "greet"}, "tts_played": True}

    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--expression-event-json",
            '{"type":"touch_event"}',
            "--expression-speak",
            "--local-tts-fallback",
            "--output-device",
            "3",
        ],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    output = capsys.readouterr().out
    assert '"tts_played": true' in output


def test_main_wake_chat_realtime_tts_preserves_wake_flow(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeApp:
        def run_wake_chat(self, **kwargs) -> int:
            calls.append(kwargs)
            return 1

    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--wake-chat",
            "--realtime-tts",
            "--low-latency-voice",
            "--show-wake-level",
            "--max-wake-sessions",
            "1",
        ],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    assert calls
    assert calls[0]["realtime_tts"] is True
    assert calls[0]["low_latency_voice"] is True
    assert calls[0]["no_quick_ack"] is False
    assert calls[0]["no_wake_ack"] is False
    assert calls[0]["show_wake_level"] is True
    assert calls[0]["max_sessions"] == 1


def test_main_wake_chat_allows_realtime_tts_with_board_output(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeApp:
        def run_wake_chat(self, **kwargs) -> int:
            calls.append(kwargs)
            return 1

    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--wake-chat",
            "--realtime-tts",
            "--board-audio-output",
            "--max-wake-sessions",
            "1",
        ],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    assert calls
    assert calls[0]["realtime_tts"] is True
    assert calls[0]["output_device"] == BOARD_APLAY_OUTPUT_DEVICE


def test_main_voice_once_passes_realtime_asr_options(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    class FakeResult:
        user_text = "你好"
        assistant_text = "我在"
        action = {"screen_expression": "smile"}
        audio_path = "input.wav"

    class FakeApp:
        def run_voice_once(self, **kwargs) -> FakeResult:
            calls.append(kwargs)
            return FakeResult()

    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--voice-once",
            "--realtime-asr",
            "--streaming-asr",
            "--realtime-asr-model",
            "paraformer-realtime-v2",
        ],
    )
    monkeypatch.setattr("main.XingbaoApp", lambda: FakeApp())

    assert main() == 0
    assert calls
    assert calls[0]["realtime_asr"] is True
    assert calls[0]["streaming_asr"] is True
    assert calls[0]["realtime_asr_model"] == "paraformer-realtime-v2"
    assert "Xingbao: 我在" in capsys.readouterr().out
