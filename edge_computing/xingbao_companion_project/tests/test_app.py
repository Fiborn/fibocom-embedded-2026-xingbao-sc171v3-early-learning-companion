import threading
from pathlib import Path
from typing import Any

import pytest

from app import (
    ExpressionApplyResult,
    FOLLOWUP_AUDIO_SETTLE_SECONDS,
    FINALS_GUIDED_RESPONSE_DELAY_SECONDS,
    VoiceTurnResult,
    XingbaoApp,
    _canonical_dinosaur_intro_from_llm_json,
    _canonical_dinosaur_intro_from_candidate,
    _fast_lead_in_for_user_text,
    _looks_like_dinosaur_script_trigger_candidate,
    _reply_commits_to_conversation_end,
    _scenario_prompt_for_user_text,
    _voice_prompt_rate,
    normalize_asr_text,
    sanitize_tts_stream_delta,
    sanitize_tts_text,
    split_realtime_tts_chunks,
    split_streaming_segments,
)
from core.memory import MemoryManager
from core.game_speech_cache import GameSpeechCache
from core.expression import ExpressionOutput
from core.session import SessionManager
from core.settings import AppSettings
from core.voice_events import VoiceEvent, VoiceInteractionPipeline
from multimodal.asr_client import EmptyRecognitionResult
from multimodal.vad import NoSpeechTimeout, VADConfig


def test_explicit_pause_reply_recovers_missing_end_conversation_tool_call() -> None:
    assert _reply_commits_to_conversation_end(
        "好的，星宝先暂停对话。想继续时再叫我星宝星宝哦。"
    )
    assert _reply_commits_to_conversation_end("现在结束对话，我们下次再聊。")
    assert not _reply_commits_to_conversation_end("怎样暂停对话？")
    assert not _reply_commits_to_conversation_end("我们暂停一下这个游戏吧。")


def test_first_result_tts_queue_clears_camera_preview_before_audio() -> None:
    app = XingbaoApp()
    events: list[VoiceEvent] = []
    pipeline = VoiceInteractionPipeline(events.append)
    app._camera_snapshot_preview_active = True

    app._emit_tts_segment_queued(pipeline, "这是水杯。", 1)

    assert [event.type for event in events] == [
        "camera_snapshot_clear",
        "tts_segment_queued",
    ]


def test_camera_preview_shows_before_prompt_and_clears_before_result_tts() -> None:
    class CameraReplyLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            self.on_agent_event({
                "type": "camera_snapshot_ready",
                "data_uri": "data:image/jpeg;base64,preview",
                "width": 320,
                "height": 240,
            })
            self.on_agent_event({
                "type": "realtime_query_started",
                "tools": ["inspect_current_camera"],
                "subtitle": "让我看一看",
                "voice_prompt": "稍等一小会儿，让我仔细看一看。",
            })
            yield "这是水杯。"

    app = XingbaoApp()
    app.llm_client = CameraReplyLLM()
    events: list[VoiceEvent] = []
    pipeline = VoiceInteractionPipeline(events.append)

    assert app._generate_and_speak_streaming(
        "我手上拿的是什么？",
        "系统提示",
        history=[],
        tts_client=None,
        no_tts=True,
        local_tts_fallback=False,
        output_device=None,
        pipeline=pipeline,
    ) == "这是水杯。"

    types = [event.type for event in events]
    assert types.index("camera_snapshot_ready") < types.index("realtime_query_started")
    overlay_and_queue_types = [
        event_type
        for event_type in types
        if event_type in {
            "camera_snapshot_ready",
            "camera_snapshot_clear",
            "realtime_query_started",
            "tts_segment_queued",
        }
    ]
    assert overlay_and_queue_types == [
        "camera_snapshot_ready",
        "realtime_query_started",
        "tts_segment_queued",
        "tts_segment_queued",
        "camera_snapshot_clear",
    ]


def test_realtime_tts_keeps_camera_preview_through_query_prompt(monkeypatch) -> None:
    class CameraReplyLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            self.on_agent_event({
                "type": "camera_snapshot_ready",
                "data_uri": "data:image/jpeg;base64,preview",
                "width": 320,
                "height": 240,
            })
            self.on_agent_event({
                "type": "realtime_query_started",
                "tools": ["inspect_current_camera"],
                "subtitle": "让我看一看",
                "voice_prompt": "稍等一小会儿，让我仔细看一看。",
            })
            yield "这是水杯。"

    class FakeRealtimeTTSHandle:
        audio_started = False
        error = None

        def __init__(self, **_kwargs: Any) -> None:
            pass

        def set_interrupt_event(self, _interrupt_event: threading.Event | None) -> None:
            pass

        def start_background(self, **_kwargs: Any) -> None:
            pass

        def wait_ready(self) -> bool:
            return True

        def enqueue(self, _text: str) -> None:
            pass

        def close(self) -> None:
            pass

        def close_quietly(self) -> None:
            pass

    app = XingbaoApp()
    app.llm_client = CameraReplyLLM()
    events: list[VoiceEvent] = []
    pipeline = VoiceInteractionPipeline(events.append)
    monkeypatch.setattr("app._RealtimeTTSHandle", FakeRealtimeTTSHandle)

    assert app._generate_and_speak_realtime_tts(
        "我手上拿的是什么？",
        "系统提示",
        history=[],
        tts_client=None,
        local_tts_fallback=False,
        output_device=None,
        pipeline=pipeline,
    ) == "这是水杯。"

    overlay_and_queue_types = [
        event.type
        for event in events
        if event.type in {
            "camera_snapshot_ready",
            "camera_snapshot_clear",
            "realtime_query_started",
            "tts_segment_queued",
        }
    ]
    assert overlay_and_queue_types == [
        "camera_snapshot_ready",
        "realtime_query_started",
        "tts_segment_queued",
        "tts_segment_queued",
        "camera_snapshot_clear",
    ]


def test_realtime_query_prompt_does_not_poison_the_answer_tts_stream(monkeypatch) -> None:
    """A closed idle prompt stream must recover the answer instead of pausing chat."""
    class CameraReplyLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            self.on_agent_event({
                "type": "realtime_query_started",
                "tools": ["inspect_current_camera"],
                "subtitle": "让我看一看",
                "voice_prompt": "等一小会，让我仔细看一看。",
            })
            yield "这是水杯。"

    handles: list[Any] = []

    class FakeRealtimeTTSHandle:
        error = None

        def __init__(self, **_kwargs: Any) -> None:
            self.index = len(handles)
            self.audio_started = self.index == 0
            handles.append(self)

        def set_interrupt_event(self, _interrupt_event: threading.Event | None) -> None:
            pass

        def start_background(self, **_kwargs: Any) -> None:
            pass

        def ensure_started(self, **_kwargs: Any) -> bool:
            return True

        def wait_ready(self) -> bool:
            return True

        def enqueue(self, _text: str) -> None:
            if self.index == 2:  # fresh answer stream cannot connect
                raise ConnectionError("WebSocket connection is closed")

        def close(self) -> None:
            pass

        def close_quietly(self) -> None:
            pass

    app = XingbaoApp()
    app.llm_client = CameraReplyLLM()
    recovered: list[str] = []
    monkeypatch.setattr("app._RealtimeTTSHandle", FakeRealtimeTTSHandle)
    monkeypatch.setattr(
        app,
        "_speak_existing_text_streaming",
        lambda text, **_kwargs: recovered.append(text),
    )

    assert app._generate_and_speak_realtime_tts(
        "看一下这是什么？",
        "系统提示",
        history=[],
        tts_client=None,
        local_tts_fallback=False,
        output_device=None,
        pipeline=VoiceInteractionPipeline(),
    ) == "这是水杯。"
    assert len(handles) == 3  # initial prewarm, prompt, just-in-time answer
    assert recovered == ["这是水杯。"]


def test_new_camera_snapshot_replaces_an_active_preview_in_order() -> None:
    app = XingbaoApp()
    events: list[VoiceEvent] = []
    pipeline = VoiceInteractionPipeline(events.append)

    app._forward_camera_snapshot_agent_event(pipeline, {
        "type": "camera_snapshot_ready",
        "data_uri": "data:image/jpeg;base64,first",
        "width": 320,
        "height": 240,
    })
    app._forward_camera_snapshot_agent_event(pipeline, {
        "type": "camera_snapshot_ready",
        "data_uri": "data:image/jpeg;base64,second",
        "width": 640,
        "height": 480,
        "mirror": False,
    })

    assert [event.type for event in events] == [
        "camera_snapshot_ready",
        "camera_snapshot_clear",
        "camera_snapshot_ready",
    ]
    assert events[0].data["mirror"] is True
    assert events[-1].data["mirror"] is False


