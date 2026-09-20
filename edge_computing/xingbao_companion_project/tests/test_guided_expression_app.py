from pathlib import Path

import pytest

from app import (
    GUIDED_EXPRESSION_TTS_CACHE_FILES,
    XingbaoApp,
    _dispatch_guided_post_tts_arm_action,
    _run_finals_post_high_five_showcase,
)
from core.guided_expression_flow import (
    IDLE,
    WAIT_DRAWING_CONSENT,
    WAIT_HIGH_LEAVES_CONFIRMATION,
    WAIT_RECAST,
)
from core.memory import MemoryManager
from core.session import SessionManager


def _app(tmp_path: Path) -> XingbaoApp:
    return XingbaoApp(
        session=SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))
    )


def test_app_uses_new_finals_short_script_by_default(tmp_path: Path) -> None:
    app = _app(tmp_path)
    opening = app.handle_guided_expression_text("我叫小宇，我喜欢恐龙")
    assert opening is not None
    assert opening.text == "小宇你好，我记住你喜欢恐龙啦。你最喜欢哪一种呢？"

    leaf_prompt = app.handle_guided_expression_text("有一种龙特别大，但是不知道怎么说")
    assert leaf_prompt is not None
    assert leaf_prompt.scene == "dinosaur_short_leaf_prompt"
    assert "霸王龙" not in leaf_prompt.text
    assert app.guided_expression_flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