def test_app_runs_text_demo() -> None:
    output = XingbaoApp().run_text_demo()

    assert "Xingbao:" in output
    assert "Prompt preview:" in output


def test_dinosaur_script_json_protocol_is_prompted_and_strictly_validated() -> None:
    text = "我叫小羽，我很喜欢恐龙"

    assert _looks_like_dinosaur_script_trigger_candidate(text)
    prompt = _scenario_prompt_for_user_text(text)
    assert '"action":"dinosaur_script"' in prompt
    assert _canonical_dinosaur_intro_from_llm_json(
        '{"type":"xingbao","action":"dinosaur_script","name":"小羽"}'
    ) == "我叫小羽，我喜欢恐龙"
    assert _canonical_dinosaur_intro_from_llm_json(
        '{"type":"xingbao","action":"open_drawing","name":"小羽"}'
    ) == ""
    assert _canonical_dinosaur_intro_from_candidate("呃小宇喜欢恐龙") == (
        "我叫小宇，我喜欢恐龙"
    )


def test_llm_dinosaur_script_json_fallback_starts_canonical_flow() -> None:
    class JsonOnlyLLM:
        def generate_reply(self, *_args: Any, **_kwargs: Any) -> str:
            return (
                '{"type":"xingbao","action":"dinosaur_script","name":"小雨"}'
            )

    app = XingbaoApp()
    app.llm_client = JsonOnlyLLM()

    canonical = app._llm_dinosaur_script_fallback("我是小雨，特别喜欢恐龙")
    reply = app.handle_guided_expression_text(canonical)

    assert canonical == "我叫小雨，我喜欢恐龙"
    assert reply is not None
    assert reply.scene == "dinosaur_interest_started"


def test_app_runs_expression_demo() -> None:
    output = XingbaoApp().run_expression_demo()

    assert "星宝表达调度 demo" in output
    assert "Intent: guide_expression" in output
    assert "Memory:" in output
    assert "喝一小口水" in output


def test_app_handles_expression_event_json() -> None:
    output = XingbaoApp().run_expression_event_json(
        '{"type":"vision_event","source":"vision","payload":{"event":"face_too_close"}}'
    )

    assert output["intent"] == "eye_distance"
    assert output["priority"] == 3
    assert "往后坐" in output["speak_text"]


def test_app_plans_coordinated_game_request_without_launching() -> None:
    result = XingbaoApp().run_coordinated_text(
        "星宝我要玩游戏啦",
        apply_output=True,
    )

    assert result["plan"]["intent"]["intent"] == "open_tool"
    assert result["plan"]["tool_request"]["target"] == "mini_game_hub"
    assert result["applied"]["action"] == {
        "screen_expression": "smile",
        "led_mode": "warm_breath",
    }
    assert result["applied"]["tts_played"] is False
    assert result["tool_launched"] is False
    assert result["tool_launch_status"] == "ready"
    assert [event["type"] for event in result["trace"]] == [
        "ui.expression",
        "voice.speak",
        "tool.open",
    ]
    assert result["trace"][0]["status"] == "applied"
    assert result["trace"][1]["status"] == "skipped"
    assert result["trace"][1]["payload"]["tts_requested"] is True
    assert "选择一个游戏" in result["trace"][1]["payload"]["speak_text"]
    assert result["trace"][2]["status"] == "planned"


def test_app_can_launch_coordinated_tool_when_explicitly_enabled(monkeypatch) -> None:
    app = XingbaoApp()
    launched: list[str] = []
    monkeypatch.setattr(app, "launch_tool", lambda target: launched.append(target))

    result = app.run_coordinated_text("星宝我要玩游戏啦", launch_tools=True)

    assert launched == []
    assert result["tool_launched"] is False
    assert result["tool_launch_status"] == "ready"
    assert result["trace"][-1]["type"] == "tool.open"
    assert result["trace"][-1]["status"] == "failed_or_unavailable"


def test_app_runs_coordinated_game_event_through_trace() -> None:
    result = XingbaoApp().run_coordinated_event_json(
        '{"type":"game_event","source":"mini_game","payload":{"event":"child_made_mistake"}}',
        apply_output=True,
    )

    assert result["plan"]["intent"]["intent"] == "game_event"
    assert result["plan"]["expression_output"]["intent"] == "encourage_retry"
    assert result["applied"]["action"]["screen_expression"] == "smile"
    assert [event["type"] for event in result["trace"]] == [
        "ui.expression",
        "voice.speak",
    ]
    assert result["trace"][0]["status"] == "applied"
    assert result["trace"][1]["status"] == "planned"


def test_read_aloud_speech_uses_interruptible_external_tts(monkeypatch) -> None:
    app = XingbaoApp()
    app.tts_client = object()
    calls = []

    def fake_speak(text, **kwargs):
        calls.append((text, kwargs))
        return None

    monkeypatch.setattr(app, "_speak_with_demo_cache", fake_speak)

    app.speak_game_text(
        "星宝学习桌面。",
        interrupt=True,
        source="xingbao_desktop_read_aloud",
        scene="desktop",
    )

    assert calls[0][0] == "星宝学习桌面。"
    assert calls[0][1]["interrupt_event"] is not None
    assert str(calls[0][1]["out_wav"]).endswith("read_aloud_speech.wav")


def test_external_game_speech_is_dropped_during_conversation(monkeypatch) -> None:
    """Catch a regression that lets a touch subtitle interrupt ASR/TTS."""
    app = XingbaoApp()
    app._voice_chat_session_active.set()
    spoken: list[str] = []
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **_kwargs: spoken.append(text),
    )

    result = app.speak_game_text(
        "点一下这里",
        source="xingbao_desktop_read_aloud",
        scene="desktop",
    )

    assert result is None
    assert spoken == []


def test_drink_reminder_is_played_once_after_conversation(monkeypatch) -> None:
    """Catch queued hydration prompts either being lost or replayed twice."""
    app = XingbaoApp()
    app._voice_chat_session_active.set()
    spoken: list[str] = []
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **_kwargs: spoken.append(text),
    )
    drink_output = ExpressionOutput(
        intent="drink_reminder",
        speak_text="要不要喝一小口水？喝完我们继续。",
        screen_text="喝一小口水",
        expression="caring",
        tts=True,
        source="vision",
    )

    first = app.apply_expression_output(drink_output, no_tts=False)
    second = app.apply_expression_output(drink_output, no_tts=False)
    app._voice_chat_session_active.clear()
    app._drain_pending_drink_reminder()
    app._drain_pending_drink_reminder()

    assert first.tts_played is False
    assert second.tts_played is False
    assert spoken == ["要不要喝一小口水？喝完我们继续。"]


def test_hydration_reset_clears_queued_drink_reminder(monkeypatch) -> None:
    """Catch an obsolete water reminder playing after the child already drank."""
    app = XingbaoApp()
    app._voice_chat_session_active.set()
    spoken: list[str] = []
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **_kwargs: spoken.append(text),
    )
    drink_output = ExpressionOutput(
        intent="drink_reminder",
        speak_text="要不要喝一小口水？喝完我们继续。",
        tts=True,
        source="vision",
    )

    app.apply_expression_output(drink_output, no_tts=False)
    assert app.clear_pending_drink_reminder() is True
    app._voice_chat_session_active.clear()
    app._drain_pending_drink_reminder()

    assert spoken == []


def test_conversation_activation_interrupts_current_external_speech() -> None:
    """Catch conversation start leaving already-playing auxiliary audio alive."""
    app = XingbaoApp()
    token = app._begin_game_speech_turn(interrupt=False)

    app._begin_conversation_audio_priority()

    assert token.is_set()


def test_touch_game_speech_uses_independent_interruptible_synthesis(monkeypatch) -> None:
    app = XingbaoApp()
    app.tts_client = object()
    calls = []

    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **kwargs: calls.append((text, kwargs)) or None,
    )

    app.speak_game_text(
        "请找到圆形在哪里。",
        interrupt=True,
        source="xingbao_touch_game",
        scene="game",
    )

    assert calls[0][1]["direct_tts"] is True
    assert calls[0][1]["interrupt_event"] is not None


def test_dispatcher_read_aloud_uses_its_job_specific_interrupt_token(
    monkeypatch,
) -> None:
    app = XingbaoApp()
    token = threading.Event()
    calls = []
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **kwargs: calls.append((text, kwargs)) or None,
    )

    app.speak_game_text(
        "圆形",
        interrupt=True,
        source="xingbao_desktop_read_aloud",
        scene="desktop",
        interrupt_event=token,
    )

    assert calls[0][1]["direct_tts"] is True
    assert calls[0][1]["interrupt_event"] is token


def test_voice_specific_game_cache_does_not_fall_back_to_legacy_voice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp()
    legacy = tmp_path / "work" / "cache" / "demo_open_game.wav"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"R" * 1200)
    voice_cache = tmp_path / "voice-specific" / "welcome.wav"
    synthesized = []
    played = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "app.speak",
        lambda text, **kwargs: synthesized.append((text, kwargs)) or voice_cache,
    )
    monkeypatch.setattr(
        "app.play_wav",
        lambda path, **kwargs: played.append(Path(path)),
    )

    result = app._speak_with_demo_cache(
        "进入游戏啦，请选择一个游戏，再选择难度。",
        tts_client=object(),
        out_wav=voice_cache,
        reuse_out_wav=True,
    )

    assert result == voice_cache
    assert synthesized
    assert played == []


def test_cache_prewarm_never_exposes_partially_downloaded_target(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"phrases":[{"id":"welcome","text":"欢迎","filename":"welcome.wav"}]}',
        encoding="utf-8",
    )
    app = XingbaoApp()
    app.game_speech_cache = GameSpeechCache(
        cache_dir=tmp_path / "cache",
        manifest_path=manifest,
        voice_id=app.voice_profile.id,
    )
    partial_written = threading.Event()
    finish_download = threading.Event()

    class SlowTTS:
        def synthesize(self, _text, out_wav):
            path = Path(out_wav)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"R" * 1200)
            partial_written.set()
            finish_download.wait(timeout=2.0)
            with path.open("ab") as stream:
                stream.write(b"W" * 1200)
            return path

    app.tts_client = SlowTTS()
    target = app.game_speech_cache.resolve_path("欢迎", app.voice_profile.id)
    result_box = []
    worker = threading.Thread(
        target=lambda: result_box.append(app.prepare_demo_tts_cache())
    )
    worker.start()
    assert partial_written.wait(1.0)

    assert target.exists() is False

    finish_download.set()
    worker.join(timeout=2.0)
    assert target.exists()
    assert result_box[0]["ok"] is True


def test_wake_ack_cache_is_prepared_under_work_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp()
    monkeypatch.chdir(tmp_path)

    class FakeTTS:
        def synthesize(self, _text, out_wav):
            path = Path(out_wav)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"W" * 1200)
            return path

    app.tts_client = FakeTTS()

    report = app.prepare_wake_ack_cache()

    assert report["ok"] is True
    assert report["counts"] == {"total": 3, "ready": 3, "failed": 0}
    assert all(Path(item["path"]).is_file() for item in report["items"])


def test_app_runs_vision_state_input_through_coordination() -> None:
    result = XingbaoApp().run_coordinated_state_json(
        '{"type":"vision_state","source":"vision","payload":{"state":"face_too_close","confidence":0.9}}',
        apply_output=True,
    )

    assert result["plan"]["intent"]["intent"] == "vision_state"
    assert result["plan"]["expression_output"]["intent"] == "eye_distance"
    assert result["applied"]["action"]["screen_expression"] == "smile"
    assert [event["type"] for event in result["trace"]] == [
        "ui.expression",
        "voice.speak",
    ]


class _FakeBoardUIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_plan(
        self,
        plan: Any,
        *,
        duration_ms: int = 4000,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "plan": plan.as_dict(),
                "duration_ms": duration_ms,
                "request_id": request_id,
            }
        )
        return {
            "ok": True,
            "request": {"type": "assistant_output"},
            "response": {"type": "command_result", "ok": True},
        }


def test_app_sends_expression_only_plan_to_board_ui() -> None:
    board_ui = _FakeBoardUIClient()

    result = XingbaoApp().run_coordinated_state_json(
        '{"type":"vision_state","source":"vision","payload":{"state":"face_too_close","confidence":0.9}}',
        apply_output=True,
        board_ui_client=board_ui,
    )

    assert len(board_ui.calls) == 1
    assert result["board_ui"]["ok"] is True
    assert result["trace"][-1]["type"] == "board_ui.assistant_output"
    assert result["trace"][-1]["status"] == "sent"


def test_active_conversation_suppresses_external_board_subtitle() -> None:
    """Catch vision status text overwriting an in-progress dialogue subtitle."""

    class PriorityAwareBoardUI:
        def __init__(self) -> None:
            self.include_screen_text: list[bool] = []

        def send_plan(self, _plan, *, include_screen_text: bool = True):
            self.include_screen_text.append(include_screen_text)
            return {
                "ok": True,
                "request": {"type": "assistant_output"},
                "response": {"type": "command_result", "ok": True},
                "arm": {"ok": True, "arm_action": "shake_head"},
            }

    app = XingbaoApp()
    app._voice_chat_session_active.set()
    board_ui = PriorityAwareBoardUI()

    app.run_coordinated_state_json(
        '{"type":"vision_state","source":"vision","payload":{"state":"face_too_close","confidence":0.9}}',
        apply_output=False,
        board_ui_client=board_ui,
    )

    assert board_ui.include_screen_text == [False]


def test_vision_feedback_can_reach_board_before_tts(monkeypatch) -> None:
    order: list[str] = []

    class OrderedBoardUIClient:
        def send_plan(self, plan):
            order.append("board")
            return {
                "ok": True,
                "request": {"type": "assistant_output"},
                "response": {"type": "command_result", "ok": True},
                "arm": {"ok": True, "arm_action": "shake_head"},
            }

    app = XingbaoApp()

    def fake_apply(output, **kwargs):
        order.append("tts")
        return ExpressionApplyResult(
            output=output.as_dict(),
            action={},
            memory=None,
            tts_played=True,
        )

    monkeypatch.setattr(app, "apply_expression_output", fake_apply)

    result = app.run_coordinated_state_json(
        '{"type":"vision_state","source":"vision","payload":{"state":"child_emotion_detected","emotion":"sadness"}}',
        apply_output=True,
        no_tts=False,
        board_ui_client=OrderedBoardUIClient(),
        board_ui_first=True,
    )

    assert order == ["board", "tts"]
    assert result["board_ui"]["arm"]["arm_action"] == "shake_head"


def test_app_runs_game_command_through_adapter_and_coordination() -> None:
    result = XingbaoApp().run_game_command_json(
        '{"type":"game_command","game_id":"shape_game","intent":"get_hint","user_text":"\u6211\u4e0d\u4f1a"}',
        apply_output=True,
    )

    assert result["game_response"]["type"] == "game_response"
    assert result["game_response"]["ok"] is True
    assert result["game_response"]["intent"] == "get_hint"
    assert result["plan"]["intent"]["intent"] == "game_response"
    assert result["plan"]["intent"]["source_text"] == "get_hint"
    assert result["plan"]["expression_output"]["intent"] == "get_hint"
    assert result["applied"]["action"]["screen_expression"] == "thinking"
    assert [event["type"] for event in result["trace"]] == [
        "ui.expression",
        "voice.speak",
    ]


def test_app_runs_color_block_command_through_coordination() -> None:
    result = XingbaoApp().run_coordinated_color_block_command(
        "绾㈣壊鏀炬槦鍏夌嚎",
        apply_output=True,
    )

    assert result["plan"]["intent"]["intent"] == "xingbao_expression_request"
    assert result["plan"]["expression_output"]["intent"] == "game_feedback"
    assert result["applied"]["action"]["screen_expression"] == "smile"
    assert [event["type"] for event in result["trace"]] == [
        "ui.expression",
        "voice.speak",
    ]
    assert result["trace"][1]["status"] == "planned"


def test_app_applies_expression_event_to_memory_and_action(tmp_path: Path) -> None:
    app = XingbaoApp(
        session=SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))
    )

    result = app.run_expression_event_json(
        '{"type":"memory_write_request","source":"demo","payload":{"memory_kind":"interest","content":"三角龙"}}',
        apply_output=True,
    )

    assert result["output"]["intent"] == "acknowledge_memory"
    assert result["action"] == {
        "screen_expression": "smile",
        "led_mode": "warm_breath",
    }
    assert result["memory"]["interests"] == ["三角龙"]
    assert result["tts_played"] is False


def test_app_expression_speak_uses_tts_when_enabled(monkeypatch) -> None:
    app = XingbaoApp()
    app.tts_client = object()
    spoken: list[str] = []
    monkeypatch.setattr(
        "app.speak",
        lambda text, **_kwargs: spoken.append(text) or None,
    )

    result = app.run_expression_event_json(
        '{"type":"touch_event","source":"touch","payload":{"event":"child_touched_xingbao"}}',
        apply_output=True,
        no_tts=False,
    )

    assert result["tts_played"] is True
    assert spoken == ["我在呢，要一起玩一会儿吗？"]