def test_app_short_script_updates_only_safe_canonical_memory(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.handle_guided_expression_text("我叫小宇，我喜欢恐龙")
    app.handle_guided_expression_text("那个龙身体很大，我说不清楚")
    app.handle_guided_expression_text("对，可以吃到高高的树叶")

    completed = app.handle_guided_expression_text(
        "我喜欢万龙，因为它身体很大，脖子很长"
    )

    assert completed is not None
    assert completed.post_tts_arm_action == "high_five"
    assert completed.end_session is True
    memory = app.session.memory_manager.load()
    assert "腕龙" in memory["interests"]
    assert "万龙" not in str(memory)
    assert "小宇" not in str(memory)
    assert app.guided_expression_flow.snapshot().stage == WAIT_DRAWING_CONSENT


def test_app_advances_after_any_complete_final_asr_turn(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.handle_guided_expression_text("我叫小宇，我喜欢恐龙")
    app.handle_guided_expression_text("有一种恐龙特别大，我不知道怎么说")
    app.handle_guided_expression_text("对")

    completed = app.handle_guided_expression_text("我喜欢腕龙，因为它身体很大")

    assert completed is not None
    assert completed.post_tts_arm_action == "high_five"
    assert app.guided_expression_flow.snapshot().stage == WAIT_DRAWING_CONSENT


def test_app_does_not_intercept_unmatched_normal_chat(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.handle_guided_expression_text("今天想听一个星星故事") is None


def test_old_script_tts_lines_are_disabled_and_new_files_are_distinct() -> None:
    assert "特别特别大的……会不会是霸王龙呀？" not in GUIDED_EXPRESSION_TTS_CACHE_FILES
    assert "没关系，我们慢慢说。它能吃到高高的树叶吗？" in GUIDED_EXPRESSION_TTS_CACHE_FILES
    assert all("finals" in filename for filename in GUIDED_EXPRESSION_TTS_CACHE_FILES.values())


def test_completed_reply_dispatches_high_five_only_after_tts_gate() -> None:
    seen: list[str] = []

    def fake_dispatcher(text: str) -> dict[str, object]:
        seen.append(text)
        return {"matched": True, "queued": True, "arm_action": "high_five"}

    disabled = _dispatch_guided_post_tts_arm_action(
        "high_five",
        enabled=False,
        dispatcher=fake_dispatcher,
    )
    assert disabled["queued"] is False
    assert seen == []

    dispatched = _dispatch_guided_post_tts_arm_action(
        "high_five",
        enabled=True,
        dispatcher=fake_dispatcher,
    )
    assert dispatched["queued"] is True
    assert seen == ["击掌"]


def test_unknown_post_tts_action_never_reaches_dispatcher() -> None:
    def fail_dispatcher(_text: str) -> dict[str, object]:
        raise AssertionError("unknown action must not be dispatched")

    result = _dispatch_guided_post_tts_arm_action(
        "vision_high_five_11",
        enabled=True,
        dispatcher=fail_dispatcher,
    )
    assert result == {"matched": False, "queued": False, "arm_action": ""}


def test_post_high_five_showcase_waits_for_active_then_completed_session() -> None:
    now = [0.0]
    spoken: list[str] = []
    ready: list[str] = []
    statuses = iter(
        [
            {
                "ok": True,
                "hand_recognition_enabled": True,
                "generation": 1,
                "follow_start_count": 1,
                "follow_redirect_count": 0,
                "last_follow_seconds_ago": 0.0,
            },
            {
                "ok": True,
                "hand_recognition_enabled": True,
                "generation": 1,
                "follow_start_count": 1,
                "follow_redirect_count": 1,
                "last_follow_seconds_ago": 1.3,
            },
            {
                "ok": True,
                "hand_recognition_enabled": False,
                "generation": 2,
                "follow_start_count": 1,
                "follow_redirect_count": 1,
                "last_follow_seconds_ago": 1.6,
            },
        ]
    )
    result = _run_finals_post_high_five_showcase(
        baseline_status={
            "ok": True,
            "hand_recognition_enabled": False,
            "generation": 0,
            "follow_start_count": 0,
            "follow_redirect_count": 0,
        },
        dispatch_result={
            "queued": True,
            "expected_duration_seconds": 24,
            "fallback_expected_duration_seconds": 9,
        },
        speak_line=spoken.append,
        on_ready_for_drawing=lambda: ready.append("drawing_consent"),
        status_reader=lambda: next(statuses),
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    assert result["completion_reason"] == "vision_session_completed"
    assert result["redirect_feedback_spoken"] is True
    assert result["stable_feedback_spoken"] is True
    assert spoken == [
        "你换位置了，我来追你！",
        "我们稳定啦，来击一个掌！",
        "看到你啦！你换了位置，我也会重新找你。我们配合成功！",
        "小宇，你刚才把腕龙说得这么清楚，要不要把它画下来呀？",
    ]
    assert ready == ["drawing_consent"]
    assert now[0] == pytest.approx(1.2)


def test_post_high_five_showcase_uses_bounded_fallback_when_vision_never_starts() -> None:
    now = [0.0]

    result = _run_finals_post_high_five_showcase(
        baseline_status={
            "ok": True,
            "hand_recognition_enabled": False,
            "generation": 0,
            "follow_start_count": 0,
            "follow_redirect_count": 0,
        },
        dispatch_result={
            "queued": True,
            "expected_duration_seconds": 24,
            "fallback_expected_duration_seconds": 9,
        },
        status_reader=lambda: {
            "ok": True,
            "hand_recognition_enabled": False,
            "generation": 0,
        },
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    assert result["completion_reason"] == "vision_unavailable_fallback_elapsed"
    assert now[0] == pytest.approx(9.8)


def test_scripted_followups_only_open_the_reviewed_drawing_and_memory_turns(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.request_scripted_followup("drawing_consent")["ok"] is False
    assert app.request_scripted_followup("memory_recall")["ok"] is False

    app.handle_guided_expression_text("我叫小宇，我喜欢恐龙")
    app.handle_guided_expression_text("有一种恐龙特别大，我不知道怎么说")
    app.handle_guided_expression_text("对")
    app.handle_guided_expression_text("我喜欢腕龙，因为它身体大，脖子长")
    assert app.guided_expression_flow.snapshot().stage == WAIT_DRAWING_CONSENT
    assert app.request_scripted_followup("drawing_consent") == {
        "ok": True,
        "kind": "drawing_consent",
    }
    assert app._take_scripted_followup_request() == "drawing_consent"

    accepted = app.handle_guided_expression_text("好呀")
    assert accepted is not None and accepted.scene == "dinosaur_drawing_accepted"
    app._scripted_memory_recall_armed.set()
    assert app.request_scripted_followup("memory_recall") == {
        "ok": True,
        "kind": "memory_recall",
    }
    assert app._take_scripted_followup_request() == "memory_recall"