def test_app_builds_prompt_preview() -> None:
    prompt = XingbaoApp().build_prompt_preview()

    assert '你叫星宝' in prompt
    assert '4-6岁' in prompt
    assert '不要询问或保存家庭住址' in prompt

def test_app_detects_configured_exit_words() -> None:
    app = XingbaoApp(settings=AppSettings(conversation_exit_words=("不聊了",)))

    assert app._is_exit_text("我现在不聊了") is True
    assert app._is_exit_text("我们继续讲故事") is False


def test_app_does_not_treat_negated_exit_word_as_session_exit() -> None:
    app = XingbaoApp(settings=AppSettings(conversation_exit_words=("结束",)))

    assert app._is_exit_text("故事不要结束") is False
    assert app._is_exit_text("我不想结束") is False
    assert app._is_exit_text("故事现在结束") is True


def test_song_request_does_not_receive_story_prompt_or_lead_in() -> None:
    assert _scenario_prompt_for_user_text("我想听你唱歌") == ""
    assert _fast_lead_in_for_user_text("我想听你唱歌") == ""


def test_story_prompt_declares_extended_reply_limit() -> None:
    prompt = _scenario_prompt_for_user_text("我想听一个恐龙故事")

    assert "回复长度上限：220" in prompt


class FakeWakeWordDetector:
    def wait_for_wake_word(self) -> str:
        return "星宝星宝"


def test_app_wake_loop_runs_voice_turn_after_detection(monkeypatch) -> None:
    app = XingbaoApp(settings=AppSettings(wake_word_cooldown_seconds=0))
    expected = VoiceTurnResult(
        user_text="你好",
        assistant_text="你好呀",
        action={"face": "smile"},
        audio_path="input.wav",
    )
    calls: list[bool] = []
    monkeypatch.setattr(app, "run_voice_once", lambda **_kwargs: calls.append(True) or expected)

    completed = app.run_wake_loop(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_turns=1,
    )

    assert completed == 1
    assert calls == [True]


def test_wake_loop_clears_an_active_camera_preview_at_session_end(monkeypatch) -> None:
    app = XingbaoApp(settings=AppSettings(wake_word_cooldown_seconds=0))
    app._camera_snapshot_preview_active = True
    events: list[VoiceEvent] = []
    expected = VoiceTurnResult("你好", "你好呀", {}, "input.wav")
    monkeypatch.setattr(app, "run_voice_once", lambda **_kwargs: expected)

    app.run_wake_loop(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_turns=1,
        on_voice_event=events.append,
    )

    assert [event.type for event in events][-2:] == [
        "camera_snapshot_clear",
        "session_ended",
    ]


def test_app_wake_chat_stops_session_after_followup_timeout(monkeypatch) -> None:
    app = XingbaoApp(
        settings=AppSettings(
            wake_word_cooldown_seconds=0,
            conversation_followup_timeout_seconds=0.25,
            max_conversation_turns=3,
        )
    )
    expected = VoiceTurnResult(
        user_text="你好",
        assistant_text="你好呀",
        action={"face": "smile"},
        audio_path="input.wav",
    )
    listen_timeouts: list[float] = []

    def fake_voice_once(**kwargs):
        listen_timeouts.append(kwargs["listen_timeout_seconds"])
        if len(listen_timeouts) == 1:
            return expected
        raise NoSpeechTimeout("done")

    turn_results: list[VoiceTurnResult] = []
    session_results: list[tuple[int, str]] = []
    monkeypatch.setattr(app, "run_voice_once", fake_voice_once)

    completed = app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_sessions=1,
        on_turn_complete=turn_results.append,
        on_session_complete=lambda count, reason: session_results.append((count, reason)),
    )

    assert completed == 1
    assert listen_timeouts == [0.0, 0.25]
    assert turn_results == [expected]
    assert session_results == [(1, "timeout")]


def test_wake_chat_reconnects_once_after_transient_streaming_asr_stop(monkeypatch) -> None:
    app = XingbaoApp(settings=AppSettings(wake_word_cooldown_seconds=0))
    calls: list[int] = []
    events: list[VoiceEvent] = []
    expected = VoiceTurnResult(
        user_text="你好",
        assistant_text="你好呀",
        action={},
        audio_path="input.wav",
        end_session=True,
    )

    def fake_voice_once(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Speech recognition has stopped.")
        return expected

    monkeypatch.setattr(app, "run_voice_once", fake_voice_once)

    completed = app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_sessions=1,
        streaming_asr=True,
        on_voice_event=events.append,
    )

    assert completed == 1
    assert calls == [1, 1]
    assert [event.type for event in events].count("asr_reconnecting") == 1
    assert [event.type for event in events][-1] == "session_ended"


def test_wake_chat_does_not_apply_wake_cooldown_between_followup_turns(
    monkeypatch,
) -> None:
    app = XingbaoApp(
        settings=AppSettings(
            wake_word_cooldown_seconds=1.2,
            max_conversation_turns=2,
        )
    )
    timeline: list[str] = []
    results = [
        VoiceTurnResult("你好", "你好呀", {}, "first.wav"),
        VoiceTurnResult("再见", "再见", {}, "second.wav", end_session=True),
    ]

    def fake_voice_once(**_kwargs):
        timeline.append(f"turn_{len(timeline) + 1}")
        return results.pop(0)

    monkeypatch.setattr(app, "run_voice_once", fake_voice_once)
    monkeypatch.setattr("app.time.sleep", lambda seconds: timeline.append(f"sleep_{seconds}"))

    app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_sessions=1,
    )

    assert timeline == ["turn_1", "turn_2"]


def test_app_wake_chat_emits_wake_ack_by_default(monkeypatch) -> None:
    app = XingbaoApp(settings=AppSettings(wake_word_cooldown_seconds=0))
    expected = VoiceTurnResult(
        user_text="再见",
        assistant_text="好呢",
        action={"face": "smile"},
        audio_path="input.wav",
        end_session=True,
    )
    spoken: list[str] = []
    events: list[VoiceEvent] = []

    monkeypatch.setattr(app, "run_voice_once", lambda **_kwargs: expected)
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **_kwargs: spoken.append(text),
    )

    completed = app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        max_sessions=1,
        on_voice_event=events.append,
    )

    assert completed == 1
    assert spoken == ["我在呢。"]
    assert "wake_ack_started" in [event.type for event in events]


def test_scripted_followup_listens_without_a_second_wake_or_wake_ack(monkeypatch) -> None:
    app = XingbaoApp(settings=AppSettings(wake_word_cooldown_seconds=0))
    app.handle_guided_expression_text("我叫小宇，我喜欢恐龙")
    app.handle_guided_expression_text("有一种恐龙特别大，我不知道怎么说")
    app.handle_guided_expression_text("对")
    app.handle_guided_expression_text("我喜欢腕龙，因为它身体大，脖子长")
    assert app.request_scripted_followup("drawing_consent")["ok"] is True

    expected = VoiceTurnResult(
        user_text="好呀",
        assistant_text="那我们去百宝箱画一画吧。",
        action={},
        audio_path="input.wav",
        end_session=True,
        session_end_reason="guided_expression_touch_handoff",
    )
    events: list[VoiceEvent] = []
    spoken: list[str] = []
    monkeypatch.setattr(app, "run_voice_once", lambda **_kwargs: expected)
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda text, **_kwargs: spoken.append(text),
    )

    completed = app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        max_sessions=1,
        on_voice_event=events.append,
    )

    assert completed == 1
    assert spoken == []
    assert "scripted_followup_listening" in [event.type for event in events]
    assert "wake_ack_started" not in [event.type for event in events]


def test_memory_recall_timeout_clears_the_dinosaur_handoff(monkeypatch) -> None:
    app = XingbaoApp(
        settings=AppSettings(
            wake_word_cooldown_seconds=0,
            conversation_followup_timeout_seconds=0.25,
        )
    )
    app._guided_expression_handoff_active.set()
    app._scripted_memory_recall_armed.set()
    assert app.request_scripted_followup("memory_recall") == {
        "ok": True,
        "kind": "memory_recall",
    }
    received_timeouts: list[float] = []

    def fake_voice_once(**kwargs):
        received_timeouts.append(kwargs["listen_timeout_seconds"])
        raise NoSpeechTimeout("no answer")

    monkeypatch.setattr(app, "run_voice_once", fake_voice_once)

    app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_sessions=1,
    )

    assert received_timeouts == [30.0]
    assert app._guided_expression_handoff_active.is_set() is False
    assert app._scripted_memory_recall_armed.is_set() is False


def test_wake_ack_text_rotates_through_verified_short_cache_items() -> None:
    app = XingbaoApp()

    assert [app._next_wake_ack_text() for _ in range(4)] == [
        "我在呢。",
        "你好呀，小朋友。",
        "我在呢，想说什么？",
        "我在呢。",
    ]


def test_app_wake_chat_stops_session_on_exit_word(monkeypatch) -> None:
    app = XingbaoApp(settings=AppSettings(wake_word_cooldown_seconds=0))
    expected = VoiceTurnResult(
        user_text="再见",
        assistant_text="好呢",
        action={"face": "smile"},
        audio_path="input.wav",
        end_session=True,
    )
    monkeypatch.setattr(app, "run_voice_once", lambda **_kwargs: expected)
    session_results: list[tuple[int, str]] = []

    completed = app.run_wake_chat(
        detector=FakeWakeWordDetector(),
        no_wake_ack=True,
        max_sessions=1,
        on_session_complete=lambda count, reason: session_results.append((count, reason)),
    )

    assert completed == 1
    assert session_results == [(1, "exit_word")]


def test_voice_turn_emits_streaming_pipeline_events(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "你好新宝"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            assert user_text == "你好星宝"
            assert system_prompt
            assert history == []
            yield "你好，"
            yield "我在。✨\n"

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 900.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(no_tts=True, on_voice_event=events.append)

    assert result.user_text == "你好星宝"
    assert result.assistant_text == "你好，我在。✨"
    assert result.audio_path == str(wav_path)
    event_types = [event.type for event in events]
    assert event_types[0] == "listening_started"
    assert "network_warmup_started" in event_types
    assert "speech_captured" in event_types
    assert "asr_started" in event_types
    assert "asr_final" in event_types
    assert "llm_delta" in event_types
    assert "llm_stream_finished" in event_types
    assert "tts_synthesis_started" in event_types
    assert "tts_synthesis_skipped" in event_types
    assert "tts_segment_queued" in event_types
    assert "playback_started" not in event_types
    assert "playback_skipped" in event_types
    asr_events = [event for event in events if event.type == "asr_final"]
    assert "elapsed_ms" in asr_events[-1].data
    assert asr_events[-1].data["text_chars"] == len("你好星宝")
    asr_started_events = [event for event in events if event.type == "asr_started"]
    assert asr_started_events[-1].data["capture_utterance_ms"] == 900.0
    first_delta_events = [
        event
        for event in events
        if event.type == "llm_delta" and event.data.get("index") == 1
    ]
    assert "first_delta_elapsed_ms" in first_delta_events[-1].data
    first_tts_events = [
        event
        for event in events
        if event.type == "tts_segment_queued" and event.data.get("index") == 1
    ]
    assert "first_queue_elapsed_ms" in first_tts_events[-1].data


def test_empty_asr_cancels_delayed_processing_notice(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "empty.wav"
    cancelled: list[bool] = []

    class EmptyASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            raise EmptyRecognitionResult("no usable speech")

    monkeypatch.setattr(
        "app.capture_utterance_vad",
        lambda **_kwargs: (wav_path, {"utterance_ms": 900.0}),
    )
    monkeypatch.setattr(
        app,
        "_notify_board_processing",
        lambda *_args, **_kwargs: lambda: cancelled.append(True),
    )
    app.asr_client = EmptyASR()  # type: ignore[assignment]

    try:
        app.run_voice_once(no_tts=True)
    except NoSpeechTimeout:
        pass
    else:
        raise AssertionError("empty ASR must end the voice turn")

    assert cancelled == [True]


def test_guided_reply_waits_for_final_asr_then_uses_a_short_pause(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp(
        settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0),
        session=SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json")),
    )
    app.handle_guided_expression_text("我叫小宇，我喜欢恐龙")
    wav_path = tmp_path / "guided.wav"
    order: list[str] = []
    pauses: list[float] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            order.append("asr_final_result")
            return "演员这一句怎么说都可以"

    def fake_capture(**_kwargs: Any):
        return wav_path, {"utterance_ms": 900.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture)
    monkeypatch.setattr("app.time.sleep", lambda seconds: pauses.append(seconds))
    monkeypatch.setattr(
        app,
        "_speak_with_demo_cache",
        lambda _text, **_kwargs: order.append("guided_reply_spoken"),
    )
    app.asr_client = FakeASR()  # type: ignore[assignment]

    result = app.run_voice_once(no_quick_ack=True)

    assert result.assistant_text == "没关系，我们慢慢说。它能吃到高高的树叶吗？"
    assert order == ["asr_final_result", "guided_reply_spoken"]
    assert FINALS_GUIDED_RESPONSE_DELAY_SECONDS in pauses


def test_voice_turn_answers_game_status_from_fixed_command(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝我现在有几颗星"

    class FailingLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            raise AssertionError("game status query should not call qwen-plus")

    class FakeBoardClient:
        def send_game_command(self, command):
            assert command["intent"] == "get_stars"
            return {
                "ok": True,
                "response": {"ok": True},
                "game_response": {
                    "type": "game_response",
                    "ok": True,
                    "message": "你现在有3颗星。",
                    "feedback": {"screen_expression": "smile"},
                },
            }

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FailingLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_tts=True,
        board_ui_client=FakeBoardClient(),  # type: ignore[arg-type]
    )

    assert result.assistant_text == "你现在有3颗星。"
    assert result.fast_path == "fixed_game_status"


def test_voice_turn_opens_game_with_stable_local_demo_reply(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    events: list[str] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝，我想玩形状游戏"

    class FakeLLM:
        def generate_reply(self, *_args: Any, **_kwargs: Any) -> str:
            events.append("llm_reply")
            return "好呀，我们来认形状。"

    class FakeBoardClient:
        def send_plan(self, plan):
            events.append("open_game")
            assert plan.intent.target == "mini_game_hub"
            return {"ok": True, "response": {"ok": True}}

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_tts=True,
        no_quick_ack=True,
        board_ui_client=FakeBoardClient(),  # type: ignore[arg-type]
    )

    assert events == ["open_game"]
    assert result.assistant_text == "进入游戏啦，请选择一个游戏，再选择难度。"
    assert result.fast_path == "demo_open_game"


def test_voice_turn_short_circuits_wake_only_text(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    spoken: list[str] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝，星宝。"

    class FailingLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            raise AssertionError("wake-only text should not call LLM")

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 600.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.speak", lambda text, **_kwargs: spoken.append(text) or None)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FailingLLM()  # type: ignore[assignment]

    result = app.run_voice_once(no_quick_ack=True)

    assert result.fast_path == "wake_only"
    assert result.assistant_text == "我在呢。你想聊什么？"
    assert spoken == ["我在呢。你想聊什么？"]


def test_wake_only_text_uses_realtime_tts_when_enabled(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    queued_fragments: list[str] = []
    order: list[str] = []
    prewarm_started = threading.Event()

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            assert prewarm_started.wait(timeout=1.0)
            order.append("asr")
            return "星宝，星宝。"

    class FailingLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            raise AssertionError("wake-only text should not call LLM")

    class FakeRealtimePlayer:
        sample_rate = 22050
        audio_started = False

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del settings, voice_profile, output_device, interrupt_event
            self.on_stream_start = on_stream_start
            self.on_audio_start = on_audio_start
            self.on_stream_done = on_stream_done

        def start(self) -> None:
            order.append("prewarm")
            prewarm_started.set()
            if self.on_stream_start is not None:
                self.on_stream_start()

        def enqueue(self, text: str) -> None:
            queued_fragments.append(text)
            self.audio_started = True
            if self.on_audio_start is not None:
                self.on_audio_start(320)

        def close(self) -> None:
            if self.on_stream_done is not None:
                self.on_stream_done(320, 0.01)

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 600.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FakeRealtimePlayer)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FailingLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        on_voice_event=events.append,
    )

    assert result.fast_path == "wake_only"
    assert queued_fragments == ["我在呢。你想聊什么？"]
    assert order.index("prewarm") < order.index("asr")
    event_types = [event.type for event in events]
    assert "tts_stream_audio_started" in event_types
    assert "playback_started" in event_types


def test_voice_turn_uses_low_latency_vad_config(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    captured_configs: list[VADConfig] = []

    class FakeASR:
        def transcribe(self, _path: Path | str) -> str:
            return "星宝，星宝。"

    def fake_capture_utterance_vad(**kwargs: Any):
        captured_configs.append(kwargs["vad_config"])
        return wav_path, {"utterance_ms": 360.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]

    result = app.run_voice_once(no_tts=True, low_latency_voice=True)

    assert result.fast_path == "wake_only"
    assert captured_configs
    assert captured_configs[0].calibrate_seconds == 0.18
    assert captured_configs[0].end_silence_ms == 1000
    assert captured_configs[0].min_utterance_ms == 650
    assert captured_configs[0].start_hold_ms == 60
    assert captured_configs[0].pre_roll_ms == 240


def test_voice_turn_shows_listening_only_after_microphone_is_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none"))
    wav_path = tmp_path / "input.wav"
    order: list[str] = []
    settle_values: list[float] = []
    events: list[VoiceEvent] = []

    class FakeASR:
        def transcribe(self, _path: Path | str) -> str:
            return "星宝星宝"

    class FakeBoardClient:
        def send_ui_command(self, _plan, **kwargs):
            if kwargs.get("screen_text") == "● 正在听，请说话":
                order.append("ui_listening")
            return {"ok": True, "response": {"ok": True}}

    def fake_capture_utterance_vad(**kwargs: Any):
        order.append("capture_open")
        kwargs["on_listening_ready"]()
        order.append("capture_ready_returned")
        return wav_path, {"utterance_ms": 360.0}

    monkeypatch.setattr(
        "app.wait_for_audio_playback_idle",
        lambda *, settle_seconds: settle_values.append(settle_seconds),
    )
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]

    app.run_voice_once(
        no_tts=True,
        low_latency_voice=True,
        board_ui_client=FakeBoardClient(),  # type: ignore[arg-type]
        on_voice_event=events.append,
    )

    event_types = [event.type for event in events]
    assert settle_values == [FOLLOWUP_AUDIO_SETTLE_SECONDS]
    assert FOLLOWUP_AUDIO_SETTLE_SECONDS == 0.08
    assert order[:3] == ["capture_open", "ui_listening", "capture_ready_returned"]
    assert event_types.index("listening_ready") < event_types.index("wake_ui_listening")
    assert event_types.index("wake_ui_listening") < event_types.index("speech_captured")


def test_voice_turn_streams_audio_frames_to_asr(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    frames: list[bytes] = []
    started: list[bool] = []
    finished: list[bool] = []

    class FailingASR:
        def transcribe(self, _path: Path | str) -> str:
            raise AssertionError("streaming_asr should not call batch ASR")

    class FakeStreamingASR:
        last_metrics = {
            "encode_ms": 0.0,
            "request_ms": 12.0,
            "total_stream_ms": 620.0,
            "engine": "dashscope_streaming_recognition",
            "model": "paraformer-realtime-v2",
            "frames": 1.0,
            "bytes": 9.0,
        }

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def start(self) -> None:
            started.append(True)

        def start_background(self) -> None:
            self.start()

        def send_audio_frame(self, frame: bytes) -> None:
            frames.append(frame)

        def finish(self) -> str:
            finished.append(True)
            return "你好星宝"

        def cancel(self) -> None:
            pass

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del system_prompt, history
            assert user_text == "你好星宝"
            yield "你好，"
            yield "我在。"

    def fake_capture_utterance_vad(**kwargs: Any):
        callback = kwargs.get("audio_frame_callback")
        assert callback is not None
        callback(b"pcm-frame")
        return wav_path, {"utterance_ms": 600.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.DashScopeStreamingRecognitionASRClient", FakeStreamingASR)
    app.asr_client = FailingASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_tts=True,
        streaming_asr=True,
        on_voice_event=events.append,
    )

    assert started == [True]
    assert frames == [b"pcm-frame"]
    assert finished == [True]
    assert result.user_text == "你好星宝"
    asr_event = next(event for event in events if event.type == "asr_final")
    assert asr_event.data["engine"] == "dashscope_streaming_recognition"
    assert asr_event.data["request_ms"] == 12.0
    assert asr_event.data["total_stream_ms"] == 620.0
    assert asr_event.data["frames"] == 1.0


def test_streaming_asr_partial_text_can_play_lead_in_before_finish(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    queued_fragments: list[str] = []
    order: list[str] = []

    class FakeStreamingASR:
        last_metrics = {
            "encode_ms": 0.0,
            "request_ms": 20.0,
            "total_stream_ms": 700.0,
            "engine": "dashscope_streaming_recognition",
            "model": "paraformer-realtime-v2",
            "frames": 2.0,
            "bytes": 18.0,
        }

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def start_background(self) -> None:
            order.append("asr_start")

        def send_audio_frame(self, _frame: bytes) -> None:
            pass

        def partial_text(self) -> str:
            return "我想听一个恐龙的故事"

        def finish(self) -> str:
            order.append("asr_finish")
            return "我想听一个恐龙的故事"

        def cancel(self) -> None:
            pass

    class FakeRealtimePlayer:
        sample_rate = 22050

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del settings, voice_profile, output_device, interrupt_event
            self.audio_started = False
            self.on_stream_start = on_stream_start
            self.on_audio_start = on_audio_start
            self.on_stream_done = on_stream_done

        def start(self) -> None:
            if self.on_stream_start is not None:
                self.on_stream_start()

        def enqueue(self, text: str) -> None:
            order.append(f"enqueue:{text}")
            queued_fragments.append(text)
            if not self.audio_started and self.on_audio_start is not None:
                self.audio_started = True
                self.on_audio_start(320)

        def close(self) -> None:
            if self.on_stream_done is not None:
                self.on_stream_done(320, 0.01)

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del system_prompt, history
            assert user_text == "我想听一个恐龙的故事"
            yield "小三角龙看见一串脚印。"
            yield "脚印能告诉我们动物走过的方向。"

    def fake_capture_utterance_vad(**kwargs: Any):
        callback = kwargs.get("audio_frame_callback")
        assert callback is not None
        callback(b"pcm-frame")
        return wav_path, {"utterance_ms": 600.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.DashScopeStreamingRecognitionASRClient", FakeStreamingASR)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FakeRealtimePlayer)
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        streaming_asr=True,
        on_voice_event=events.append,
    )

    lead_in = "好呀，我先给你准备一个恐龙小故事。"
    assert queued_fragments[0] == lead_in
    assert queued_fragments.count(lead_in) == 1
    assert order.index(f"enqueue:{lead_in}") < order.index("asr_finish")
    assert result.assistant_text.startswith(lead_in)
    first_queue = next(
        event
        for event in events
        if event.type == "tts_segment_queued" and event.data.get("index") == 1
    )
    assert first_queue.data["fast_path"] == "partial_lead_in"


def test_streaming_asr_empty_partial_plays_instant_ack_before_finish(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    queued_fragments: list[str] = []
    order: list[str] = []

    class FakeStreamingASR:
        last_metrics = {
            "encode_ms": 0.0,
            "request_ms": 18.0,
            "total_stream_ms": 650.0,
            "engine": "dashscope_streaming_recognition",
            "model": "paraformer-realtime-v2",
            "frames": 2.0,
            "bytes": 18.0,
        }

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def start_background(self) -> None:
            pass

        def send_audio_frame(self, _frame: bytes) -> None:
            pass

        def partial_text(self) -> str:
            return ""

        def finish(self) -> str:
            order.append("asr_finish")
            return "你好星宝"

        def cancel(self) -> None:
            pass

    class FakeRealtimePlayer:
        sample_rate = 22050

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del settings, voice_profile, output_device, interrupt_event
            self.audio_started = False
            self.on_stream_start = on_stream_start
            self.on_audio_start = on_audio_start
            self.on_stream_done = on_stream_done

        def start(self) -> None:
            if self.on_stream_start is not None:
                self.on_stream_start()

        def enqueue(self, text: str) -> None:
            order.append(f"enqueue:{text}")
            queued_fragments.append(text)
            if not self.audio_started and self.on_audio_start is not None:
                self.audio_started = True
                self.on_audio_start(320)

        def close(self) -> None:
            if self.on_stream_done is not None:
                self.on_stream_done(320, 0.01)

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del system_prompt, history
            assert user_text == "你好星宝"
            yield "你好，"
            yield "我在。"

    def fake_capture_utterance_vad(**kwargs: Any):
        callback = kwargs.get("audio_frame_callback")
        assert callback is not None
        callback(b"pcm-frame")
        return wav_path, {"utterance_ms": 600.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.DashScopeStreamingRecognitionASRClient", FakeStreamingASR)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FakeRealtimePlayer)
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        streaming_asr=True,
        on_voice_event=events.append,
    )

    ack = "我听到啦。"
    assert queued_fragments[0] == ack
    assert order.index(f"enqueue:{ack}") < order.index("asr_finish")
    assert result.assistant_text.startswith(ack)
    first_queue = next(
        event
        for event in events
        if event.type == "tts_segment_queued" and event.data.get("index") == 1
    )
    assert first_queue.data["fast_path"] == "instant_ack"


def test_voice_turn_adds_story_prompt_and_memory(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(
        settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0),
        session=SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json")),
    )
    wav_path = tmp_path / "input.wav"

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "我想听一个恐龙的故事"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del history
            assert user_text == "我想听一个恐龙的故事"
            assert "当前对话场景" in system_prompt
            assert "恐龙" in system_prompt
            assert "140 到 220 个中文字符" in system_prompt
            yield "小三角龙在河边发现一串脚印。"
            yield "它知道脚印会留下动物走过的方向。"

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 900.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(no_tts=True)
    memory = app.session.memory_manager.load()

    assert "小三角龙" in result.assistant_text
    assert memory["interests"] == ["恐龙"]
    assert memory["recent_topics"] == ["恐龙"]


def test_story_request_queues_lead_in_before_llm_delta(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    order: list[str] = []
    queued_fragments: list[str] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "我想听一个恐龙的故事"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del system_prompt, history
            assert user_text == "我想听一个恐龙的故事"
            order.append("llm_started")
            yield "小三角龙在河边发现一串脚印。"
            yield "脚印会告诉我们动物走过的方向。"

    class FakeRealtimePlayer:
        sample_rate = 22050

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del settings, voice_profile, output_device, interrupt_event
            self.audio_started = False
            self.on_stream_start = on_stream_start
            self.on_audio_start = on_audio_start
            self.on_stream_done = on_stream_done

        def start(self) -> None:
            if self.on_stream_start is not None:
                self.on_stream_start()

        def enqueue(self, text: str) -> None:
            order.append(f"enqueue:{text}")
            queued_fragments.append(text)
            if not self.audio_started and self.on_audio_start is not None:
                self.audio_started = True
                self.on_audio_start(320)

        def close(self) -> None:
            if self.on_stream_done is not None:
                self.on_stream_done(320, 0.01)

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 900.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FakeRealtimePlayer)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        on_voice_event=events.append,
    )

    assert queued_fragments[0] == "好呀，我先给你准备一个恐龙小故事。"
    assert order.index("enqueue:好呀，我先给你准备一个恐龙小故事。") < order.index(
        "llm_started"
    )
    assert result.assistant_text.startswith("好呀，我先给你准备一个恐龙小故事。")
    assert "小三角龙" in result.assistant_text
    first_queue = next(
        event
        for event in events
        if event.type == "tts_segment_queued" and event.data.get("index") == 1
    )
    assert first_queue.data["fast_path"] == "lead_in"


def test_voice_turn_can_interrupt_tts_with_wake_word(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    playback_started = threading.Event()
    detector_detected = threading.Event()

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "讲一个故事"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del user_text, system_prompt, history
            yield "第一句。"
            assert playback_started.wait(timeout=1.0)
            assert detector_detected.wait(timeout=1.0)
            yield "第二句。"

    class FakeTTS:
        def synthesize(self, text: str, out_wav: Path) -> Path:
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            out_wav.write_text(text, encoding="utf-8")
            return out_wav

    class FakeBargeInDetector:
        def wait_for_wake_word(self, **_kwargs: Any) -> str:
            assert playback_started.wait(timeout=1.0)
            detector_detected.set()
            return "星宝星宝"

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 900.0}

    def fake_play_wav(
        path: Path,
        *,
        output_device: int | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> bool:
        del path, output_device
        assert interrupt_event is not None
        playback_started.set()
        assert interrupt_event.wait(timeout=1.0)
        return False

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("multimodal.audio_io.play_wav", fake_play_wav)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]
    app.tts_client = FakeTTS()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        barge_in_detector=FakeBargeInDetector(),
        on_voice_event=events.append,
    )

    assert result.tts_interrupted is True
    assert "第一句" in result.assistant_text
    assert "第二句" not in result.assistant_text
    assert "tts_interrupted" in [event.type for event in events]


def test_voice_turn_does_not_interrupt_tts_with_plain_vad_speech(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    playback_started = threading.Event()

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝星宝"

    class FakeTTS:
        def synthesize(self, text: str, out_wav: Path) -> Path:
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            out_wav.write_text(text, encoding="utf-8")
            return out_wav

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 900.0}

    def fake_play_wav(
        path: Path,
        *,
        output_device: int | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> bool:
        del path, output_device
        assert interrupt_event is not None
        playback_started.set()
        assert not interrupt_event.wait(timeout=0.05)
        return True

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("multimodal.audio_io.play_wav", fake_play_wav)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.tts_client = FakeTTS()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        on_voice_event=events.append,
    )

    assert result.tts_interrupted is False
    interrupted = [event for event in events if event.type == "tts_interrupted"]
    assert not interrupted


def test_voice_turn_starts_quick_ack_by_default(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    ack_started: list[float | None] = []
    spoken: list[str] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "再见"

    class FakeQuickAckManager:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def play_async(self, deadline_start: float | None = None) -> None:
            ack_started.append(deadline_start)

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.QuickAckManager", FakeQuickAckManager)
    monkeypatch.setattr(
        "app.speak",
        lambda text, **_kwargs: spoken.append(text) or None,
    )
    app.asr_client = FakeASR()  # type: ignore[assignment]

    result = app.run_voice_once(on_voice_event=events.append)

    assert result.end_session is True
    assert ack_started
    assert spoken == ["好的，星宝先安静等你。想继续聊的时候，再叫我一声星宝星宝。"]
    assert "quick_ack_started" in [event.type for event in events]


def test_voice_turn_can_disable_quick_ack_explicitly(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    ack_started: list[bool] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "再见"

    class FakeQuickAckManager:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def play_async(self, deadline_start: float | None = None) -> None:
            del deadline_start
            ack_started.append(True)

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.QuickAckManager", FakeQuickAckManager)
    monkeypatch.setattr("app.speak", lambda *_args, **_kwargs: None)
    app.asr_client = FakeASR()  # type: ignore[assignment]

    app.run_voice_once(no_quick_ack=True, on_voice_event=events.append)

    assert ack_started == []
    assert "quick_ack_started" not in [event.type for event in events]


def test_voice_turn_can_stream_realtime_tts_text(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    queued_fragments: list[str] = []
    closed: list[bool] = []
    started: list[bool] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝，你好"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            assert user_text == "星宝，你好"
            assert system_prompt
            assert history == []
            yield "你好，"
            yield "我在"
            yield "呢。"

    class FakeRealtimePlayer:
        sample_rate = 22050

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del settings, voice_profile, output_device, interrupt_event
            self.on_stream_start = on_stream_start
            self.on_audio_start = on_audio_start
            self.on_stream_done = on_stream_done
            if self.on_stream_start is not None:
                self.on_stream_start()

        def start(self) -> None:
            started.append(True)

        def enqueue(self, text: str) -> None:
            queued_fragments.append(text)
            if len(queued_fragments) == 1 and self.on_audio_start is not None:
                self.on_audio_start(320)

        def close(self) -> None:
            closed.append(True)
            if self.on_stream_done is not None:
                self.on_stream_done(960, 0.12)

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FakeRealtimePlayer)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        on_voice_event=events.append,
    )

    assert result.assistant_text == "你好，我在呢。"
    assert started == [True]
    assert queued_fragments == ["你好，", "我在呢。"]
    assert closed == [True]
    event_types = [event.type for event in events]
    assert "tts_stream_started" in event_types
    assert "tts_stream_prewarmed" in event_types
    assert "tts_stream_audio_started" in event_types
    assert "tts_stream_finished" in event_types
    assert "llm_stream_finished" in event_types
    assert "playback_finished" in event_types
    audio_events = [event for event in events if event.type == "tts_stream_audio_started"]
    assert "first_audio_elapsed_ms" in audio_events[-1].data


def test_realtime_tts_prewarm_runs_alongside_llm(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    order: list[str] = []
    prewarm_started = threading.Event()
    llm_started = threading.Event()

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            assert prewarm_started.wait(timeout=1.0)
            order.append("asr_done")
            return "星宝，你好"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del user_text, system_prompt, history
            order.append("llm_started")
            llm_started.set()
            yield "你好，"
            yield "我在。"

    class SlowPrewarmPlayer:
        sample_rate = 22050
        audio_started = False

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del settings, voice_profile, output_device, interrupt_event
            self.on_stream_start = on_stream_start
            self.on_audio_start = on_audio_start
            self.on_stream_done = on_stream_done

        def start(self) -> None:
            order.append("prewarm_start")
            prewarm_started.set()
            assert llm_started.wait(timeout=1.0)
            if self.on_stream_start is not None:
                self.on_stream_start()
            order.append("prewarm_done")

        def enqueue(self, text: str) -> None:
            order.append(f"enqueue:{text}")
            if not self.audio_started and self.on_audio_start is not None:
                self.audio_started = True
                self.on_audio_start(320)

        def close(self) -> None:
            if self.on_stream_done is not None:
                self.on_stream_done(320, 0.01)

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", SlowPrewarmPlayer)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(no_quick_ack=True, realtime_tts=True)

    assert result.assistant_text == "你好，我在。"
    assert order.index("prewarm_start") < order.index("asr_done")
    assert order.index("llm_started") < order.index("prewarm_done")


def test_realtime_tts_falls_back_before_audio_starts(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    queued_realtime: list[str] = []
    queued_fallback: list[str] = []
    stream_calls: list[int] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝，你好"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del user_text, system_prompt, history
            stream_calls.append(1)
            yield "你好，"
            yield "我在。"

    class FailingRealtimePlayer:
        sample_rate = 22050
        audio_started = False

        def __init__(
            self,
            *,
            settings: AppSettings,
            voice_profile=None,
            output_device: int | None = None,
            on_stream_start=None,
            on_audio_start=None,
            on_stream_done=None,
            interrupt_event=None,
        ) -> None:
            del (
                settings,
                voice_profile,
                output_device,
                on_audio_start,
                on_stream_done,
                interrupt_event,
            )
            if on_stream_start is not None:
                on_stream_start()

        def enqueue(self, text: str) -> None:
            queued_realtime.append(text)
            raise RuntimeError("dashscope SDK missing")

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeSentencePlayer:
        def __init__(self, **kwargs: Any) -> None:
            self.on_segment_start = kwargs.get("on_segment_start")
            self.on_segment_done = kwargs.get("on_segment_done")
            self.on_synthesis_start = kwargs.get("on_synthesis_start")
            self.on_synthesis_done = kwargs.get("on_synthesis_done")
            self.index = 0

        def enqueue(self, text: str) -> None:
            self.index += 1
            queued_fallback.append(text)
            if self.on_synthesis_start is not None:
                self.on_synthesis_start(text, self.index)
            if self.on_synthesis_done is not None:
                self.on_synthesis_done(text, self.index, None, 0.01)
            if self.on_segment_start is not None:
                self.on_segment_start(text, self.index)
            if self.on_segment_done is not None:
                self.on_segment_done(text, self.index)

        def close(self) -> None:
            pass

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FailingRealtimePlayer)
    monkeypatch.setattr("app.StreamingSpeechPlayer", FakeSentencePlayer)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        on_voice_event=events.append,
    )

    assert result.assistant_text == "你好，我在。"
    assert queued_realtime == ["你好，"]
    assert queued_fallback == ["你好，我在。"]
    assert len(stream_calls) == 1
    failed_events = [event for event in events if event.type == "tts_stream_failed"]
    assert failed_events
    assert failed_events[-1].data["fallback"] is True
    assert failed_events[-1].data["audio_started"] is False


def test_realtime_tts_prewarm_failure_falls_back(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"
    queued_fallback: list[str] = []

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "星宝，你好"

    class FakeLLM:
        def stream_reply(
            self,
            user_text: str,
            system_prompt: str,
            history: list[dict[str, str]] | None = None,
        ):
            del system_prompt, history
            assert user_text == "星宝，你好"
            yield "你好，"
            yield "我在。"

    class FailingPrewarmPlayer:
        sample_rate = 22050
        audio_started = False

        def __init__(self, **_kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("tts prewarm failed")

    class FakeSentencePlayer:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def enqueue(self, text: str) -> None:
            queued_fallback.append(text)

        def close(self) -> None:
            pass

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 800.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    monkeypatch.setattr("app.RealtimeStreamingSpeechPlayer", FailingPrewarmPlayer)
    monkeypatch.setattr("app.StreamingSpeechPlayer", FakeSentencePlayer)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(
        no_quick_ack=True,
        realtime_tts=True,
        on_voice_event=events.append,
    )

    assert result.assistant_text == "你好，我在。"
    assert queued_fallback == ["你好，我在。"]
    failed_events = [event for event in events if event.type == "tts_stream_failed"]
    assert failed_events[0].data["phase"] == "recording_prewarm"
    assert failed_events[-1].data["fallback"] is True


def test_normalize_asr_text_repairs_common_companion_name_errors() -> None:
    assert normalize_asr_text("新宝新宝，你好") == "星宝星宝，你好"
    assert normalize_asr_text("星豹，你在吗") == "星宝，你在吗"
    assert normalize_asr_text("心包，我想讲故事") == "星宝，我想讲故事"


def test_normalize_asr_text_redirects_wan_long_homophones_to_brachiosaurus() -> None:
    assert normalize_asr_text("帮我找万龙的图片") == "帮我找腕龙的图片"
    assert normalize_asr_text("万隆长什么样") == "腕龙长什么样"
    assert normalize_asr_text("wan long 长什么样") == "腕龙长什么样"


def test_manual_conversation_stop_interrupts_active_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    import app as app_module

    stopped_guards: list[bool] = []
    monkeypatch.setattr(app_module._TTSBargeInGuard, "stop_all", lambda: stopped_guards.append(True))
    monkeypatch.setattr(app_module, "interrupt_active_realtime_playback", lambda: True)

    result = XingbaoApp().request_conversation_stop()

    assert stopped_guards == [True]
    assert result["tts_interrupted"] is True


def test_sanitize_tts_text_removes_visual_noise() -> None:
    assert sanitize_tts_text("你好✨\n小朋友") == "你好 小朋友"


def test_voice_prompt_rate_clamps_to_supported_tts_range() -> None:
    assert _voice_prompt_rate(0.8) == 0.8
    assert _voice_prompt_rate("not-a-rate") == 1.0
    assert _voice_prompt_rate(0.1) == 0.5
    assert _voice_prompt_rate(3.0) == 2.0


def test_camera_query_prompt_uses_a_dedicated_slow_voice_profile(monkeypatch) -> None:
    created: list[Any] = []

    class FakeRealtimeHandle:
        def __init__(self, **kwargs: Any) -> None:
            self.voice_profile = kwargs["voice_profile"]
            self.enqueued: list[str] = []
            created.append(self)

        def ensure_started(self, **_kwargs: Any) -> bool:
            return True

        def enqueue(self, text: str) -> None:
            self.enqueued.append(text)

        def close(self) -> None:
            pass

        def close_quietly(self) -> None:
            pass

    monkeypatch.setattr("app._RealtimeTTSHandle", FakeRealtimeHandle)
    companion = XingbaoApp()
    companion._speak_realtime_query_prompt(
        "稍等一小会儿，让我仔细看一看。",
        rate=0.8,
        output_device=None,
        pipeline=VoiceInteractionPipeline(),
        interrupt_event=None,
    )

    assert created[0].voice_profile.rate == 0.8
    assert created[0].enqueued == ["稍等一小会儿，让我仔细看一看。"]


def test_sanitize_tts_text_drops_punctuation_only_fragment() -> None:
    assert sanitize_tts_text("？") == ""
    assert sanitize_tts_text("!!!") == ""


def test_sanitize_tts_stream_delta_removes_visual_noise_without_waiting_for_sentence() -> None:
    assert sanitize_tts_stream_delta("✨，我在\n") == "，我在"


def test_split_realtime_tts_chunks_keeps_short_fragments_together() -> None:
    chunks, pending = split_realtime_tts_chunks("我在桌子里转着小圈圈")

    assert chunks == []
    assert pending == "我在桌子里转着小圈圈"

    chunks, pending = split_realtime_tts_chunks(pending + "呢！")

    assert chunks == ["我在桌子里转着小圈圈呢！"]
    assert pending == ""


def test_split_realtime_tts_chunks_flushes_phrase_boundary() -> None:
    chunks, pending = split_realtime_tts_chunks("你好，")

    assert chunks == ["你好，"]
    assert pending == ""


def test_split_streaming_segments_treats_tilde_as_sentence_boundary() -> None:
    segments, pending = split_streaming_segments("我在桌子里眨眼睛等你来玩呢～小朋友想一起做什么呀")

    assert segments == ["我在桌子里眨眼睛等你来玩呢～"]
    assert pending == "小朋友想一起做什么呀"
