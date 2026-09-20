"""Application orchestration for Xingbao Companion."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.arm_action_bridge import dispatch_voice_arm_action, get_hand_recognition_status
from core.board_ui_client import BoardUIClient
from core.coordinator import CoordinationPlan, XingbaoCoordinator
from core.color_block_events import color_block_command_event, color_block_result_event
from core.expression import ExpressionDispatcher, ExpressionOutput
from core.game_status_query import resolve_game_status_query
from core.game_speech_cache import GameSpeechCache
from core.guided_expression_flow import (
    IDLE,
    WAIT_DRAWING_CONSENT,
    DinosaurExpressionFlow,
    GuidedExpressionReply,
)
from core.growth_guidance import GrowthContext, GrowthGuidanceEngine, GrowthGuidancePlan
from core.kids_visual_tools_bridge import get_visual_tool_registry, launch_visual_tools
from core.listening_loop import ListeningLoop
from core.network import NetworkClient, enforce_direct_network_env
from core.output_adapters import OutputAdapterSet, OutputTrace
from core.serial_bridge import SerialBridge
from core.scene_animation import (
    SceneMarkerStreamFilter,
    ScenePriorityController,
    SceneTurnSelector,
    scene_catalog_prompt,
)
from core.session import SessionManager
from core.settings import AppSettings
from core.voice_events import VoiceEventHandler, VoiceInteractionPipeline
from core.voice_profiles import load_voice_profiles, select_voice_profile
from src.game_api import GameCommandAdapter
from core.color_block_game import ColorBlockGame
from core.color_block_voice import parse_color_block_voice_command
from core.color_block_ui import launch_color_block_game
from intelligence.llm_client import DashScopeLLMClient
from multimodal.asr_client import (
    DashScopeStreamingRecognitionASRClient,
    EmptyRecognitionResult,
    SherpaOnnxASRClient,
    SherpaOnnxStreamingASRClient,
)
from multimodal.asr_wake_word import ASRWakeWordDetector
from multimodal.audio_io import (
    AudioDeviceConfig,
    BOARD_APLAY_OUTPUT_DEVICE,
    QuickAckManager,
    RealtimeStreamingSpeechPlayer,
    StreamingSpeechPlayer,
    generate_chime_wav,
    import_audio_libs,
    interrupt_active_realtime_playback,
    list_devices,
    play_wav,
    speak,
    speak_interruptible_direct,
    wait_for_audio_playback_idle,
)
from multimodal.tts_client import DashScopeTTSClient
from multimodal.vad import (
    NoSpeechTimeout,
    VADConfig,
    capture_utterance_vad,
)
from multimodal.webrtc_aec3 import Aec3Processor, aec3_enabled, log_aec3, reference_bus
from multimodal.wake_word import OpenWakeWordDetector, WakeWordConfig


WAKE_ACK_CACHE_ITEMS = (
    ("我在呢。", "wake_ack_im_here.wav"),
    ("你好呀，小朋友。", "wake_ack_hello_child.wav"),
    ("我在呢，想说什么？", "wake_ack_open_question.wav"),
)
# During speech playback, speaker leakage is more likely to resemble the wake
# phrase.  Use a separate, stricter KWS detector for barge-in and keep the
# normal idle wake detector at its configured threshold.
TTS_BARGE_KWS_THRESHOLD = 0.8

# The playback lock already guarantees that the previous audio process has
# finished. Keep only a short hardware-tail guard before opening the mic.
FOLLOWUP_AUDIO_SETTLE_SECONDS = 0.08

# The finals showcase does not guess that a variable hand-follow interaction
# lasts exactly ten seconds.  It observes the local high-level vision gate,
# retains a bounded fallback for an unavailable vision service, and never
# reads frames or raw arm state.
FINALS_HIGH_FIVE_ACTIVATION_TIMEOUT_SECONDS = 4.0
FINALS_HIGH_FIVE_COMPLETION_TIMEOUT_SECONDS = 27.0
FINALS_HIGH_FIVE_FALLBACK_SECONDS = 9.0

DINOSAUR_SCRIPT_JSON_TYPE = "xingbao"
DINOSAUR_SCRIPT_JSON_ACTION = "dinosaur_script"
# The reviewed dinosaur presentation is retired.  Keep its old implementation
# only as historical code; no voice, UI, vision, or operator path may enter it.
DINOSAUR_SCRIPT_ENABLED = False
FINALS_HIGH_FIVE_SETTLE_SECONDS = 0.8
FINALS_HIGH_FIVE_POLL_SECONDS = 0.20
FINALS_HIGH_FIVE_STABLE_SECONDS = 1.2
FINALS_GUIDED_RESPONSE_DELAY_SECONDS = 0.45
FINALS_HIGH_FIVE_REDIRECT_TEXT = "你换位置了，我来追你！"
FINALS_HIGH_FIVE_STABLE_TEXT = "我们稳定啦，来击一个掌！"
FINALS_HIGH_FIVE_SUCCESS_TEXT = "看到你啦！你换了位置，我也会重新找你。我们配合成功！"
FINALS_DRAWING_PROMPT_TEXT = "小宇，你刚才把腕龙说得这么清楚，要不要把它画下来呀？"


# Deterministic lines from the reviewed dinosaur demonstration.  These WAV
# files are prepared before the demo so scripted responses never depend on
# realtime TTS or the network, while free conversation keeps realtime TTS.
GUIDED_EXPRESSION_TTS_CACHE_FILES = {
    "小宇你好，我记住你喜欢恐龙啦。你最喜欢哪一种呢？": "dino_finals_interest_xiaoyu.wav",
    "没关系，我们慢慢说。它能吃到高高的树叶吗？": "dino_finals_leaf_prompt.wav",
    "可能是腕龙。试着说：我喜欢腕龙，因为它身体大、脖子长，还能吃到高高的树叶。": "dino_finals_recast.wav",
    "你自己说得真完整！我也记住你喜欢腕龙啦。来，击掌庆祝一下吧！": "dino_finals_completed_high_five.wav",
    "特点都说对啦，再把“我喜欢腕龙”也连起来说一遍吧。": "dino_finals_retry_preference.wav",
    "你已经说出喜欢腕龙啦，再说说它的身体是什么样的吧。": "dino_finals_retry_body.wav",
    "你已经说出它身体很大啦，再说说它的脖子是什么样的吧。": "dino_finals_retry_neck.wav",
    FINALS_HIGH_FIVE_REDIRECT_TEXT: "dino_finals_high_five_redirect_v2.wav",
    FINALS_HIGH_FIVE_STABLE_TEXT: "dino_finals_high_five_stable_v2.wav",
    FINALS_HIGH_FIVE_SUCCESS_TEXT: "dino_finals_high_five_success.wav",
    FINALS_DRAWING_PROMPT_TEXT: "dino_finals_drawing_prompt.wav",
    "那我们去百宝箱画一画吧。": "dino_finals_drawing_accepted.wav",
    "记得呀，你喜欢身体很大、脖子很长的腕龙。": "dino_finals_memory_recall.wav",
}


def _dispatch_guided_post_tts_arm_action(
    arm_action: str,
    *,
    enabled: bool,
    dispatcher: Callable[[str], dict[str, Any]] = dispatch_voice_arm_action,
) -> dict[str, Any]:
    """Dispatch one reviewed action only after a complete guided reply."""
    if not enabled or str(arm_action or "").strip() != "high_five":
        return {"matched": False, "queued": False, "arm_action": ""}
    return dispatcher("击掌")


def _read_high_five_status_quietly(
    reader: Callable[[], dict[str, Any]] = get_hand_recognition_status,
) -> dict[str, Any] | None:
    try:
        result = reader()
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) and result.get("ok") else None


def _run_finals_post_high_five_showcase(
    *,
    baseline_status: dict[str, Any] | None,
    dispatch_result: dict[str, Any],
    speak_line: Callable[[str], None] | None = None,
    on_ready_for_drawing: Callable[[], Any] | None = None,
    status_reader: Callable[[], dict[str, Any]] = get_hand_recognition_status,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Narrate one bounded high-five, then invite the child to draw."""
    started_at = clock()
    baseline_generation: int | None = None
    baseline_enabled = False
    baseline_follow_starts = 0
    baseline_follow_redirects = 0
    if isinstance(baseline_status, dict):
        try:
            baseline_generation = int(baseline_status.get("generation"))
        except (TypeError, ValueError):
            baseline_generation = None
        baseline_enabled = bool(baseline_status.get("hand_recognition_enabled"))
        try:
            baseline_follow_starts = int(baseline_status.get("follow_start_count") or 0)
            baseline_follow_redirects = int(
                baseline_status.get("follow_redirect_count") or 0
            )
        except (TypeError, ValueError):
            baseline_follow_starts = 0
            baseline_follow_redirects = 0

    saw_active_session = baseline_enabled
    playful_redirect_spoken = False
    stable_hand_spoken = False
    completion_reason = "completion_timeout"
    activation_timeout = FINALS_HIGH_FIVE_ACTIVATION_TIMEOUT_SECONDS
    completion_timeout = max(
        activation_timeout,
        min(
            FINALS_HIGH_FIVE_COMPLETION_TIMEOUT_SECONDS,
            float(
                dispatch_result.get("expected_duration_seconds")
                or FINALS_HIGH_FIVE_COMPLETION_TIMEOUT_SECONDS
            )
            + 3.0,
        ),
    )
    fallback_seconds = max(
        0.0,
        float(
            dispatch_result.get("fallback_expected_duration_seconds")
            or FINALS_HIGH_FIVE_FALLBACK_SECONDS
        ),
    )

    while True:
        elapsed = clock() - started_at
        status = _read_high_five_status_quietly(status_reader)
        if status is not None:
            enabled = bool(status.get("hand_recognition_enabled"))
            try:
                generation = int(status.get("generation"))
            except (TypeError, ValueError):
                generation = None
            if enabled and (
                baseline_generation is None
                or generation is None
                or generation > baseline_generation
                or baseline_enabled
            ):
                saw_active_session = True
            try:
                follow_starts = int(status.get("follow_start_count") or 0)
                follow_redirects = int(status.get("follow_redirect_count") or 0)
                last_follow_seconds_ago = float(
                    status.get("last_follow_seconds_ago") or 0.0
                )
            except (TypeError, ValueError):
                follow_starts = baseline_follow_starts
                follow_redirects = baseline_follow_redirects
                last_follow_seconds_ago = 0.0
            if (
                follow_redirects > baseline_follow_redirects
                and not playful_redirect_spoken
            ):
                if speak_line is not None:
                    speak_line(FINALS_HIGH_FIVE_REDIRECT_TEXT)
                playful_redirect_spoken = True
            has_stable_follow = (
                follow_starts > baseline_follow_starts
                or follow_redirects > baseline_follow_redirects
            )
            if (
                has_stable_follow
                and not stable_hand_spoken
                and last_follow_seconds_ago >= FINALS_HIGH_FIVE_STABLE_SECONDS
            ):
                if speak_line is not None:
                    speak_line(FINALS_HIGH_FIVE_STABLE_TEXT)
                stable_hand_spoken = True
            completed_between_polls = (
                baseline_generation is not None
                and generation is not None
                and generation >= baseline_generation + 2
            )
            if not enabled and (saw_active_session or completed_between_polls):
                completion_reason = "vision_session_completed"
                break

        if elapsed >= completion_timeout:
            break
        if not saw_active_session and elapsed >= activation_timeout:
            remaining_fallback = max(0.0, fallback_seconds - elapsed)
            if remaining_fallback:
                sleep(remaining_fallback)
            completion_reason = "vision_unavailable_fallback_elapsed"
            break
        sleep(FINALS_HIGH_FIVE_POLL_SECONDS)

    sleep(FINALS_HIGH_FIVE_SETTLE_SECONDS)
    if speak_line is not None:
        speak_line(FINALS_HIGH_FIVE_SUCCESS_TEXT)
        speak_line(FINALS_DRAWING_PROMPT_TEXT)
    followup_result = on_ready_for_drawing() if on_ready_for_drawing is not None else None
    return {
        "completion_reason": completion_reason,
        "redirect_feedback_spoken": playful_redirect_spoken,
        "stable_feedback_spoken": stable_hand_spoken,
        "drawing_followup": followup_result,
    }


def _start_finals_post_high_five_showcase(
    *,
    baseline_status: dict[str, Any] | None,
    dispatch_result: dict[str, Any],
    speak_line: Callable[[str], None] | None = None,
    on_ready_for_drawing: Callable[[], Any] | None = None,
) -> bool:
    if not dispatch_result.get("queued"):
        return False
    threading.Thread(
        target=_run_finals_post_high_five_showcase,
        kwargs={
            "baseline_status": baseline_status,
            "dispatch_result": dict(dispatch_result),
            "speak_line": speak_line,
            "on_ready_for_drawing": on_ready_for_drawing,
        },
        name="finals-post-high-five-showcase",
        daemon=True,
    ).start()
    return True


def _guided_expression_session_end_reason(reply: GuidedExpressionReply) -> str:
    """Keep the reviewed presentation handoffs out of the generic end banner."""
    if not reply.end_session:
        return ""
    if reply.post_tts_arm_action == "high_five":
        return "guided_expression_high_five"
    if reply.scene in {"dinosaur_drawing_accepted", "dinosaur_drawing_declined"}:
        return "guided_expression_touch_handoff"
    if reply.scene == "dinosaur_interest_recalled":
        return "guided_expression_memory_recalled"
    return "guided_expression_complete"


# Fixed, presentation-safe replies that must not depend on a live model or
# camera result.  Their trigger predicates are deliberately narrow.
FIXED_DEMO_TTS_CACHE_FILES = {
    "你看上去很开心。": "demo_emotion_happy.wav",
}

# Fixed vision reminders use local WAV playback once prepared. Keep these
# texts identical to the coordinator's current vision responses.
VISION_TTS_CACHE_FILES = {
    "小眼睛离屏幕有点近啦，我们往后坐一点。": "vision_face_too_close.wav",
    "要不要喝一小口水？喝完我们继续。": "vision_drink_water.wav",
    "我们坐了一会儿啦，要不要站起来伸个懒腰？": "vision_sitting_too_long.wav",
    "看到你开心，星宝也很开心。": "vision_emotion_happiness.wav",
    "如果你现在有点难过，星宝在这里陪你。": "vision_emotion_sadness.wav",
    "如果你现在有点生气，我们可以先慢慢呼吸。": "vision_emotion_anger.wav",
    "哇，是不是发现了新东西？": "vision_emotion_surprise.wav",
    "如果你有点害怕，星宝在这里，我们慢慢来。": "vision_emotion_fear.wav",
}


DEMO_TTS_CACHE_FILES = {
    "hi": "demo_wake_hi.wav",
    "我在呢，今天也一起玩一会儿吧。": "demo_greeting.wav",
    **{text: filename for text, filename in WAKE_ACK_CACHE_ITEMS},
    "星宝学习桌面。": "demo_desktop_title.wav",
    "今天想和星宝聊什么？": "demo_desktop_prompt.wav",
    "我可以陪你聊天，玩小游戏，画画，专心学习，也会提醒你休息和喝水。": "demo_desktop_features.wav",
    "\u8fdb\u5165\u6e38\u620f\u5566\uff0c\u8bf7\u9009\u62e9\u4e00\u4e2a\u6e38\u620f\uff0c\u518d\u9009\u62e9\u96be\u5ea6\u3002": "demo_open_game.wav",
    "\u96be\u5ea6\u9009\u597d\u4e86\uff0c\u6211\u4eec\u5f00\u59cb\u7b2c\u4e00\u9898\u3002": "demo_difficulty_selected.wav",
    "请找到三角形在哪里。": "demo_shape_question.wav",
    "请找到圆形在哪里。": "demo_shape_circle.wav",
    "请找到正方形在哪里。": "demo_shape_square.wav",
    "请找到长方形在哪里。": "demo_shape_rectangle.wav",
    "请找到星形在哪里。": "demo_shape_star.wav",
    "请找到爱心在哪里。": "demo_shape_heart.wav",
    "请找到椭圆在哪里。": "demo_shape_oval.wav",
    "请找到椭圆形在哪里。": "demo_shape_ellipse.wav",
    "\u592a\u68d2\u4e86\uff0c\u4f60\u7b54\u5bf9\u4e86\u3002": "demo_answer_correct.wav",
    "\u6ca1\u5173\u7cfb\uff0c\u8fd9\u4e00\u9898\u6211\u4eec\u518d\u8bd5\u4e00\u6b21\u3002": "demo_answer_wrong.wav",
    "\u5c0f\u670b\u53cb\uff0c\u5e94\u8be5\u8c03\u6574\u4e00\u4e0b\u59ff\u52bf\uff0c\u79bb\u5c4f\u5e55\u7a0d\u5fae\u8fdc\u4e00\u70b9\uff0c\u4e5f\u8bb0\u5f97\u559d\u6c34\u54e6\u3002": "demo_posture_fallback.wav",
    "\u5c0f\u670b\u53cb\uff0c\u4f60\u79bb\u5c4f\u5e55\u6709\u70b9\u8fd1\uff0c\u7a0d\u5fae\u5750\u8fdc\u4e00\u70b9\uff0c\u4e5f\u8bb0\u5f97\u559d\u6c34\u54e6\u3002": "demo_posture_warning.wav",
    **FIXED_DEMO_TTS_CACHE_FILES,
    **VISION_TTS_CACHE_FILES,
    **GUIDED_EXPRESSION_TTS_CACHE_FILES,
}


@dataclass(frozen=True)
class VoiceTurnResult:
    user_text: str
    assistant_text: str
    action: dict[str, str]
    audio_path: str
    end_session: bool = False
    session_end_reason: str = ""
    tts_interrupted: bool = False
    fast_path: str = ""


class GuidedExpressionRecoveryRequested(Exception):
    """A touch recovery request superseded the audio currently being captured."""


class ConversationStopRequested(Exception):
    """A touch request ended the current wake-chat session."""


class ReadAloudPlaybackActive(Exception):
    """Desktop subtitle point-read temporarily owns microphone input."""


@dataclass(frozen=True)
class ExpressionApplyResult:
    output: dict[str, Any]
    action: dict[str, str]
    memory: dict[str, Any] | None
    tts_played: bool

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "output": self.output,
            "action": self.action,
            "tts_played": self.tts_played,
        }
        if self.memory is not None:
            result["memory"] = self.memory
        return result


@dataclass(frozen=True)
class PendingDrinkReminder:
    """One hydration prompt deferred until a conversation becomes idle."""

    text: str
    local_tts_fallback: bool
    output_device: int | None


@dataclass(frozen=True)
class CoordinationRunResult:
    """Result of one computer-side coordinated text rehearsal."""

    plan: dict[str, Any]
    applied: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    tool_launched: bool = False
    tool_launch_status: str = "not_requested"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "plan": self.plan,
            "trace": self.trace,
            "tool_launched": self.tool_launched,
            "tool_launch_status": self.tool_launch_status,
        }
        if self.applied is not None:
            result["applied"] = self.applied
        return result


class _TTSBargeInGuard:
    """Uses AEC3 speech detection (or the legacy wake word) during TTS."""

    _active_guards: set["_TTSBargeInGuard"] = set()
    _active_guards_lock = threading.Lock()

    def __init__(
        self,
        *,
        detector: Any | None,
        pipeline: VoiceInteractionPipeline,
    ) -> None:
        self.detector = detector
        self.pipeline = pipeline
        self.stop_event = threading.Event()
        self.keyword = ""
        self._threads: list[threading.Thread] = []
        self._interrupt_lock = threading.Lock()
        self._interrupted = False

    @property
    def interrupted(self) -> bool:
        return bool(self.keyword)

    def start(self) -> "_TTSBargeInGuard":
        if self._threads:
            return self

        if aec3_enabled() and self.detector is not None:
            with self._active_guards_lock:
                self._active_guards.add(self)
            thread = threading.Thread(target=self._aec3_wake_worker, daemon=True)
            self._threads.append(thread)
            thread.start()
        elif self.detector is not None:
            with self._active_guards_lock:
                self._active_guards.add(self)
            thread = threading.Thread(target=self._wake_worker, daemon=True)
            self._threads.append(thread)
            thread.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self._threads:
            thread.join(timeout=1.0)
        with self._active_guards_lock:
            self._active_guards.discard(self)

    @classmethod
    def stop_all(cls) -> None:
        """Release guards left behind by an exception during TTS/LLM work."""
        with cls._active_guards_lock:
            guards = list(cls._active_guards)
        for guard in guards:
            guard.stop()

    def _wake_worker(self) -> None:
        try:
            try:
                keyword = self.detector.wait_for_wake_word(
                    stop_event=self.stop_event,
                    announce=False,
                )
            except TypeError:
                keyword = self.detector.wait_for_wake_word()
        except Exception:
            return
        if keyword and not self.stop_event.is_set():
            self.keyword = str(keyword)
            self._interrupt(reason="wake_word", keyword=self.keyword)

    def _aec3_wake_worker(self) -> None:
        """Run the wake model on echo-reduced microphone frames during TTS."""
        processor: Aec3Processor | None = None
        try:
            delay_ms = int(_aec3_barge_env_float("XINGBAO_AEC3_DELAY_MS", 110.0, 0.0, 500.0))
            processor = Aec3Processor(delay_ms=delay_ms)
            reference_bus.register(processor)
            self.pipeline.emit(
                "aec3_kws_started",
                delay_ms=delay_ms,
            )
            log_aec3(f"kws_started delay_ms={delay_ms}")
            keyword = self.detector.wait_for_wake_word(
                stop_event=self.stop_event,
                announce=False,
                audio_frame_processor=processor.process_capture,
            )
            if keyword and not self.stop_event.is_set():
                self.keyword = str(keyword)
                log_aec3(f"kws_triggered keyword={self.keyword}")
                self._interrupt(reason="aec3_wake_word", keyword=self.keyword)
        except Exception as exc:
            log_aec3(f"kws_unavailable error={type(exc).__name__}: {exc}")
            self.pipeline.emit("aec3_kws_unavailable", error=type(exc).__name__, message=str(exc))
        finally:
            if processor is not None:
                reference_bus.unregister(processor)

    def _interrupt(self, **data: Any) -> None:
        with self._interrupt_lock:
            if self._interrupted:
                return
            self._interrupted = True
        self.stop_event.set()
        self.pipeline.emit("tts_interrupted", **data)


class _RealtimeTTSHandle:
    """Owns one realtime TTS stream that can be prewarmed before text is ready."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        voice_profile: Any,
        output_device: int | None,
        pipeline: VoiceInteractionPipeline,
        interrupt_event: threading.Event | None,
        ready_timeout_seconds: float = 7.0,
    ) -> None:
        self.settings = settings
        self.voice_profile = voice_profile
        self.output_device = output_device
        self.pipeline = pipeline
        self.interrupt_event = interrupt_event
        self.playback_started = False
        self.stream_started_at = 0.0
        self.error: BaseException | None = None
        self._started_at = 0.0
        self._start_invoked = False
        self._closed = False
        self._done = threading.Event()
        self._start_lock = threading.Lock()
        self._ready_timeout_seconds = max(0.5, float(ready_timeout_seconds))
        self._ready_timeout_reported = False
        self.player = RealtimeStreamingSpeechPlayer(
            settings=settings,
            voice_profile=voice_profile,
            output_device=output_device,
            on_stream_start=self._on_stream_start,
            on_audio_start=self._on_audio_start,
            on_stream_done=self._on_stream_done,
            interrupt_event=interrupt_event,
        )

    @property
    def audio_started(self) -> bool:
        return bool(self.player.audio_started)

    def start_background(self, *, phase: str = "prewarm", fast_path: str = "") -> None:
        with self._start_lock:
            if self._start_invoked:
                return
            self._start_invoked = True
            self._started_at = time.perf_counter()
        threading.Thread(
            target=self._start_player,
            kwargs={"phase": phase, "fast_path": fast_path},
            daemon=True,
        ).start()

    def ensure_started(self, *, phase: str = "prewarm", fast_path: str = "") -> bool:
        with self._start_lock:
            if self._start_invoked:
                return self.wait_ready()
            self._start_invoked = True
            self._started_at = time.perf_counter()
        # ``RealtimeStreamingSpeechPlayer.start`` opens a cloud stream and
        # can block in third-party networking code.  Keep that operation off
        # the voice-loop thread, then use ``wait_ready``'s bounded deadline so
        # a failed stream falls back to normal cached/batch TTS instead of
        # freezing the child-facing session.
        threading.Thread(
            target=self._start_player,
            kwargs={"phase": phase, "fast_path": fast_path},
            daemon=True,
        ).start()
        return self.wait_ready()

    def wait_ready(self) -> bool:
        if not self._done.wait(timeout=self._ready_timeout_seconds):
            if self.error is None:
                self.error = TimeoutError(
                    "Realtime TTS startup did not become ready within "
                    f"{self._ready_timeout_seconds:.1f}s."
                )
            if not self._ready_timeout_reported:
                self._ready_timeout_reported = True
                self.pipeline.emit(
                    "tts_stream_failed",
                    message=str(self.error),
                    fallback=True,
                    audio_started=self.audio_started,
                    phase="ready_timeout",
                )
            return False
        return self.error is None

    def enqueue(self, text: str) -> None:
        self.player.enqueue(text)

    def set_interrupt_event(self, interrupt_event: threading.Event | None) -> None:
        self.interrupt_event = interrupt_event
        self.player.interrupt_event = interrupt_event

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._start_invoked:
            self._done.wait(timeout=2.0)
        self.player.close()
        if self.playback_started:
            self.pipeline.emit("playback_finished", text="", index=1, streaming=True)

    def close_quietly(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _start_player(self, *, phase: str, fast_path: str = "") -> None:
        try:
            self.player.start()
            if self._closed:
                self.player.close()
                return
            data: dict[str, Any] = {
                "elapsed_ms": round((time.perf_counter() - self._started_at) * 1000, 1),
                "index": 1,
                "phase": phase,
            }
            if fast_path:
                data["fast_path"] = fast_path
            self.pipeline.emit("tts_stream_prewarmed", **data)
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            self.error = exc
            self.pipeline.emit(
                "tts_stream_failed",
                message=str(exc),
                fallback=True,
                audio_started=self.audio_started,
                phase=phase,
            )
        finally:
            self._done.set()

    def _on_stream_start(self) -> None:
        self.stream_started_at = time.perf_counter()
        self.pipeline.emit(
            "tts_stream_started",
            voice_profile_id=self.voice_profile.id,
            voice_profile_label=self.voice_profile.label,
            model=self.voice_profile.model,
            voice=self.voice_profile.voice,
            sample_rate=RealtimeStreamingSpeechPlayer.sample_rate,
        )
        self.pipeline.emit(
            "tts_synthesis_started",
            text="",
            index=1,
            streaming=True,
        )

    def _on_audio_start(self, first_chunk_bytes: int) -> None:
        self.playback_started = True
        first_audio_elapsed_ms = (
            round((time.perf_counter() - self.stream_started_at) * 1000, 1)
            if self.stream_started_at
            else 0.0
        )
        self.pipeline.emit(
            "tts_stream_audio_started",
            first_chunk_bytes=first_chunk_bytes,
            first_audio_elapsed_ms=first_audio_elapsed_ms,
            index=1,
        )
        self.pipeline.emit("playback_started", text="", index=1, streaming=True)

    def _on_stream_done(self, total_bytes: int, elapsed_seconds: float) -> None:
        self.pipeline.emit(
            "tts_stream_finished",
            total_bytes=total_bytes,
            elapsed_ms=round(elapsed_seconds * 1000, 1),
            index=1,
        )
        self.pipeline.emit(
            "tts_synthesis_finished",
            text="",
            index=1,
            audio_path="",
            elapsed_ms=round(elapsed_seconds * 1000, 1),
            streaming=True,
        )


HARD_SENTENCE_BOUNDARIES = "。！？!?～~"
SOFT_SENTENCE_BOUNDARIES = "，、；;：:"
STREAMING_SOFT_LIMIT_CHARS = 20
REALTIME_TTS_SOFT_LIMIT_CHARS = 12
REALTIME_TTS_FORCE_LIMIT_CHARS = 18
REALTIME_TTS_MIN_CHARS = 3
ASR_COMPANION_NAME_VARIANTS = (
    "新宝",
    "欣宝",
    "兴宝",
    "心宝",
    "醒宝",
    "信宝",
    "星保",
    "星堡",
    "星豹",
    "星包",
    "星爆",
    "星抱",
    "星鲍",
    "行宝",
    "幸宝",
    "姓宝",
    "新保",
    "新堡",
    "新豹",
    "新包",
    "新爆",
    "新抱",
    "心保",
    "心堡",
    "心豹",
    "心包",
    "心爆",
    "心抱",
)

# The child frequently asks for the dinosaur 腕龙, while ASR hears the same
# syllables as several ordinary character combinations.  This is intentionally
# global at the transcript boundary, as requested, before any intent routing.
ASR_BRACHIOSAURUS_VARIANTS = (
    "万龙", "万隆", "腕隆", "湾龙", "玩龙", "完龙", "皖龙", "万笼", "万聋",
)
TTS_DROP_CHARS = "✨⭐🌟💫🙂😀😄😁😆😉😊🥰😍🤖"


class XingbaoApp:
    """Coordinates session, model clients, audio, and optional board output."""

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        session: SessionManager | None = None,
        voice_profile_id: str | None = None,
    ) -> None:
        self.settings = settings or AppSettings.load()
        if self.settings.proxy_mode == "none":
            # DashScope streaming ASR/TTS use the SDK's WebSocket transport,
            # not NetworkClient.  Clear inherited proxy variables before any
            # of those clients are lazily created.
            enforce_direct_network_env()
        self.session = session or SessionManager()
        self.voice_profile = select_voice_profile(self.settings, voice_profile_id)
        self.game_speech_cache = GameSpeechCache(voice_id=self.voice_profile.id)
        self._game_prefetch_lock = threading.Lock()
        self._game_prefetch_pending: set[str] = set()
        self._network_client: NetworkClient | None = None
        self._asr_client: Any | None = None
        self._llm_client: Any | None = None
        self._tts_client: Any | None = None
        self._growth_guidance_engine: GrowthGuidanceEngine | None = None
        self.guided_expression_flow = DinosaurExpressionFlow()
        self._coordinator: XingbaoCoordinator | None = None
        self._external_tts_lock = threading.Lock()
        self._external_read_aloud_lock = threading.Lock()
        self._external_read_aloud_interrupt: threading.Event | None = None
        self._external_game_speech_lock = threading.Lock()
        self._external_game_speech_interrupt: threading.Event | None = None
        self._external_auxiliary_speech_lock = threading.Lock()
        self._external_auxiliary_speech_interrupt: threading.Event | None = None
        self._pending_drink_reminder_lock = threading.Lock()
        self._pending_drink_reminder: PendingDrinkReminder | None = None
        self._guided_recovery_lock = threading.RLock()
        self._guided_recovery_requested = threading.Event()
        self._guided_recovery_input = ""
        self._conversation_stop_requested = threading.Event()
        self._conversation_stop_silent = threading.Event()
        self._voice_chat_session_active = threading.Event()
        self._camera_snapshot_preview_active = False
        self._external_read_aloud_active = threading.Event()
        self._external_read_aloud_depth = 0
        self._active_voice_capture_cancel: threading.Event | None = None
        self._active_voice_asr_cancel: Callable[[], Any] | None = None
        self._synthetic_wake_requested = threading.Event()
        self._scripted_followup_requested = threading.Event()
        self._scripted_followup_kind = ""
        self._scripted_memory_recall_armed = threading.Event()
        # The finals high-five is followed by a touch drawing handoff and one
        # scripted memory question. During that handoff, motor noise and
        # accidental touches must not open an unrelated voice session.
        self._guided_expression_handoff_active = threading.Event()
        self._active_wake_wait_cancel: threading.Event | None = None
        self._wake_ack_lock = threading.Lock()
        self._wake_ack_index = 0
        self._scene_turn_selector = SceneTurnSelector()
        self._stream_scene_id = 0
        self._stream_scene_callback: Callable[[int], None] | None = None
        self._scene_priority_controller = ScenePriorityController()
        self._scene_night_timer: threading.Timer | None = None
        self.output_adapters = OutputAdapterSet()

    def _next_wake_ack_text(self) -> str:
        """Return the next short, pre-cached wake acknowledgement."""
        with self._wake_ack_lock:
            text = WAKE_ACK_CACHE_ITEMS[
                self._wake_ack_index % len(WAKE_ACK_CACHE_ITEMS)
            ][0]
            self._wake_ack_index += 1
        return text

    @property
    def network_client(self) -> NetworkClient:
        if self._network_client is None:
            self._network_client = NetworkClient(self.settings)
        return self._network_client

    @network_client.setter
    def network_client(self, value: NetworkClient) -> None:
        self._network_client = value

    @property
    def asr_client(self) -> Any:
        if self._asr_client is None:
            self._asr_client = SherpaOnnxASRClient(self.settings)
        return self._asr_client

    @asr_client.setter
    def asr_client(self, value: Any) -> None:
        self._asr_client = value

    @property
    def llm_client(self) -> Any:
        if self._llm_client is None:
            self._llm_client = DashScopeLLMClient(self.settings, self.network_client)
        return self._llm_client

    @llm_client.setter
    def llm_client(self, value: Any) -> None:
        self._llm_client = value

    @property
    def tts_client(self) -> Any:
        if self._tts_client is None:
            self._tts_client = DashScopeTTSClient(
                self.settings,
                self.network_client,
                voice_profile=self.voice_profile,
            )
        return self._tts_client

    @tts_client.setter
    def tts_client(self, value: Any) -> None:
        self._tts_client = value

    @property
    def growth_guidance_engine(self) -> GrowthGuidanceEngine:
        if self._growth_guidance_engine is None:
            knowledge_base = None
            if self.session.prompt_builder is not None:
                knowledge_base = getattr(self.session.prompt_builder, "knowledge_base", None)
            self._growth_guidance_engine = GrowthGuidanceEngine(
                knowledge_base=knowledge_base,
            )
        return self._growth_guidance_engine

    @growth_guidance_engine.setter
    def growth_guidance_engine(self, value: GrowthGuidanceEngine) -> None:
        self._growth_guidance_engine = value

    @property
    def coordinator(self) -> XingbaoCoordinator:
        if self._coordinator is None:
            self._coordinator = XingbaoCoordinator()
        return self._coordinator

    @coordinator.setter
    def coordinator(self, value: XingbaoCoordinator) -> None:
        self._coordinator = value

    def run_text_demo(self) -> str:
        return self.session.run_text_demo()

    def build_prompt_preview(self) -> str:
        assert self.session.prompt_builder is not None
        return self.session.prompt_builder.build_system_prompt()

    def list_audio_devices(self) -> str:
        return str(list_devices())

    def list_output_devices(self) -> str:
        _np, sd = import_audio_libs()
        devices = sd.query_devices()
        lines: list[str] = []
        for index, device in enumerate(devices):
            max_output_channels = int(device.get("max_output_channels", 0))
            if max_output_channels <= 0:
                continue
            lines.append(
                f"{index}: {device.get('name', '(unknown)')} "
                f"({max_output_channels} out, "
                f"default_sr={device.get('default_samplerate', 'unknown')})"
            )
        return "\n".join(lines) if lines else "No output-capable audio devices found."

    def test_output_device(self, output_device: int) -> str:
        lines = [f"Testing output device {output_device}."]
        for sample_rate in (24000, 48000):
            path = generate_chime_wav(
                Path(f"work/cache/output_test_{sample_rate}.wav"),
                sample_rate=sample_rate,
            )
            try:
                play_wav(path, output_device=output_device)
            except Exception as exc:
                lines.append(f"- {sample_rate} Hz failed: {exc}")
                continue
            lines.append(f"- {sample_rate} Hz played successfully.")
            return "\n".join(lines)
        lines.append("No test tone could be played on this device.")
        return "\n".join(lines)

    def test_board_output(self) -> str:
        path = generate_chime_wav(Path("work/cache/board_output_test.wav"), sample_rate=48000)
        play_wav(path, output_device=BOARD_APLAY_OUTPUT_DEVICE)
        return "Board ALSA output test played through lahaina aplay backend."

    def list_voice_profiles(self) -> str:
        profiles = load_voice_profiles(self.settings)
        lines = []
        for profile in profiles:
            marker = "*" if profile.id == self.voice_profile.id else "-"
            lines.append(
                f"{marker} {profile.id}: {profile.label} "
                f"({profile.model}/{profile.voice}, rate={profile.rate}, volume={profile.volume})"
            )
            if profile.description:
                lines.append(f"  {profile.description}")
        return "\n".join(lines)

    def send_action(self, serial_port: str, action_name: str) -> dict[str, str]:
        with SerialBridge(serial_port, action_bus=self.session.action_bus) as bridge:
            action = bridge.send_action(action_name)
        return action.as_dict()

    def run_color_block_demo(self) -> str:
        """Run a deterministic text demo of the color block mini game."""
        game = ColorBlockGame()
        lines = [
            "星宝色块牌阵 demo",
            f"Start action: {game.start_action().as_dict()}",
        ]
        script = (
            ("child_play", "red", "star_lane"),
            ("xingbao_turn",),
            ("child_play", "yellow", "guard_lane"),
            ("xingbao_turn",),
            ("child_pass",),
        )
        for step in script:
            if step[0] == "child_play":
                result = game.child_play(step[1], step[2])
            elif step[0] == "child_pass":
                result = game.child_pass()
            else:
                result = game.xingbao_take_turn()
            lines.append(result.message)
            lines.append(f"Action: {result.action.as_dict()}")
            if game.turn == "xingbao" and game.passed["child"] and not game.game_winner:
                result = game.xingbao_take_turn()
                lines.append(result.message)
                lines.append(f"Action: {result.action.as_dict()}")
        snapshot = game.snapshot()
        lines.append(
            "Score: "
            f"child={snapshot['totals']['child']} "
            f"xingbao={snapshot['totals']['xingbao']}"
        )
        lines.append(f"Round winners: {snapshot['round_winners']}")
        return "\n".join(lines)

    def launch_color_block_game(self, *, serial_port: str | None = None) -> None:
        """Launch the assisted desktop UI for physical color block play."""
        launch_color_block_game(serial_port=serial_port)

    def color_block_web_path(self) -> Path:
        """Return the standalone browser-playable color block game UI path."""
        return Path("web/color_block_game.html").resolve()

    def list_kids_visual_tools(self) -> list[dict[str, Any]]:
        """Return the migrated white-box visual tool registry."""
        return get_visual_tool_registry()

    def launch_kids_visual_tools(
        self,
        tool: str | None = None,
        *,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Launch the migrated white-box visual toolbox."""
        return launch_visual_tools(tool, wait=wait)

    def run_coordinated_text(
        self,
        user_text: str,
        *,
        apply_output: bool = False,
        launch_tools: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> dict[str, Any]:
        """Plan and optionally apply a full expression/TTS/tool interaction."""
        plan = self.coordinator.plan_text(user_text)
        return self._run_coordination_plan(
            plan,
            apply_output=apply_output,
            launch_tools=launch_tools,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
            board_ui_client=board_ui_client,
        )

    def run_coordinated_event_json(
        self,
        raw_event_json: str,
        *,
        apply_output: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> dict[str, Any]:
        """Plan and optionally apply one structured module event."""
        try:
            raw_event = json.loads(raw_event_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid coordination event JSON: {exc}") from exc
        if not isinstance(raw_event, dict):
            raise ValueError("Coordination event JSON must be an object.")
        plan = self.coordinator.plan_event(raw_event)
        return self._run_coordination_plan(
            plan,
            apply_output=apply_output,
            launch_tools=False,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
            board_ui_client=board_ui_client,
        )

    def run_coordinated_state_json(
        self,
        raw_state_json: str,
        *,
        apply_output: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
        board_ui_client: BoardUIClient | None = None,
        board_ui_first: bool = False,
    ) -> dict[str, Any]:
        """Plan and optionally apply one reserved state-input envelope."""
        try:
            raw_state = json.loads(raw_state_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid coordination state JSON: {exc}") from exc
        if not isinstance(raw_state, dict):
            raise ValueError("Coordination state JSON must be an object.")
        plan = self.coordinator.plan_event(raw_state)
        return self._run_coordination_plan(
            plan,
            apply_output=apply_output,
            launch_tools=False,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
            board_ui_client=board_ui_client,
            board_ui_first=board_ui_first,
        )

    def run_game_command_json(
        self,
        raw_command_json: str,
        *,
        apply_output: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> dict[str, Any]:
        """Run one fixed-intent game command and coordinate the response."""
        try:
            command = json.loads(raw_command_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid game command JSON: {exc}") from exc
        if not isinstance(command, dict):
            raise ValueError("Game command JSON must be an object.")

        response = GameCommandAdapter(self).handle_command(command)
        plan = self.coordinator.plan_event(response)
        result = self._run_coordination_plan(
            plan,
            apply_output=apply_output,
            launch_tools=False,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
            board_ui_client=board_ui_client,
        )
        result["game_response"] = response
        return result

    def run_coordinated_color_block_command(
        self,
        command_text: str,
        *,
        apply_output: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> dict[str, Any]:
        """Run one color block command and route its result through coordination."""
        game = ColorBlockGame()
        command = parse_color_block_voice_command(command_text)
        if command.intent == "play" and command.color_id and command.lane_id:
            result = game.child_play(command.color_id, command.lane_id)
            raw_event = color_block_result_event(
                result,
                game=game,
                command_text=command_text,
            )
        elif command.intent == "pass":
            result = game.child_pass()
            raw_event = color_block_result_event(
                result,
                game=game,
                command_text=command_text,
            )
        else:
            raw_event = color_block_command_event(
                command,
                command_text=command_text,
            )
        plan = self.coordinator.plan_event(raw_event)
        return self._run_coordination_plan(
            plan,
            apply_output=apply_output,
            launch_tools=False,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
            board_ui_client=board_ui_client,
        )

    def _run_coordination_plan(
        self,
        plan: CoordinationPlan,
        *,
        apply_output: bool,
        launch_tools: bool,
        no_tts: bool,
        local_tts_fallback: bool,
        output_device: int | None,
        board_ui_client: BoardUIClient | None = None,
        board_ui_first: bool = False,
    ) -> dict[str, Any]:
        """Run a prepared coordination plan through output adapters."""
        trace = OutputTrace()
        board_ui_result = None

        def send_board_ui() -> dict[str, Any]:
            assert board_ui_client is not None
            try:
                include_screen_text = not (
                    self._conversation_audio_active()
                    and str(plan.expression_output.source or "") != "dialogue"
                )
                subtitle_priority = (
                    "dialogue"
                    if str(plan.expression_output.source or "") == "dialogue"
                    else "external"
                )
                return board_ui_client.send_plan(
                    plan,
                    include_screen_text=include_screen_text,
                    subtitle_priority=subtitle_priority,
                )
            except TypeError as exc:
                # Some integration tests and older board bridges expose the
                # legacy send_plan signature. They remain compatible when no
                # subtitle protection is required; do not silently allow an
                # external subtitle to replace dialogue text.
                if (
                    self._conversation_audio_active()
                    and str(plan.expression_output.source or "") != "dialogue"
                ):
                    return {
                        "ok": True,
                        "skipped_screen_text": True,
                        "reason": "conversation_subtitle_active",
                    }
                if "include_screen_text" not in str(exc) and "subtitle_priority" not in str(exc):
                    raise
                return board_ui_client.send_plan(plan, include_screen_text=include_screen_text)
            except OSError as exc:
                return {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }

        if board_ui_first and board_ui_client is not None:
            board_ui_result = send_board_ui()

        applied = None
        if apply_output:
            applied = self.apply_expression_output(
                plan.expression_output,
                no_tts=no_tts,
                local_tts_fallback=local_tts_fallback,
                output_device=output_device,
            ).as_dict()

        applied_action = applied.get("action") if isinstance(applied, dict) else None
        applied_output = applied.get("output") if isinstance(applied, dict) else None
        tts_played = bool(applied.get("tts_played")) if isinstance(applied, dict) else False
        self.output_adapters.screen.record(
            trace,
            expression=plan.expression_output.expression,
            screen_text=plan.expression_output.screen_text,
            action=applied_action if isinstance(applied_action, dict) else None,
            applied=apply_output,
        )
        self.output_adapters.speech.record(
            trace,
            speak_text=(
                str(applied_output.get("speak_text") or "")
                if isinstance(applied_output, dict)
                else plan.expression_output.speak_text
            ),
            tts_requested=plan.expression_output.tts,
            tts_played=tts_played,
            no_tts=no_tts,
            force_skip=(
                plan.tool_request is not None
                and plan.tool_request.target == "mini_game_hub"
            ),
        )

        tool_launched = False
        tool_launch_status = "not_requested"
        if plan.tool_request is not None:
            tool_launch_status = plan.tool_request.status
            if (
                launch_tools
                and plan.tool_request.status == "ready"
                and plan.tool_request.target != "mini_game_hub"
            ):
                self.launch_tool(plan.tool_request.target)
                tool_launched = True
                tool_launch_status = "launched"
            self.output_adapters.tool.record(
                trace,
                target=plan.tool_request.target,
                request_status=plan.tool_request.status,
                launch_enabled=launch_tools,
                launched=tool_launched,
                message=plan.tool_request.message,
            )

        if board_ui_client is not None:
            if board_ui_result is None:
                board_ui_result = send_board_ui()
            if board_ui_result.get("ok"):
                trace.emit(
                    "board_ui.assistant_output",
                    "sent",
                    request=board_ui_result.get("request"),
                    response=board_ui_result.get("response"),
                    arm=board_ui_result.get("arm"),
                )
            else:
                trace.emit(
                    "board_ui.assistant_output",
                    "failed",
                    error=board_ui_result.get("error", "command_failed"),
                    message=board_ui_result.get("message", ""),
                )

        result = CoordinationRunResult(
            plan=plan.as_dict(),
            applied=applied,
            trace=trace.as_list(),
            tool_launched=tool_launched,
            tool_launch_status=tool_launch_status,
        ).as_dict()
        if board_ui_result is not None:
            result["board_ui"] = board_ui_result
        return result

    def launch_tool(self, target: str) -> None:
        """Launch one registered computer-side tool by id."""
        if target == "color_block_game":
            self.launch_color_block_game()
            return
        if target == "kids_visual_tools":
            self.launch_kids_visual_tools(wait=False)
            return
        if target.startswith("kids_visual_tools:"):
            self.launch_kids_visual_tools(target, wait=False)
            return
        if target == "story_time":
            return
        raise ValueError(f"Tool is not launchable yet: {target}")

    def run_expression_demo(
        self,
        *,
        apply_output: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
    ) -> str:
        """Run a deterministic demo of the Xingbao expression dispatcher."""
        dispatcher = ExpressionDispatcher()
        lines = ["星宝表达调度 demo"]
        for index, event in enumerate(build_expression_demo_events(), start=1):
            output = dispatcher.handle(event)
            lines.append(f"\n[{index}] {event['type']} from {event['source']}")
            payload_event = event.get("payload", {}).get("event")
            if payload_event:
                lines.append(f"Event: {payload_event}")
            lines.append(f"Intent: {output.intent}")
            lines.append(f"Speak: {output.speak_text or '(no tts)'}")
            lines.append(f"Screen: {output.screen_text}")
            lines.append(f"Expression: {output.expression}")
            lines.append(f"Priority: {output.priority}")
            if output.memory_request:
                lines.append(
                    "Memory: "
                    + json.dumps(output.memory_request, ensure_ascii=False, sort_keys=True)
                )
            if apply_output:
                applied = self.apply_expression_output(
                    output,
                    no_tts=no_tts,
                    local_tts_fallback=local_tts_fallback,
                    output_device=output_device,
                )
                lines.append(
                    "Applied: "
                    + json.dumps(applied.as_dict(), ensure_ascii=False, sort_keys=True)
                )
        return "\n".join(lines)

    def run_expression_event_json(
        self,
        raw_event_json: str,
        *,
        apply_output: bool = False,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
        use_growth_guidance: bool = False,
    ) -> dict[str, Any]:
        """Handle one module collaboration event encoded as JSON."""
        try:
            raw_event = json.loads(raw_event_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid expression event JSON: {exc}") from exc
        if not isinstance(raw_event, dict):
            raise ValueError("Expression event JSON must be an object.")
        if use_growth_guidance:
            plan = self.growth_guidance_engine.plan(raw_event)
            output = _expression_output_from_growth_plan(plan)
        else:
            output = ExpressionDispatcher().handle(raw_event)
        if apply_output:
            return self.apply_expression_output(
                output,
                no_tts=no_tts,
                local_tts_fallback=local_tts_fallback,
                output_device=output_device,
            ).as_dict()
        return output.as_dict()

    def apply_expression_output(
        self,
        output: ExpressionOutput,
        *,
        no_tts: bool = True,
        local_tts_fallback: bool = False,
        output_device: int | None = None,
    ) -> ExpressionApplyResult:
        """Apply an expression output to memory, screen state, and optional TTS."""
        memory = None
        if output.memory_request:
            memory = self.session.memory_manager.update(output.memory_request)

        action = self.session.action_bus.emit(
            {
                "screen_expression": _screen_expression_for(output.expression),
                "led_mode": _led_mode_for(output.expression),
            }
        ).as_dict()

        tts_played = False
        speech_text = sanitize_tts_text(output.speak_text)
        if output.tts and speech_text and not no_tts:
            if self._conversation_audio_active():
                if output.intent == "drink_reminder":
                    self._queue_pending_drink_reminder(
                        speech_text,
                        local_tts_fallback=local_tts_fallback,
                        output_device=output_device,
                    )
                    print("[auxiliary-speech] queued type=drink_reminder", flush=True)
                else:
                    print(
                        "[auxiliary-speech] dropped source={} intent={} reason=conversation_active".format(
                            output.source,
                            output.intent,
                        ),
                        flush=True,
                    )
            else:
                interrupt_event = self._begin_auxiliary_speech_turn()
                try:
                    self._speak_with_demo_cache(
                        speech_text,
                        tts_client=self.tts_client,
                        no_tts=False,
                        local_fallback=local_tts_fallback,
                        output_device=output_device,
                        interrupt_event=interrupt_event,
                    )
                    tts_played = not interrupt_event.is_set()
                finally:
                    self._finish_auxiliary_speech_turn(interrupt_event)

        return ExpressionApplyResult(
            output=output.as_dict(),
            action=action,
            memory=memory,
            tts_played=tts_played,
        )

    def speak_game_text(
        self,
        text: str,
        *,
        output_device: int | None = None,
        local_tts_fallback: bool = False,
        interrupt: bool = False,
        source: str = "",
        scene: str = "",
        latency_mode: str = "",
        interrupt_event: threading.Event | None = None,
        speech_context: dict[str, Any] | None = None,
    ) -> Path | None:
        """Play one trusted game prompt through the central TTS path."""
        speech_text = sanitize_tts_text(text)
        if not speech_text:
            return None
        if self._conversation_audio_active():
            print(
                "[auxiliary-speech] dropped source={} scene={} reason=conversation_active".format(
                    source,
                    scene,
                ),
                flush=True,
            )
            return None
        is_read_aloud = str(source or "") == "xingbao_desktop_read_aloud" or str(scene or "") == "desktop"
        provided_interrupt_event = interrupt_event
        if is_read_aloud:
            if interrupt_event is None:
                interrupt_event = self._begin_read_aloud_turn(interrupt=interrupt)
            self._begin_external_read_aloud()
            try:
                print(
                    "[game-speech] read_aloud_stream_started chars={} output_device={}".format(
                        len(speech_text), output_device
                    ),
                    flush=True,
                )
                player = RealtimeStreamingSpeechPlayer(
                    settings=self.settings,
                    voice_profile=self.voice_profile,
                    output_device=output_device,
                    interrupt_event=interrupt_event,
                )
                player.start()
                player.enqueue(speech_text)
                player.close()
                print(
                    "[game-speech] read_aloud_stream_finished audio_started={}".format(
                        player.audio_started
                    ),
                    flush=True,
                )
                return None
            except Exception as exc:
                print(
                    "[game-speech] read_aloud_stream_failed error={}: {}".format(
                        type(exc).__name__, exc
                    ),
                    flush=True,
                )
                raise
            finally:
                self._finish_external_read_aloud()
                if provided_interrupt_event is None:
                    self._finish_read_aloud_turn(interrupt_event)
        out_wav = self.game_speech_cache.resolve_path(
            speech_text,
            self.voice_profile.id,
        )
        if interrupt_event is None:
            interrupt_event = self._begin_game_speech_turn(interrupt=interrupt)
        cache_hit = self.game_speech_cache.is_valid(out_wav)
        if isinstance(speech_context, dict):
            speech_context["cache_hit"] = cache_hit
            speech_context["_cache_hit"] = cache_hit
        direct_tts = True
        lock = None
        if lock is not None:
            lock.acquire()
        try:
            active_tts_client = (
                self.tts_client
                if not direct_tts
                else DashScopeTTSClient(
                    self.settings,
                    voice_profile=self.voice_profile,
                    request_timeout=12,
                    retries=1,
                    interrupt_event=interrupt_event,
                )
            )
            return self._speak_with_demo_cache(
                speech_text,
                tts_client=active_tts_client,
                no_tts=False,
                local_fallback=local_tts_fallback,
                out_wav=out_wav,
                output_device=output_device,
                interrupt_event=interrupt_event,
                reuse_out_wav=direct_tts,
                direct_tts=direct_tts,
            )
        finally:
            try:
                if interrupt_event is not None:
                    if is_read_aloud:
                        if provided_interrupt_event is None:
                            self._finish_read_aloud_turn(interrupt_event)
                    else:
                        if provided_interrupt_event is None:
                            self._finish_game_speech_turn(interrupt_event)
            finally:
                if lock is not None:
                    lock.release()

    def prefetch_game_tts_texts(self, texts: list[str] | tuple[str, ...]) -> int:
        """Warm future trusted prompts without delaying the visible game UI.

        This is intentionally limited to the current game's already-authored
        text. It never asks an LLM to create content and it deduplicates both
        cached and in-flight phrases.
        """
        candidates: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for raw_text in texts:
            text = sanitize_tts_text(raw_text)
            if not text or text in seen:
                continue
            seen.add(text)
            path = self.game_speech_cache.resolve_path(text, self.voice_profile.id)
            if not self.game_speech_cache.is_valid(path):
                candidates.append((text, path))
        if not candidates:
            return 0

        with self._game_prefetch_lock:
            pending = [
                item for item in candidates if item[0] not in self._game_prefetch_pending
            ]
            self._game_prefetch_pending.update(text for text, _ in pending)
        if not pending:
            return 0

        def warm() -> None:
            try:
                for text, path in pending:
                    try:
                        if not self.game_speech_cache.is_valid(path):
                            self._synthesize_cache_atomic(
                                text,
                                path,
                                tts_client=self.tts_client,
                            )
                    except Exception as exc:  # pragma: no cover - network is optional
                        print(
                            "[game-speech] prefetch skipped text={!r} error={}: {}".format(
                                text, type(exc).__name__, exc
                            ),
                            flush=True,
                        )
            finally:
                with self._game_prefetch_lock:
                    self._game_prefetch_pending.difference_update(
                        text for text, _ in pending
                    )

        threading.Thread(
            target=warm,
            name="game-tts-prefetch",
            daemon=True,
        ).start()
        return len(pending)

    def _begin_read_aloud_turn(self, *, interrupt: bool) -> threading.Event:
        event = threading.Event()
        with self._external_read_aloud_lock:
            if interrupt and self._external_read_aloud_interrupt is not None:
                self._external_read_aloud_interrupt.set()
            self._external_read_aloud_interrupt = event
        return event

    def _finish_read_aloud_turn(self, event: threading.Event) -> None:
        with self._external_read_aloud_lock:
            if self._external_read_aloud_interrupt is event:
                self._external_read_aloud_interrupt = None

    def interrupt_game_speech(self, payload: dict[str, Any] | None = None) -> None:
        """Stop the current touch-game utterance before a newer UI state speaks."""
        source = str((payload or {}).get("source") or "")
        if source not in {"", "xingbao_touch_game"}:
            return
        with self._external_game_speech_lock:
            if self._external_game_speech_interrupt is not None:
                self._external_game_speech_interrupt.set()

    def _begin_game_speech_turn(self, *, interrupt: bool) -> threading.Event:
        event = threading.Event()
        with self._external_game_speech_lock:
            if interrupt and self._external_game_speech_interrupt is not None:
                self._external_game_speech_interrupt.set()
            self._external_game_speech_interrupt = event
        return event

    def _finish_game_speech_turn(self, event: threading.Event) -> None:
        with self._external_game_speech_lock:
            if self._external_game_speech_interrupt is event:
                self._external_game_speech_interrupt = None

    def _conversation_audio_active(self) -> bool:
        """True while the child-facing dialogue owns playback and microphone."""
        return self._voice_chat_session_active.is_set()

    def _queue_pending_drink_reminder(
        self,
        text: str,
        *,
        local_tts_fallback: bool,
        output_device: int | None,
    ) -> None:
        """Keep only the newest hydration prompt; all other external speech drops."""
        with self._pending_drink_reminder_lock:
            if not self._conversation_audio_active():
                return
            self._pending_drink_reminder = PendingDrinkReminder(
                text=text,
                local_tts_fallback=local_tts_fallback,
                output_device=output_device,
            )

    def clear_pending_drink_reminder(self) -> bool:
        """Discard an obsolete hydration prompt after the timer has reset."""
        with self._pending_drink_reminder_lock:
            had_pending = self._pending_drink_reminder is not None
            self._pending_drink_reminder = None
        if had_pending:
            print("[auxiliary-speech] dropped type=drink_reminder reason=hydration_reset", flush=True)
        return had_pending

    def _drain_pending_drink_reminder(self) -> None:
        """Play one deferred hydration prompt only after dialogue audio is idle."""
        with self._pending_drink_reminder_lock:
            if self._conversation_audio_active():
                return
            pending = self._pending_drink_reminder
            self._pending_drink_reminder = None
        if pending is None:
            return
        interrupt_event = self._begin_auxiliary_speech_turn()
        try:
            if interrupt_event.is_set() or self._conversation_audio_active():
                return
            print("[auxiliary-speech] play type=drink_reminder", flush=True)
            self._speak_with_demo_cache(
                pending.text,
                tts_client=self.tts_client,
                no_tts=False,
                local_fallback=pending.local_tts_fallback,
                output_device=pending.output_device,
                interrupt_event=interrupt_event,
            )
        finally:
            self._finish_auxiliary_speech_turn(interrupt_event)

    def _begin_auxiliary_speech_turn(self) -> threading.Event:
        event = threading.Event()
        with self._external_auxiliary_speech_lock:
            if self._conversation_audio_active():
                event.set()
            self._external_auxiliary_speech_interrupt = event
        return event

    def _finish_auxiliary_speech_turn(self, event: threading.Event) -> None:
        with self._external_auxiliary_speech_lock:
            if self._external_auxiliary_speech_interrupt is event:
                self._external_auxiliary_speech_interrupt = None

    def _interrupt_external_speech(self) -> None:
        """Best-effort cancellation of external audio when dialogue takes priority."""
        with self._external_read_aloud_lock:
            if self._external_read_aloud_interrupt is not None:
                self._external_read_aloud_interrupt.set()
        with self._external_game_speech_lock:
            if self._external_game_speech_interrupt is not None:
                self._external_game_speech_interrupt.set()
        with self._external_auxiliary_speech_lock:
            if self._external_auxiliary_speech_interrupt is not None:
                self._external_auxiliary_speech_interrupt.set()

    def _begin_conversation_audio_priority(self) -> None:
        """Reserve playback and ASR for a just-started child conversation."""
        self._voice_chat_session_active.set()
        self._interrupt_external_speech()

    def _finish_conversation_audio_priority(self) -> None:
        """Release dialogue priority, then play the sole allowed queued prompt."""
        self._voice_chat_session_active.clear()
        # Do not begin the queued hydration line until the main dialogue's
        # output lock has become idle (including its final streamed chunk).
        wait_for_audio_playback_idle(settle_seconds=0.0)
        self._drain_pending_drink_reminder()

    @staticmethod
    def _set_board_dialogue_subtitle_state(
        board_ui_client: BoardUIClient | None,
        active: bool,
    ) -> None:
        """Best-effort subtitle ownership update for the Wayland touch UI."""
        sender = getattr(board_ui_client, "send_dialogue_subtitle_state", None)
        if not callable(sender):
            return
        try:
            sender(active)
        except OSError:
            pass

    def _send_xingbao_scene(self, board_ui_client: BoardUIClient | None, scene_id: int, source: str) -> None:
        sender = getattr(board_ui_client, "send_xingbao_scene", None)
        if not callable(sender):
            return
        try:
            sender(scene_id, source=source)
        except (OSError, ValueError):
            pass

    def _schedule_night_scene(self, board_ui_client: BoardUIClient | None) -> None:
        if self._scene_night_timer is not None:
            self._scene_night_timer.cancel()

        def show_if_still_idle() -> None:
            scene_id = self._scene_priority_controller.poll_idle(datetime.now())
            if scene_id:
                self._send_xingbao_scene(board_ui_client, scene_id, "night_idle")

        timer = threading.Timer(10 * 60, show_if_still_idle)
        timer.daemon = True
        self._scene_night_timer = timer
        timer.start()

    def prepare_demo_tts_cache(
        self,
        *,
        yield_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Synthesize fixed demo utterances once so playback is instant during filming."""
        results: list[dict[str, Any]] = []
        ok = True
        for entry in self.game_speech_cache.entries:
            text = entry.text
            path = self.game_speech_cache.resolve_path(text, self.voice_profile.id)
            item: dict[str, Any] = {"text": text, "path": str(path)}
            if self.game_speech_cache.is_valid(path):
                item["status"] = "cached"
                results.append(item)
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with self._external_tts_lock:
                    if self.game_speech_cache.is_valid(path):
                        item["status"] = "cached"
                    else:
                        self._synthesize_cache_atomic(
                            text,
                            path,
                            tts_client=self.tts_client,
                        )
                        item["status"] = "created"
            except Exception as exc:
                ok = False
                item["status"] = "failed"
                item["error"] = type(exc).__name__
                item["message"] = str(exc)
            results.append(item)
            if yield_seconds > 0:
                time.sleep(min(float(yield_seconds), 1.0))
        inspection = self.game_speech_cache.inspect_manifest()
        return {
            "ok": ok and inspection["ok"],
            "counts": inspection["counts"],
            "items": results,
        }

    def prepare_wake_ack_cache(self) -> dict[str, Any]:
        """Pre-synthesize the short wake replies used by the live wake loop."""
        return self._prepare_named_tts_cache(dict(WAKE_ACK_CACHE_ITEMS))

    def prepare_guided_expression_tts_cache(self) -> dict[str, Any]:
        """Pre-synthesize deterministic dinosaur-script replies for the demo."""
        if not DINOSAUR_SCRIPT_ENABLED:
            return {"ok": True, "disabled": True, "counts": {"ready": 0, "missing": 0, "corrupt": 0, "total": 0}, "items": []}
        return self._prepare_named_tts_cache(GUIDED_EXPRESSION_TTS_CACHE_FILES)

    def prepare_fixed_demo_tts_cache(self) -> dict[str, Any]:
        """Pre-synthesize short fixed demonstration replies."""
        return self._prepare_named_tts_cache(FIXED_DEMO_TTS_CACHE_FILES)

    def prepare_vision_tts_cache(self) -> dict[str, Any]:
        """Pre-synthesize fixed vision reminders for offline local playback."""
        return self._prepare_named_tts_cache(VISION_TTS_CACHE_FILES)

    def _prepare_named_tts_cache(
        self,
        entries: dict[str, str],
    ) -> dict[str, Any]:
        """Create direct WAV cache entries without involving realtime TTS."""
        results: list[dict[str, Any]] = []
        ok = True
        for text, filename in entries.items():
            path = Path("work/cache") / filename
            item: dict[str, Any] = {"text": text, "path": str(path)}
            if self.game_speech_cache.is_valid(path):
                item["status"] = "cached"
                results.append(item)
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with self._external_tts_lock:
                    if self.game_speech_cache.is_valid(path):
                        item["status"] = "cached"
                    else:
                        self._synthesize_cache_atomic(
                            text,
                            path,
                            tts_client=self.tts_client,
                        )
                        item["status"] = "created"
            except Exception as exc:
                ok = False
                item["status"] = "failed"
                item["error"] = type(exc).__name__
                item["message"] = str(exc)
            results.append(item)
        return {
            "ok": ok,
            "counts": {
                "total": len(results),
                "ready": sum(
                    item["status"] in {"cached", "created"} for item in results
                ),
                "failed": sum(item["status"] == "failed" for item in results),
            },
            "items": results,
        }

    def _synthesize_cache_atomic(
        self,
        text: str,
        target_path: Path,
        *,
        tts_client: DashScopeTTSClient,
    ) -> Path:
        temp_path = target_path.with_name(
            f".{target_path.stem}.{uuid.uuid4().hex}.tmp.wav"
        )
        promoted = False
        try:
            tts_client.synthesize(text, temp_path)
            if not self.game_speech_cache.normalize_wav_header(temp_path):
                raise RuntimeError("TTS cache synthesis produced an unreadable WAV file.")
            if not self.game_speech_cache.is_valid(temp_path):
                raise RuntimeError("TTS cache synthesis produced an invalid WAV file.")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_path, target_path)
            promoted = True
            return target_path
        finally:
            if not promoted:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _speak_with_demo_cache(
        self,
        text: str,
        *,
        tts_client: DashScopeTTSClient | None = None,
        no_tts: bool = False,
        local_fallback: bool = False,
        out_wav: Path | str = Path("work/cache/reply.wav"),
        output_device: int | None = None,
        interrupt_event: threading.Event | None = None,
        reuse_out_wav: bool = False,
        direct_tts: bool = False,
    ) -> Path | None:
        speech_text = sanitize_tts_text(text)
        if no_tts or not speech_text:
            return None
        if os.environ.get("XINGBAO_DEMO_TTS_CACHE", "1") != "0":
            resolved_out_wav = Path(out_wav)
            if reuse_out_wav and self.game_speech_cache.is_valid(resolved_out_wav):
                started_at = time.perf_counter()
                print(
                    "[event-audio] cache_play_start path={} chars={}".format(
                        resolved_out_wav, len(speech_text)
                    ),
                    flush=True,
                )
                play_wav(
                    resolved_out_wav,
                    output_device=output_device,
                    interrupt_event=interrupt_event,
                )
                print(
                    "[event-audio] cache_play_finished path={} elapsed_ms={:.1f}".format(
                        resolved_out_wav, (time.perf_counter() - started_at) * 1000.0
                    ),
                    flush=True,
                )
                return resolved_out_wav
            filename = None if reuse_out_wav else DEMO_TTS_CACHE_FILES.get(speech_text)
            if filename:
                cache_path = Path("work/cache") / filename
                if self.game_speech_cache.is_valid(cache_path):
                    started_at = time.perf_counter()
                    print(
                        "[event-audio] cache_play_start path={} chars={}".format(
                            cache_path, len(speech_text)
                        ),
                        flush=True,
                    )
                    play_wav(
                        cache_path,
                        output_device=output_device,
                        interrupt_event=interrupt_event,
                    )
                    print(
                        "[event-audio] cache_play_finished path={} elapsed_ms={:.1f}".format(
                            cache_path, (time.perf_counter() - started_at) * 1000.0
                        ),
                        flush=True,
                    )
                    return cache_path
        # Fixed prompts are normally served from the local WAV cache above.
        # For a cache miss, use the same DashScope WebSocket stream as normal
        # conversation TTS rather than requesting and downloading a temporary
        # HTTP audio URL. Set this environment variable to 0 only when an
        # operator deliberately needs the legacy HTTP route.
        if os.environ.get("XINGBAO_EVENT_TTS_STREAMING", "1") != "0":
            player = RealtimeStreamingSpeechPlayer(
                settings=self.settings,
                voice_profile=self.voice_profile,
                output_device=output_device,
                interrupt_event=interrupt_event,
            )
            player.start()
            player.enqueue(speech_text)
            player.close()
            return None
        speech_function = speak_interruptible_direct if direct_tts else speak
        if direct_tts and reuse_out_wav:
            target_path = Path(out_wav)
            temp_path = target_path.with_name(
                f".{target_path.stem}.{uuid.uuid4().hex}.tmp.wav"
            )
            promoted = False
            try:
                result = speech_function(
                    speech_text,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_fallback,
                    out_wav=temp_path,
                    output_device=output_device,
                    interrupt_event=interrupt_event,
                )
                if (
                    (interrupt_event is None or not interrupt_event.is_set())
                    and self.game_speech_cache.is_valid(temp_path)
                ):
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(temp_path, target_path)
                    promoted = True
                    return target_path
                return result
            finally:
                if not promoted:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        return speech_function(
            speech_text,
            tts_client=tts_client,
            no_tts=no_tts,
            local_fallback=local_fallback,
            out_wav=out_wav,
            output_device=output_device,
            interrupt_event=interrupt_event,
        )

    def wait_for_wake_word(
        self,
        *,
        input_device: int | None = None,
        detector: Any | None = None,
        wake_level_interval_seconds: float = 0.25,
        wake_word_threshold: float | None = None,
    ) -> str:
        active_detector = detector or self._build_wake_word_detector(
            input_device=input_device,
            show_input_level=True,
            wake_level_interval_seconds=wake_level_interval_seconds,
            wake_word_threshold=wake_word_threshold,
        )
        return active_detector.wait_for_wake_word()

    def test_wake_wav(self, wav_path: str) -> list[str]:
        detector = self._build_wake_word_detector()
        return detector.detect_wav(wav_path)

    def run_wake_loop(
        self,
        *,
        no_tts: bool = False,
        no_quick_ack: bool = False,
        no_wake_ack: bool = False,
        local_tts_fallback: bool = False,
        serial_port: str | None = None,
        input_device: int | None = None,
        output_device: int | None = None,
        max_turns: int | None = None,
        detector: Any | None = None,
        on_turn_complete: Callable[[VoiceTurnResult], Any] | None = None,
        streaming_response: bool = True,
        realtime_tts: bool = False,
        realtime_asr: bool = False,
        streaming_asr: bool = False,
        realtime_asr_model: str = "",
        show_wake_level: bool = False,
        wake_level_interval_seconds: float = 1.0,
        wake_word_threshold: float | None = None,
        low_latency_voice: bool = False,
        listen_timeout_seconds: float = 0.0,
        vad_manual_threshold: float = 0.0,
        vad_end_silence_ms: int = 0,
        on_voice_event: VoiceEventHandler | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> int:
        """Run voice turns gated by local offline wake-word detection."""
        active_detector = detector or self._build_wake_word_detector(
            input_device=input_device,
            show_input_level=show_wake_level,
            wake_level_interval_seconds=wake_level_interval_seconds,
            wake_word_threshold=wake_word_threshold,
        )
        pipeline = VoiceInteractionPipeline(on_voice_event)
        wake_ack = None
        if not no_wake_ack:
            def wake_ack() -> None:
                pipeline.emit("wake_ack_started", output_device=output_device)
                try:
                    play_wav(
                        generate_chime_wav(),
                        output_device=output_device,
                    )
                except Exception as exc:  # audio failure must not stop wake handling
                    pipeline.emit(
                        "wake_ack_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )

        def on_wake() -> VoiceTurnResult:
            pipeline.emit("wake_detected")
            return self.run_voice_once(
                no_tts=no_tts,
                no_quick_ack=no_quick_ack,
                local_tts_fallback=local_tts_fallback,
                serial_port=serial_port,
                input_device=input_device,
                output_device=output_device,
                streaming_response=streaming_response,
                realtime_tts=realtime_tts,
                realtime_asr=realtime_asr,
                streaming_asr=streaming_asr,
                realtime_asr_model=realtime_asr_model,
                low_latency_voice=low_latency_voice,
                listen_timeout_seconds=listen_timeout_seconds,
                vad_manual_threshold=vad_manual_threshold,
                vad_end_silence_ms=vad_end_silence_ms,
                barge_in_detector=active_detector,
                on_voice_event=on_voice_event,
                board_ui_client=board_ui_client,
            )

        loop = ListeningLoop(
            detector=active_detector,
            play_wake_ack=wake_ack,
            on_wake=on_wake,
            on_turn_complete=on_turn_complete,
            cooldown_seconds=self.settings.wake_word_cooldown_seconds,
        )
        completed = loop.run(max_turns=max_turns)
        self._clear_camera_snapshot_preview(pipeline)
        pipeline.emit("session_ended", reason="max_turns", turns=completed)
        return completed

    def _run_guided_expression_recovery_once(
        self,
        recovery_input: str,
        *,
        no_tts: bool,
        local_tts_fallback: bool,
        output_device: int | None,
        on_voice_event: VoiceEventHandler | None,
        board_ui_client: BoardUIClient | None,
    ) -> VoiceTurnResult:
        """Consume one touch-requested script checkpoint without recording audio."""
        pipeline = VoiceInteractionPipeline(on_voice_event)
        guided_reply = self.handle_guided_expression_text(recovery_input)
        if guided_reply is None:
            raise GuidedExpressionRecoveryRequested(
                "The guided-expression checkpoint no longer accepts recovery."
            )
        reply = guided_reply.text
        cache_filename = DEMO_TTS_CACHE_FILES.get(sanitize_tts_text(reply))
        cache_hit = bool(
            cache_filename
            and self.game_speech_cache.is_valid(Path("work/cache") / cache_filename)
        )
        pipeline.emit(
            "guided_expression_recovery",
            recovery_input=recovery_input,
            scene=guided_reply.scene,
            stage=guided_reply.stage,
            tts_route="cached_wav" if cache_hit else "batch_tts_fallback",
        )
        if board_ui_client is not None:
            try:
                board_ui_client.send_ui_command(
                    None,
                    screen_text=reply,
                    expression=_screen_expression_for(guided_reply.screen_expression),
                    led_mode=guided_reply.led_mode,
                    duration_ms=12000,
                    subtitle_priority="dialogue",
                )
            except OSError:
                pass
        turn = self.session.record_assistant_turn(
            user_text=f"[卡住了？]{recovery_input}",
            assistant_text=reply,
            action_proposal={
                "screen_expression": _screen_expression_for(
                    guided_reply.screen_expression
                ),
                "led_mode": guided_reply.led_mode,
            },
        )
        self._emit_tts_segment_queued(
            pipeline,
            reply,
            1,
            first_queue_elapsed_ms=0.0,
            fast_path="guided_expression_recovery",
            scene=guided_reply.scene,
            cached=cache_hit,
        )
        # The recovery line deliberately has no barge-in listener: it is the
        # cleanup boundary used after an interrupted voice turn.
        self._speak_with_demo_cache(
            reply,
            tts_client=None if no_tts else self.tts_client,
            no_tts=no_tts,
            local_fallback=local_tts_fallback,
            output_device=output_device,
        )
        _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
        high_five_baseline = (
            _read_high_five_status_quietly()
            if guided_reply.post_tts_arm_action == "high_five" and not no_tts
            else None
        )
        post_tts_arm_dispatch = _dispatch_guided_post_tts_arm_action(
            guided_reply.post_tts_arm_action,
            enabled=not no_tts,
        )
        if post_tts_arm_dispatch.get("queued"):
            self._guided_expression_handoff_active.set()
        if guided_reply.scene == "dinosaur_drawing_accepted":
            self._scripted_memory_recall_armed.set()
            self._open_dinosaur_drawing_board(board_ui_client, pipeline)

        def speak_high_five_line(text: str) -> None:
            self._speak_with_demo_cache(
                text,
                tts_client=None if no_tts else self.tts_client,
                no_tts=no_tts,
                local_fallback=local_tts_fallback,
                output_device=output_device,
            )

        _start_finals_post_high_five_showcase(
            baseline_status=high_five_baseline,
            dispatch_result=post_tts_arm_dispatch,
            speak_line=speak_high_five_line,
            on_ready_for_drawing=lambda: self.request_scripted_followup(
                "drawing_consent"
            ),
        )
        return VoiceTurnResult(
            user_text=recovery_input,
            assistant_text=reply,
            action=turn.action,
            audio_path="",
            end_session=guided_reply.end_session,
            session_end_reason=_guided_expression_session_end_reason(guided_reply),
            fast_path="guided_expression_recovery",
        )

    def run_wake_chat(
        self,
        *,
        no_tts: bool = False,
        no_quick_ack: bool = False,
        no_wake_ack: bool = False,
        local_tts_fallback: bool = False,
        serial_port: str | None = None,
        input_device: int | None = None,
        output_device: int | None = None,
        max_sessions: int | None = None,
        max_turns_per_session: int | None = None,
        followup_timeout_seconds: float | None = None,
        detector: Any | None = None,
        on_turn_complete: Callable[[VoiceTurnResult], Any] | None = None,
        on_session_complete: Callable[[int, str], Any] | None = None,
        streaming_response: bool = True,
        realtime_tts: bool = False,
        realtime_asr: bool = False,
        streaming_asr: bool = False,
        realtime_asr_model: str = "",
        show_wake_level: bool = False,
        wake_level_interval_seconds: float = 1.0,
        wake_word_threshold: float | None = None,
        low_latency_voice: bool = False,
        listen_timeout_seconds: float = 0.0,
        vad_manual_threshold: float = 0.0,
        vad_end_silence_ms: int = 0,
        on_voice_event: VoiceEventHandler | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> int:
        """Run wake-gated conversation sessions with follow-up turns."""
        completed_sessions = 0
        active_detector = detector or self._build_wake_word_detector(
            input_device=input_device,
            show_input_level=show_wake_level,
            wake_level_interval_seconds=wake_level_interval_seconds,
            wake_word_threshold=wake_word_threshold,
        )
        pipeline = VoiceInteractionPipeline(on_voice_event)
        if datetime.now().hour >= self._scene_priority_controller.night_hour:
            self._send_xingbao_scene(board_ui_client, 22, "night_startup")
        turn_limit = (
            self.settings.max_conversation_turns
            if max_turns_per_session is None
            else max_turns_per_session
        )
        unlimited_turns = int(turn_limit) <= 0
        timeout = (
            followup_timeout_seconds
            if followup_timeout_seconds is not None
            else self.settings.conversation_followup_timeout_seconds
        )

        while max_sessions is None or completed_sessions < max_sessions:
            if self._external_read_aloud_active.is_set():
                pipeline.emit("wake_suppressed", reason="read_aloud_playback")
                time.sleep(0.05)
                continue
            scripted_followup = self._take_scripted_followup_request()
            if self._guided_expression_handoff_active.is_set() and not scripted_followup:
                # Only the reviewed drawing and memory inputs may reopen
                # listening while the arm-led presentation is active.
                if self._take_synthetic_wake_request():
                    pipeline.emit("wake_suppressed", reason="guided_expression_handoff")
                self._scripted_followup_requested.wait(0.10)
                continue
            synthetic_wake = False
            if scripted_followup:
                keyword = self.settings.wake_word
            else:
                synthetic_wake = self._take_synthetic_wake_request()
            if synthetic_wake:
                keyword = self.settings.wake_word
            elif not scripted_followup:
                wake_cancel_event = self._begin_synthetic_wake_wait()
                try:
                    keyword = self._wait_for_wake_word_with_cancel(
                        active_detector,
                        wake_cancel_event,
                    )
                except Exception as exc:
                    # A wake detector is an always-on boundary.  It may lose
                    # the microphone or a cloud ASR request, but that must
                    # not kill the presentation process; wait briefly and
                    # rebuild the listening cycle on the same configured
                    # wake word.
                    pipeline.emit(
                        "wake_wait_recovered",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
                    time.sleep(0.25)
                    continue
                finally:
                    self._finish_synthetic_wake_wait(wake_cancel_event)
                # A touch wake may arrive while the detector is cancelling
                # its current microphone capture. It takes precedence over
                # the empty cancellation result.
                scripted_followup = self._take_scripted_followup_request()
                if scripted_followup or self._take_synthetic_wake_request():
                    keyword = self.settings.wake_word
            if self._external_read_aloud_active.is_set():
                pipeline.emit("wake_suppressed", reason="read_aloud_playback")
                continue
            if not str(keyword or "").strip():
                # Some detector implementations return an empty value when a
                # capture is cancelled.  Never promote that to a wake event,
                # otherwise the UI can get stuck in a recording session with
                # no actual child request.
                pipeline.emit("wake_wait_empty")
                continue
            pipeline.emit(
                "scripted_followup_listening" if scripted_followup else "wake_detected",
                keyword=keyword,
                kind=scripted_followup,
            )
            self._begin_conversation_audio_priority()
            self._send_xingbao_scene(
                board_ui_client,
                self._scene_priority_controller.on_wake(datetime.now()),
                "wake",
            )
            self._set_board_dialogue_subtitle_state(board_ui_client, True)
            send_ui_command = getattr(board_ui_client, "send_ui_command", None)
            if not scripted_followup and callable(send_ui_command):
                try:
                    wake_ui_result = send_ui_command(
                        None,
                        screen_text="星宝在这儿",
                        expression="smile",
                        led_mode="warm_breath",
                        subtitle_priority="dialogue",
                    )
                    pipeline.emit(
                        "wake_ui_acknowledged",
                        ok=bool(wake_ui_result.get("ok")),
                        response=wake_ui_result.get("response"),
                    )
                except OSError as exc:
                    pipeline.emit(
                        "wake_ui_listening_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
            if not scripted_followup and not no_wake_ack:
                wake_ack_text = self._next_wake_ack_text()
                pipeline.emit(
                    "wake_ack_started",
                    output_device=output_device,
                    text=wake_ack_text,
                    cached=True,
                )
                try:
                    self._speak_with_demo_cache(
                        wake_ack_text,
                        tts_client=self.tts_client,
                        no_tts=False,
                        local_fallback=local_tts_fallback,
                        output_device=output_device,
                    )
                except Exception as exc:  # audio failure must not stop the conversation
                    pipeline.emit(
                        "wake_ack_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )

            turns_in_session = 0
            # DashScope can occasionally close an otherwise healthy streaming
            # Recognition session just as VAD finishes.  The recorded turn is
            # then lost, but it must not force the child to say the wake word
            # again.  Permit one clean connection retry in this wake session.
            transient_streaming_asr_retries = 0
            end_reason = "max_turns"
            while unlimited_turns or turns_in_session < turn_limit:
                if self._take_conversation_stop_request():
                    end_reason = "manual_stop"
                    pipeline.emit("conversation_stop_requested")
                    break
                recovery_input = self._take_guided_recovery_input()
                if recovery_input:
                    try:
                        result = self._run_guided_expression_recovery_once(
                            recovery_input,
                            no_tts=no_tts,
                            local_tts_fallback=local_tts_fallback,
                            output_device=output_device,
                            on_voice_event=on_voice_event,
                            board_ui_client=board_ui_client,
                        )
                    except GuidedExpressionRecoveryRequested:
                        # The scene can end between the tap and the recovery
                        # worker.  Stay in the current session without
                        # promoting stale audio to a normal turn.
                        continue
                    turns_in_session += 1
                    if on_turn_complete is not None:
                        on_turn_complete(result)
                    if result.end_session:
                        end_reason = result.session_end_reason or "exit_word"
                        break
                    continue
                if turns_in_session > 0:
                    pipeline.emit(
                        "followup_waiting",
                        timeout_seconds=timeout,
                        turn_index=turns_in_session,
                    )
                turn_timeout = (
                    max(timeout, 30.0)
                    if scripted_followup == "memory_recall" and turns_in_session == 0
                    else listen_timeout_seconds
                    if turns_in_session == 0 and listen_timeout_seconds > 0
                    else 0.0
                    if turns_in_session == 0
                    else timeout
                )
                try:
                    result = self.run_voice_once(
                        no_tts=no_tts,
                        no_quick_ack=no_quick_ack,
                        local_tts_fallback=local_tts_fallback,
                        serial_port=serial_port,
                        input_device=input_device,
                        output_device=output_device,
                        streaming_response=streaming_response,
                        realtime_tts=realtime_tts,
                        realtime_asr=realtime_asr,
                        streaming_asr=streaming_asr,
                        realtime_asr_model=realtime_asr_model,
                        low_latency_voice=low_latency_voice,
                        barge_in_detector=active_detector,
                        listen_timeout_seconds=turn_timeout,
                        vad_manual_threshold=vad_manual_threshold,
                        vad_end_silence_ms=vad_end_silence_ms,
                        on_voice_event=on_voice_event,
                        board_ui_client=board_ui_client,
                    )
                except ConversationStopRequested:
                    self._take_conversation_stop_request()
                    end_reason = "manual_stop"
                    pipeline.emit("conversation_stop_requested")
                    break
                except ReadAloudPlaybackActive:
                    # Subtitle point-read temporarily owns microphone input.
                    # Once its audio ends, resume this conversation without
                    # treating the cancelled ASR as a timeout or a stopped chat.
                    pipeline.emit("wake_suppressed", reason="read_aloud_playback")
                    while self._external_read_aloud_active.wait(0.10):
                        pass
                    continue
                except NoSpeechTimeout:
                    end_reason = "timeout"
                    break
                except GuidedExpressionRecoveryRequested:
                    recovery_input = self._take_guided_recovery_input()
                    if not recovery_input:
                        end_reason = "turn_recovered"
                        break
                    try:
                        result = self._run_guided_expression_recovery_once(
                            recovery_input,
                            no_tts=no_tts,
                            local_tts_fallback=local_tts_fallback,
                            output_device=output_device,
                            on_voice_event=on_voice_event,
                            board_ui_client=board_ui_client,
                        )
                    except GuidedExpressionRecoveryRequested:
                        continue
                except Exception as exc:
                    if (
                        streaming_asr
                        and transient_streaming_asr_retries < 1
                        and _is_recoverable_streaming_asr_error(exc)
                    ):
                        transient_streaming_asr_retries += 1
                        pipeline.emit(
                            "asr_reconnecting",
                            error=type(exc).__name__,
                            message=str(exc)[:320],
                            retry_index=transient_streaming_asr_retries,
                        )
                        # Start a fresh Recognition connection and return to
                        # listening without ending the active wake session.
                        # The next run_voice_once call updates the UI back to
                        # its normal listening state.
                        continue
                    # A single cloud/audio turn must never terminate the
                    # always-on wake loop.  Return to wake-word listening so
                    # the child can simply call Xingbao again.
                    # Some fixed-reply branches can fail while their TTS
                    # barge-in worker is active (for example cloud TTS
                    # account errors). Ensure that no such worker survives
                    # to consume the next wake word.
                    _TTSBargeInGuard.stop_all()
                    end_reason = "turn_error"
                    pipeline.emit(
                        "voice_turn_recovered",
                        error=type(exc).__name__,
                        message=str(exc),
                        turn_index=turns_in_session,
                    )
                    break

                turns_in_session += 1
                transient_streaming_asr_retries = 0
                if on_turn_complete is not None:
                    on_turn_complete(result)
                if result.end_session:
                    end_reason = result.session_end_reason or "exit_word"
                    break
                if result.tts_interrupted:
                    continue

            completed_sessions += 1
            self._clear_camera_snapshot_preview(pipeline)
            self._notify_board_session_ended(
                board_ui_client,
                pipeline,
                reason=end_reason,
            )
            pipeline.emit(
                "session_ended",
                reason=end_reason,
                turns=turns_in_session,
                session_index=completed_sessions,
            )
            if on_session_complete is not None:
                on_session_complete(turns_in_session, end_reason)
            self._set_board_dialogue_subtitle_state(board_ui_client, False)
            self._send_xingbao_scene(
                board_ui_client,
                self._scene_priority_controller.on_session_end(datetime.now()),
                "session_end",
            )
            self._schedule_night_scene(board_ui_client)
            self._finish_conversation_audio_priority()
            if end_reason == "guided_expression_memory_recalled":
                self._clear_guided_expression_handoff()
            elif scripted_followup == "memory_recall" and end_reason in {
                "timeout",
                "turn_error",
            }:
                # This no-wake turn is the final, optional recall prompt.
                # If it receives no usable speech, do not leave wake input
                # suppressed indefinitely behind a stale script handoff.
                self._clear_guided_expression_handoff()
            # Wake-word cooldown belongs between separate wake sessions. It
            # must not delay natural follow-up speech inside one conversation.
            has_more_sessions = (
                max_sessions is None or completed_sessions < max_sessions
            )
            if has_more_sessions and self.settings.wake_word_cooldown_seconds > 0:
                time.sleep(self.settings.wake_word_cooldown_seconds)

        return completed_sessions

    def _notify_board_listening(
        self,
        board_ui_client: BoardUIClient | None,
        pipeline: VoiceInteractionPipeline,
        *,
        duration_seconds: float = 30.0,
    ) -> None:
        """Show the listening state when microphone capture is about to begin."""
        send_ui_command = getattr(board_ui_client, "send_ui_command", None)
        if not callable(send_ui_command):
            return
        try:
            result = send_ui_command(
                None,
                screen_text="● 正在听，请说话",
                expression="curious",
                led_mode="blue_breath",
                duration_ms=int(max(4.0, min(30.0, duration_seconds)) * 1000),
                subtitle_priority="dialogue",
            )
            pipeline.emit(
                "wake_ui_listening",
                ok=bool(result.get("ok")),
                response=result.get("response"),
            )
        except OSError as exc:
            pipeline.emit(
                "wake_ui_listening_failed",
                error=type(exc).__name__,
                message=str(exc),
            )

    def _notify_board_processing(
        self,
        board_ui_client: BoardUIClient | None,
        pipeline: VoiceInteractionPipeline,
        *,
        delay_seconds: float = 0.0,
    ) -> Callable[[], None]:
        """Show the processing state after an optional post-capture delay.

        Return a cancellation callback.  Fast local answers (notably time
        lookups) can finish before the delayed processing indication is sent;
        without cancellation that stale indication would overwrite the answer
        subtitle a moment later.
        """
        send_ui_command = getattr(board_ui_client, "send_ui_command", None)
        if not callable(send_ui_command):
            return lambda: None

        state_lock = threading.Lock()
        cancelled = False

        def cancel_processing() -> None:
            nonlocal cancelled
            # Synchronize with the timer's UI request.  When this returns,
            # no older "正在想" request can be sent after the actual answer.
            with state_lock:
                cancelled = True

        def show_processing() -> None:
            with state_lock:
                if cancelled:
                    return
                try:
                    result = send_ui_command(
                        None,
                        screen_text="✓ 听到了，我正在想…",
                        expression="thinking",
                        led_mode="warm_breath",
                        duration_ms=15000,
                        subtitle_priority="dialogue",
                    )
                    pipeline.emit(
                        "wake_ui_processing",
                        ok=bool(result.get("ok")),
                        response=result.get("response"),
                    )
                except OSError as exc:
                    pipeline.emit(
                        "wake_ui_processing_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )

        delay = max(0.0, float(delay_seconds))
        if delay <= 0:
            show_processing()
            return cancel_processing
        timer = threading.Timer(delay, show_processing)
        timer.daemon = True
        timer.start()
        return cancel_processing

    @staticmethod
    def _cancel_board_processing_notification(pipeline: VoiceInteractionPipeline) -> None:
        """Prevent a delayed generic processing subtitle from replacing output."""
        cancel = getattr(pipeline, "_cancel_board_processing_notification", None)
        if callable(cancel):
            cancel()

    def _open_dinosaur_drawing_board(
        self,
        board_ui_client: BoardUIClient | None,
        pipeline: VoiceInteractionPipeline,
    ) -> None:
        """Open the drawing board after the child's affirmative dinosaur reply."""
        send_ui_command = getattr(board_ui_client, "send_ui_command", None)
        if not callable(send_ui_command):
            pipeline.emit(
                "board_ui_game_command",
                source="dinosaur_drawing_handoff",
                ok=False,
                skipped=True,
            )
            return
        try:
            result = send_ui_command(
                {"name": "open_desktop_modal", "params": {"modal": "drawing"}},
                screen_text="我们去百宝箱画一画吧",
                expression="smile",
                led_mode="warm_breath",
                duration_ms=10000,
                subtitle_priority="dialogue",
            )
            pipeline.emit(
                "board_ui_game_command",
                source="dinosaur_drawing_handoff",
                ok=bool(result.get("ok")),
                response=result.get("response"),
            )
        except OSError as exc:
            pipeline.emit(
                "board_ui_game_command_failed",
                source="dinosaur_drawing_handoff",
                error=type(exc).__name__,
                message=str(exc),
            )

    def _notify_board_session_ended(
        self,
        board_ui_client: BoardUIClient | None,
        pipeline: VoiceInteractionPipeline,
        *,
        reason: str,
    ) -> None:
        """Make every conversation-window transition explicit to the child."""
        send_ui_command = getattr(board_ui_client, "send_ui_command", None)
        if not callable(send_ui_command):
            return
        if reason in {
            "guided_expression_high_five",
            "guided_expression_touch_handoff",
            "guided_expression_memory_recalled",
        }:
            # The reviewed flow owns the next visible state. Do not cover the
            # drawing handoff or memory answer with a generic end banner.
            pipeline.emit("wake_ui_session_end_suppressed", reason=reason)
            return
        if reason == "manual_stop" and self._conversation_stop_silent.is_set():
            self._conversation_stop_silent.clear()
            pipeline.emit("wake_ui_session_end_suppressed", reason="silent_read_aloud_stop")
            return
        screen_text = (
            "对话已停止｜说“星宝星宝”再聊"
            if reason == "manual_stop"
            else "对话已结束｜说“星宝星宝”再聊"
            if reason in {"exit_word", "guided_expression_complete"}
            else "对话已暂停｜说“星宝星宝”继续"
        )
        try:
            result = send_ui_command(
                None,
                screen_text=screen_text,
                expression="neutral",
                led_mode="off",
                duration_ms=10000,
                subtitle_priority="dialogue",
            )
            pipeline.emit(
                "wake_ui_session_ended",
                reason=reason,
                ok=bool(result.get("ok")),
                response=result.get("response"),
            )
        except OSError as exc:
            pipeline.emit(
                "wake_ui_session_end_failed",
                reason=reason,
                error=type(exc).__name__,
                message=str(exc),
            )

    def run_voice_once(
        self,
        *,
        no_tts: bool = False,
        no_quick_ack: bool = False,
        local_tts_fallback: bool = False,
        serial_port: str | None = None,
        input_device: int | None = None,
        output_device: int | None = None,
        record_sample_rate: int | None = None,
        listen_timeout_seconds: float = 0.0,
        streaming_response: bool = True,
        realtime_tts: bool = False,
        realtime_asr: bool = False,
        streaming_asr: bool = False,
        realtime_asr_model: str = "",
        low_latency_voice: bool = False,
        vad_manual_threshold: float = 0.0,
        vad_end_silence_ms: int = 0,
        vad_debug_level: bool = False,
        barge_in_detector: Any | None = None,
        on_voice_event: VoiceEventHandler | None = None,
        board_ui_client: BoardUIClient | None = None,
    ) -> VoiceTurnResult:
        """Run one real voice turn using the migrated modules."""
        self._raise_if_conversation_stop_requested()
        pipeline = VoiceInteractionPipeline(on_voice_event)
        if self._external_read_aloud_active.is_set():
            pipeline.emit(
                "asr_suppressed",
                reason="read_aloud_playback",
                phase="before_capture",
            )
            raise ReadAloudPlaybackActive()
        turn_handoff_started_at = time.perf_counter()
        wait_for_audio_playback_idle(settle_seconds=FOLLOWUP_AUDIO_SETTLE_SECONDS)
        active_sample_rate = record_sample_rate or self.settings.record_sample_rate
        audio_config = AudioDeviceConfig(
            input_device=input_device,
            output_device=output_device,
            sample_rate=active_sample_rate,
        )
        pipeline.emit(
            "listening_started",
            input_device=input_device,
            sample_rate=active_sample_rate,
            listen_timeout_seconds=listen_timeout_seconds,
        )
        audio_warmup_started_at = time.perf_counter()
        import_audio_libs()
        pipeline.emit(
            "audio_ready",
            elapsed_ms=round((time.perf_counter() - audio_warmup_started_at) * 1000, 1),
            input_device=input_device,
            sample_rate=active_sample_rate,
        )
        vad_config = None
        if (
            listen_timeout_seconds > 0
            or low_latency_voice
            or vad_manual_threshold > 0
            or vad_end_silence_ms > 0
            or vad_debug_level
        ):
            vad_config = _voice_vad_config(
                low_latency_voice=low_latency_voice,
                listen_timeout_seconds=listen_timeout_seconds,
                manual_threshold=vad_manual_threshold,
                end_silence_ms=vad_end_silence_ms,
                debug_level_interval_ms=500.0 if vad_debug_level else 0.0,
            )
        quick_ack_thread: threading.Thread | None = None

        def make_barge_in_guard(
            *,
            detector: Any | None = None,
            enable_wake_word: bool = True,
        ) -> _TTSBargeInGuard:
            if quick_ack_thread is not None and quick_ack_thread.is_alive():
                quick_ack_thread.join(timeout=2.0)
                wait_for_audio_playback_idle(settle_seconds=0.15)
            active_detector = None
            if enable_wake_word and not no_tts:
                candidate = detector if detector is not None else barge_in_detector
                if isinstance(candidate, OpenWakeWordDetector):
                    # Never mutate/reuse the idle detector: it must retain its
                    # normal threshold when the reply completes.
                    active_detector = self._build_wake_word_detector(
                        input_device=input_device,
                        wake_word_threshold=TTS_BARGE_KWS_THRESHOLD,
                    )
                    pipeline.emit(
                        "kws_barge_started",
                        threshold=TTS_BARGE_KWS_THRESHOLD,
                    )
                else:
                    # Retain injected test detectors and the explicit ASR
                    # fallback path, which has no comparable KWS threshold.
                    active_detector = candidate
            return _TTSBargeInGuard(
                detector=active_detector,
                pipeline=pipeline,
            )

        network_warmup_done = threading.Event()
        network_warmup_started_at = time.perf_counter()

        def warm_network() -> None:
            try:
                proxies = self.network_client.select_proxies()
                pipeline.emit(
                    "network_warmed",
                    elapsed_ms=round(
                        (time.perf_counter() - network_warmup_started_at) * 1000,
                        1,
                    ),
                    proxy_label=self.network_client.selected_proxy_label or "",
                    proxy_enabled=bool(proxies),
                )
            except Exception as exc:
                pipeline.emit(
                    "network_warmup_failed",
                    elapsed_ms=round(
                        (time.perf_counter() - network_warmup_started_at) * 1000,
                        1,
                    ),
                    message=str(exc),
                )
            finally:
                network_warmup_done.set()

        pipeline.emit("network_warmup_started", proxy_mode=self.settings.proxy_mode)
        threading.Thread(target=warm_network, daemon=True).start()
        tts_client = None if no_tts else self.tts_client
        early_realtime_tts: _RealtimeTTSHandle | None = None
        guided_expression_active = self._guided_expression_is_active()
        realtime_tts_prewarm_enabled = os.environ.get(
            "XINGBAO_REALTIME_TTS_PREWARM", "1"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if (
            realtime_tts
            and not no_tts
            and no_quick_ack
            and streaming_response
            and not guided_expression_active
            and realtime_tts_prewarm_enabled
        ):
            early_realtime_tts = _RealtimeTTSHandle(
                settings=self.settings,
                voice_profile=self.voice_profile,
                output_device=output_device,
                pipeline=pipeline,
                interrupt_event=None,
            )
            early_realtime_tts.start_background(phase="recording_prewarm")
        streaming_asr_client: Any | None = None
        if streaming_asr:
            backend = _streaming_asr_backend()
            if backend == "cloud":
                model = realtime_asr_model or self.settings.cloud_streaming_asr_model
                streaming_asr_client = DashScopeStreamingRecognitionASRClient(
                    self.settings,
                    model=model,
                )
            else:
                streaming_asr_client = SherpaOnnxStreamingASRClient(self.settings)

            engine = (
                "dashscope_streaming_recognition"
                if backend == "cloud"
                else "sherpa_onnx_local_streaming"
            )
            model = getattr(streaming_asr_client, "model", None)
            set_partial_callback = getattr(streaming_asr_client, "set_partial_callback", None)
            if callable(set_partial_callback):
                set_partial_callback(
                    lambda text: pipeline.emit(
                        "asr_partial",
                        text=text,
                        text_chars=len(text),
                        engine=engine,
                        model=model,
                    )
                )
            # Establish the streaming connection before opening the microphone.
            # This keeps the capture callback non-blocking and preserves the
            # first syllables after the wake word for either backend.
            streaming_asr_client.start()
        listening_duration_seconds = (
            listen_timeout_seconds if listen_timeout_seconds > 0 else 30.0
        )

        def on_listening_ready() -> None:
            handoff_elapsed_ms = round(
                (time.perf_counter() - turn_handoff_started_at) * 1000,
                1,
            )
            pipeline.emit(
                "listening_ready",
                handoff_elapsed_ms=handoff_elapsed_ms,
            )
            self._notify_board_listening(
                board_ui_client,
                pipeline,
                duration_seconds=listening_duration_seconds,
            )

        capture_cancel_event = self._begin_guided_recovery_capture()
        try:
            wav_path, vad_info = capture_utterance_vad(
                audio_config=audio_config,
                vad_config=vad_config,
                on_listening_ready=on_listening_ready,
                audio_frame_callback=(
                    streaming_asr_client.send_audio_frame
                    if streaming_asr_client is not None
                    else None
                ),
                stop_event=capture_cancel_event,
            )
        except NoSpeechTimeout as exc:
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            self._raise_if_conversation_stop_requested()
            if self._external_read_aloud_active.is_set():
                pipeline.emit("asr_suppressed", reason="read_aloud_playback", phase="capture")
                raise ReadAloudPlaybackActive() from exc
            if self._has_guided_recovery_request():
                raise GuidedExpressionRecoveryRequested(
                    "Voice capture cancelled by guided-expression recovery."
                ) from exc
            raise
        except Exception as exc:
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            self._raise_if_conversation_stop_requested()
            if self._external_read_aloud_active.is_set():
                pipeline.emit("asr_suppressed", reason="read_aloud_playback", phase="capture")
                raise ReadAloudPlaybackActive() from exc
            # A tap can land while microphone capture is already returning an
            # error. The operator recovery still wins over that stale error,
            # otherwise the wake-chat loop would exit before it consumed the
            # requested scripted checkpoint.
            if self._has_guided_recovery_request():
                raise GuidedExpressionRecoveryRequested(
                    "Voice capture failure superseded by guided-expression recovery."
                ) from exc
            raise
        finally:
            self._finish_guided_recovery_capture(capture_cancel_event)
        self._raise_if_conversation_stop_requested()
        if self._external_read_aloud_active.is_set():
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            pipeline.emit("asr_suppressed", reason="read_aloud_playback", phase="after_capture")
            raise ReadAloudPlaybackActive()
        if self._has_guided_recovery_request():
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            raise GuidedExpressionRecoveryRequested(
                "Voice capture completed after guided-expression recovery."
            )
        pipeline.emit("speech_captured", audio_path=str(wav_path), vad=vad_info)
        cancel_processing_notice = self._notify_board_processing(
            board_ui_client,
            pipeline,
            delay_seconds=1.0,
        )
        # Streaming output is produced in lower-level helpers.  Keep this
        # per-turn cancellation hook on the pipeline so those helpers can
        # retire the delayed generic status before they publish tool/output
        # subtitles.
        setattr(pipeline, "_cancel_board_processing_notification", cancel_processing_notice)
        network_warmup_done.wait(timeout=0.05)
        early_lead_in_text = ""
        early_lead_in_played = False
        if (
            streaming_asr_client is not None
            and realtime_tts
            and not no_tts
            and no_quick_ack
            and streaming_response
            and early_realtime_tts is not None
        ):
            partial_text = normalize_asr_text(streaming_asr_client.partial_text())
            if self._looks_like_guided_expression_candidate(partial_text):
                early_realtime_tts.close_quietly()
                early_realtime_tts = None
            else:
                early_lead_in_text = _fast_lead_in_for_user_text(partial_text)
                early_fast_path = "partial_lead_in"
                if not early_lead_in_text:
                    early_lead_in_text = "我听到啦。"
                    early_fast_path = "instant_ack"
                if early_lead_in_text:
                    self._emit_tts_segment_queued(
                        pipeline,
                        early_lead_in_text,
                        1,
                        first_queue_elapsed_ms=0.0,
                        fast_path=early_fast_path,
                        partial_text=partial_text,
                    )
                    self._speak_fixed_realtime_tts(
                        early_lead_in_text,
                        tts_client=tts_client,
                        local_tts_fallback=local_tts_fallback,
                        output_device=output_device,
                        pipeline=pipeline,
                        interrupt_event=None,
                        prewarmed_tts=early_realtime_tts,
                        emit_queue_event=False,
                        close_after_enqueue=False,
                    )
                    early_lead_in_played = True

        if not no_quick_ack and not no_tts:
            quick_ack_thread = QuickAckManager(
                tts_client=tts_client,
                quick_ack_text=self.voice_profile.quick_ack_text,
                output_device=output_device,
            ).play_async(time.perf_counter())
            pipeline.emit(
                "quick_ack_started",
                output_device=output_device,
                kind="post_capture",
            )

        asr_started_at = time.perf_counter()
        active_asr_client = streaming_asr_client or self.asr_client
        pipeline.emit(
            "asr_started",
            audio_path=str(wav_path),
            capture_utterance_ms=vad_info.get("utterance_ms"),
            streaming=streaming_asr_client is not None,
            engine=type(active_asr_client).__name__,
            model=getattr(active_asr_client, "model", None),
        )
        cancel_asr = getattr(active_asr_client, "cancel", None)
        self._begin_guided_recovery_asr(
            cancel_asr if callable(cancel_asr) else None
        )
        try:
            raw_user_text = (
                streaming_asr_client.finish()
                if streaming_asr_client is not None
                else active_asr_client.transcribe(wav_path)
            )
        except EmptyRecognitionResult as exc:
            self._cancel_board_processing_notification(pipeline)
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            self._raise_if_conversation_stop_requested()
            if self._external_read_aloud_active.is_set():
                pipeline.emit("asr_suppressed", reason="read_aloud_playback", phase="asr")
                raise ReadAloudPlaybackActive() from exc
            if self._has_guided_recovery_request():
                raise GuidedExpressionRecoveryRequested(
                    "ASR result superseded by guided-expression recovery."
                ) from exc
            pipeline.emit(
                "asr_empty",
                audio_path=str(wav_path),
                reason=type(exc).__name__,
                elapsed_ms=round((time.perf_counter() - asr_started_at) * 1000, 1),
            )
            raise NoSpeechTimeout("No usable speech recognized in this turn.") from exc
        except Exception as exc:
            self._cancel_board_processing_notification(pipeline)
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            self._raise_if_conversation_stop_requested()
            if self._external_read_aloud_active.is_set():
                pipeline.emit("asr_suppressed", reason="read_aloud_playback", phase="asr")
                raise ReadAloudPlaybackActive() from exc
            if self._has_guided_recovery_request():
                raise GuidedExpressionRecoveryRequested(
                    "ASR failure superseded by guided-expression recovery."
                ) from exc
            pipeline.emit(
                "asr_failed",
                audio_path=str(wav_path),
                error_type=type(exc).__name__,
                error_message=str(exc)[:320],
                elapsed_ms=round((time.perf_counter() - asr_started_at) * 1000, 1),
            )
            raise
        finally:
            self._finish_guided_recovery_asr(cancel_asr)
        self._raise_if_conversation_stop_requested()
        if self._external_read_aloud_active.is_set():
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            pipeline.emit("asr_suppressed", reason="read_aloud_playback", phase="after_asr")
            raise ReadAloudPlaybackActive()
        if self._has_guided_recovery_request():
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            raise GuidedExpressionRecoveryRequested(
                "ASR result superseded by guided-expression recovery."
            )
        user_text = normalize_asr_text(raw_user_text)
        if not user_text:
            self._cancel_board_processing_notification(pipeline)
            if streaming_asr_client is not None:
                streaming_asr_client.cancel()
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            pipeline.emit(
                "asr_empty",
                audio_path=str(wav_path),
                reason="empty_text",
                elapsed_ms=round((time.perf_counter() - asr_started_at) * 1000, 1),
            )
            raise NoSpeechTimeout("No usable speech recognized in this turn.")
        self._raise_if_conversation_stop_requested()
        asr_metrics = getattr(active_asr_client, "last_metrics", {})
        if not isinstance(asr_metrics, dict):
            asr_metrics = {}
        pipeline.emit(
            "asr_final",
            text=user_text,
            text_chars=len(user_text),
            audio_path=str(wav_path),
            elapsed_ms=round((time.perf_counter() - asr_started_at) * 1000, 1),
            encode_ms=asr_metrics.get("encode_ms"),
            request_ms=asr_metrics.get("request_ms"),
            total_stream_ms=asr_metrics.get("total_stream_ms"),
            frames=asr_metrics.get("frames"),
            bytes=asr_metrics.get("bytes"),
            engine=asr_metrics.get("engine"),
            model=asr_metrics.get("model"),
        )
        arm_dispatch = dispatch_voice_arm_action(user_text)
        if arm_dispatch.get("queued"):
            # Mechanical-arm interactions own their presentation immediately,
            # before the LLM/TTS turn begins.  This also covers commands whose
            # streamed LLM scene marker is late or absent.
            self._send_xingbao_scene(board_ui_client, 25, "voice_arm_interaction")
            pipeline.emit("arm_action_queued", **arm_dispatch)
        elif arm_dispatch["matched"]:
            pipeline.emit("arm_action_skipped", **arm_dispatch)
        if _is_wake_only_text(user_text, self.settings.wake_word):
            reply = "我在呢。你想聊什么？"
            turn = self.session.record_assistant_turn(
                user_text=user_text,
                assistant_text=reply,
                action_proposal={"screen_expression": "smile"},
            )
            self._emit_tts_segment_queued(
                pipeline,
                reply,
                1,
                first_queue_elapsed_ms=0.0,
                fast_path="wake_only",
            )
            barge_in = make_barge_in_guard().start()
            if realtime_tts and not no_tts:
                self._speak_fixed_realtime_tts(
                    reply,
                    tts_client=tts_client,
                    local_tts_fallback=local_tts_fallback,
                    output_device=output_device,
                    pipeline=pipeline,
                    interrupt_event=barge_in.stop_event,
                    prewarmed_tts=early_realtime_tts,
                    emit_queue_event=False,
                )
                barge_in.stop()
            else:
                speak(
                    reply,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_tts_fallback,
                    output_device=output_device,
                    interrupt_event=barge_in.stop_event,
                )
                barge_in.stop()
                _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=reply,
                action=turn.action,
                audio_path=str(wav_path),
                tts_interrupted=barge_in.interrupted,
                fast_path="wake_only",
            )
        # Every end/pause decision is delegated to the LLM Function Calling
        # turn.  The current wake-chat session may close only after the model
        # explicitly requests the end_conversation tool.
        if self.llm_client.request_conversation_end(
            user_text,
            self._build_turn_system_prompt(user_text),
            history=self.session.as_chat_history(),
        ):
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            reply = "好的，星宝先暂停对话。想继续时再叫我星宝星宝哦。"
            pipeline.emit("llm_conversation_end_requested", user_text=user_text)
            turn = self.session.record_assistant_turn(
                user_text=user_text,
                assistant_text=reply,
                action_proposal={"screen_expression": "sleepy"},
            )
            if serial_port:
                with SerialBridge(serial_port, action_bus=self.session.action_bus) as bridge:
                    bridge.send_action(turn.action)
            self._emit_tts_segment_queued(pipeline, reply, 1, fast_path="llm_exit_request")
            barge_in = make_barge_in_guard().start()
            speak(
                reply,
                tts_client=tts_client,
                no_tts=no_tts,
                local_fallback=local_tts_fallback,
                output_device=output_device,
                interrupt_event=barge_in.stop_event,
            )
            barge_in.stop()
            _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=reply,
                action=turn.action,
                audio_path=str(wav_path),
                end_session=True,
                session_end_reason="llm_exit_request",
                tts_interrupted=barge_in.interrupted,
                fast_path="llm_exit_request",
            )

        # This presentation route is intentionally stricter than semantic
        # matching: only the literal, contiguous keyword "情绪" is accepted.
        # Similar expressions such as "心情" or "感受" remain ordinary chat.
        if _has_exact_emotion_keyword(user_text):
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            reply = "你看上去很开心。"
            if board_ui_client is not None:
                try:
                    board_ui_client.send_ui_command(
                        None,
                        screen_text=reply,
                        expression="smile",
                        led_mode="warm_breath",
                        duration_ms=8000,
                        subtitle_priority="dialogue",
                    )
                except OSError:
                    pass
            turn = self.session.record_assistant_turn(
                user_text=user_text,
                assistant_text=reply,
                action_proposal={
                    "screen_expression": "smile",
                    "led_mode": "warm_breath",
                },
            )
            self._emit_tts_segment_queued(
                pipeline,
                reply,
                1,
                first_queue_elapsed_ms=0.0,
                fast_path="fixed_emotion_check",
            )
            barge_in = make_barge_in_guard().start()
            self._speak_with_demo_cache(
                reply,
                tts_client=tts_client,
                no_tts=no_tts,
                local_fallback=local_tts_fallback,
                output_device=output_device,
                interrupt_event=barge_in.stop_event,
            )
            barge_in.stop()
            _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=reply,
                action=turn.action,
                audio_path=str(wav_path),
                tts_interrupted=barge_in.interrupted,
                fast_path="fixed_emotion_check",
            )

        game_status_query = resolve_game_status_query(user_text)
        if board_ui_client is not None and game_status_query is not None:
            with self._external_tts_lock:
                if early_realtime_tts is not None:
                    early_realtime_tts.close_quietly()
                command = game_status_query.as_command(user_text)
                try:
                    board_result = board_ui_client.send_game_command(command)
                    game_response = board_result.get("game_response") or {}
                    pipeline.emit(
                        "board_ui_game_command",
                        ok=bool(board_result.get("ok")),
                        intent=game_status_query.intent,
                        response=board_result.get("response"),
                        game_response=game_response,
                    )
                except OSError as exc:
                    game_response = {
                        "ok": False,
                        "message": "当前小游戏还没有准备好，星宝先陪你等一下。",
                    }
                    pipeline.emit(
                        "board_ui_game_command_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
                reply = str(game_response.get("message") or "当前小游戏还没有准备好。")
                feedback = game_response.get("feedback")
                if not isinstance(feedback, dict):
                    feedback = {}
                expression = str(feedback.get("screen_expression") or "thinking")
                turn = self.session.record_assistant_turn(
                    user_text=user_text,
                    assistant_text=reply,
                    action_proposal={
                        "screen_expression": _screen_expression_for(expression),
                        "led_mode": _led_mode_for(expression),
                    },
                )
                self._emit_tts_segment_queued(
                    pipeline,
                    reply,
                    1,
                    first_queue_elapsed_ms=0.0,
                    fast_path="fixed_game_status",
                    intent=game_status_query.intent,
                )
                barge_in = make_barge_in_guard().start()
                speak(
                    reply,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_tts_fallback,
                    output_device=output_device,
                    interrupt_event=barge_in.stop_event,
                )
                barge_in.stop()
                _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
                return VoiceTurnResult(
                    user_text=user_text,
                    assistant_text=reply,
                    action=turn.action,
                    audio_path=str(wav_path),
                    tts_interrupted=barge_in.interrupted,
                    fast_path="fixed_game_status",
                )

        coordination_plan = self.coordinator.plan_text(user_text)
        if (
            board_ui_client is not None
            and coordination_plan.intent.intent == "open_tool"
            and coordination_plan.intent.target == "mini_game_hub"
        ):
            with self._external_tts_lock:
                if early_realtime_tts is not None:
                    early_realtime_tts.close_quietly()
                try:
                    board_result = board_ui_client.send_plan(coordination_plan)
                    pipeline.emit(
                        "board_ui_assistant_output",
                        ok=bool(board_result.get("ok")),
                        response=board_result.get("response"),
                        arm=board_result.get("arm"),
                    )
                except OSError as exc:
                    board_result = {
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                    pipeline.emit(
                        "board_ui_assistant_output_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
                ui_ready = bool(board_result.get("ok"))
                if os.environ.get("XINGBAO_DEMO_GAME_FLOW", "1") != "0":
                    reply = (
                        "\u8fdb\u5165\u6e38\u620f\u5566\uff0c"
                        "\u8bf7\u9009\u62e9\u4e00\u4e2a\u6e38\u620f\uff0c"
                        "\u518d\u9009\u62e9\u96be\u5ea6\u3002"
                        if ui_ready
                        else "\u6e38\u620f\u754c\u9762\u8fd8\u6ca1\u51c6\u5907\u597d\uff0c\u6211\u4eec\u7a0d\u7b49\u4e00\u4e0b\u3002"
                    )
                    output = coordination_plan.expression_output
                    action_proposal = {
                        "screen_expression": _screen_expression_for(
                            output.expression if ui_ready else "thinking"
                        ),
                        "led_mode": _led_mode_for(
                            output.expression if ui_ready else "thinking"
                        ),
                    }
                    turn = self.session.record_assistant_turn(
                        user_text=user_text,
                        assistant_text=reply,
                        action_proposal=action_proposal,
                    )
                    pipeline.emit(
                        "demo_game_prompt",
                        ui_ready=ui_ready,
                        text=reply,
                    )
                    self._emit_tts_segment_queued(
                        pipeline,
                        reply,
                        1,
                        first_queue_elapsed_ms=0.0,
                        fast_path="demo_open_game",
                    )
                    barge_in = make_barge_in_guard().start()
                    self._speak_with_demo_cache(
                        reply,
                        tts_client=tts_client,
                        no_tts=no_tts,
                        local_fallback=local_tts_fallback,
                        output_device=output_device,
                        interrupt_event=barge_in.stop_event,
                    )
                    barge_in.stop()
                    _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
                    return VoiceTurnResult(
                        user_text=user_text,
                        assistant_text=reply,
                        action=turn.action,
                        audio_path=str(wav_path),
                        end_session=True,
                        tts_interrupted=barge_in.interrupted,
                        fast_path="demo_open_game",
                    )
                tool_prompt = self._build_turn_system_prompt(user_text) + (
                    "\n\n系统动作信息：触控主界面已经执行了孩子请求的游戏操作。"
                    "请根据孩子原话，用一句自然、活泼且不重复套话的中文回应。"
                    "不要解释接口、状态机或技术过程。"
                    if ui_ready
                    else
                    "\n\n系统动作信息：触控主界面当前不可用，不能打开游戏。"
                    "请用一句自然、简短且有变化的中文告诉孩子稍等，不要编造已经打开。"
                )
                reply = self.llm_client.generate_reply(
                    user_text,
                    tool_prompt,
                    history=self.session.as_chat_history(),
                )
                pipeline.emit(
                    "llm_delta",
                    text=reply,
                    index=1,
                    elapsed_ms=None,
                    first_delta_elapsed_ms=None,
                )
                output = coordination_plan.expression_output
                action_proposal = {
                    "screen_expression": _screen_expression_for(
                        output.expression if ui_ready else "thinking"
                    ),
                    "led_mode": _led_mode_for(
                        output.expression if ui_ready else "thinking"
                    ),
                }
                turn = self.session.record_assistant_turn(
                    user_text=user_text,
                    assistant_text=reply,
                    action_proposal=action_proposal,
                )
                self._emit_tts_segment_queued(
                    pipeline,
                    reply,
                    1,
                    first_queue_elapsed_ms=0.0,
                    fast_path="board_ui_llm",
                )
                barge_in = make_barge_in_guard().start()
                speak(
                    reply,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_tts_fallback,
                    output_device=output_device,
                    interrupt_event=barge_in.stop_event,
                )
                barge_in.stop()
                _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=reply,
                action=turn.action,
                audio_path=str(wav_path),
                tts_interrupted=barge_in.interrupted,
                fast_path="board_ui_llm",
            )

        if board_ui_client is not None:
            try:
                board_result = board_ui_client.send_plan(coordination_plan)
                pipeline.emit(
                    "board_ui_assistant_output",
                    ok=bool(board_result.get("ok")),
                    response=board_result.get("response"),
                    arm=board_result.get("arm"),
                )
            except OSError as exc:
                pipeline.emit(
                    "board_ui_assistant_output_failed",
                    error=type(exc).__name__,
                    message=str(exc),
                )

        self._update_memory_from_user_text(user_text)
        guided_reply = self.handle_guided_expression_text(user_text)
        if guided_reply is None:
            # The local flow remains the primary route. This is only a
            # narrowly scoped LLM fallback for ASR wording variants that
            # still clearly contain a self-introduction and dinosaur interest.
            canonical_dinosaur_intro = self._llm_dinosaur_script_fallback(user_text)
            if canonical_dinosaur_intro:
                guided_reply = self.handle_guided_expression_text(
                    canonical_dinosaur_intro
                )
        if guided_reply is not None:
            # A guided-script reply is allowed only after VAD has closed the
            # utterance and a final ASR result exists. Keep a short visible
            # pause afterwards so Xingbao never appears to interrupt Actor A.
            if not no_tts:
                time.sleep(FINALS_GUIDED_RESPONSE_DELAY_SECONDS)
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            reply = guided_reply.text
            cache_filename = DEMO_TTS_CACHE_FILES.get(sanitize_tts_text(reply))
            cache_hit = bool(
                cache_filename
                and self.game_speech_cache.is_valid(Path("work/cache") / cache_filename)
            )
            pipeline.emit(
                "guided_expression_decision",
                scene=guided_reply.scene,
                stage=guided_reply.stage,
                end_session=guided_reply.end_session,
                tts_route="cached_wav" if cache_hit else "batch_tts_fallback",
            )
            turn = self.session.record_assistant_turn(
                user_text=user_text,
                assistant_text=reply,
                action_proposal={
                    "screen_expression": _screen_expression_for(
                        guided_reply.screen_expression
                    ),
                    "led_mode": guided_reply.led_mode,
                },
            )
            self._emit_tts_segment_queued(
                pipeline,
                reply,
                1,
                first_queue_elapsed_ms=0.0,
                fast_path="guided_expression",
                scene=guided_reply.scene,
                cached=cache_hit,
            )
            barge_in = make_barge_in_guard().start()
            self._speak_with_demo_cache(
                reply,
                tts_client=tts_client,
                no_tts=no_tts,
                local_fallback=local_tts_fallback,
                output_device=output_device,
                interrupt_event=barge_in.stop_event,
            )
            barge_in.stop()
            _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
            high_five_baseline = (
                _read_high_five_status_quietly()
                if guided_reply.post_tts_arm_action == "high_five"
                and not no_tts
                and not barge_in.interrupted
                else None
            )
            post_tts_arm_dispatch = _dispatch_guided_post_tts_arm_action(
                guided_reply.post_tts_arm_action,
                enabled=not no_tts and not barge_in.interrupted,
            )
            if post_tts_arm_dispatch.get("queued"):
                self._guided_expression_handoff_active.set()
            if post_tts_arm_dispatch.get("queued"):
                pipeline.emit(
                    "arm_action_queued",
                    source="guided_expression_post_tts",
                    **post_tts_arm_dispatch,
                )
            elif post_tts_arm_dispatch.get("matched"):
                pipeline.emit(
                    "arm_action_skipped",
                    source="guided_expression_post_tts",
                    **post_tts_arm_dispatch,
                )
            if guided_reply.scene == "dinosaur_drawing_accepted":
                self._scripted_memory_recall_armed.set()
                if not barge_in.interrupted:
                    self._open_dinosaur_drawing_board(board_ui_client, pipeline)

            def speak_high_five_line(text: str) -> None:
                self._speak_with_demo_cache(
                    text,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_tts_fallback,
                    output_device=output_device,
                )

            showcase_started = _start_finals_post_high_five_showcase(
                baseline_status=high_five_baseline,
                dispatch_result=post_tts_arm_dispatch,
                speak_line=speak_high_five_line,
                on_ready_for_drawing=lambda: self.request_scripted_followup(
                    "drawing_consent"
                ),
            )
            if showcase_started:
                pipeline.emit(
                    "finals_post_high_five_showcase_queued",
                    source="guided_expression_post_tts",
                )
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=reply,
                action=turn.action,
                audio_path=str(wav_path),
                end_session=guided_reply.end_session,
                session_end_reason=_guided_expression_session_end_reason(guided_reply),
                tts_interrupted=barge_in.interrupted,
                fast_path="guided_expression",
            )
        prepared_reply = self._prepared_reply_for_user_text(user_text)
        if prepared_reply:
            if early_realtime_tts is not None and (not realtime_tts or no_tts):
                early_realtime_tts.close_quietly()
            turn = self.session.record_assistant_turn(
                user_text=user_text,
                assistant_text=prepared_reply,
                action_proposal={
                    "screen_expression": "smile",
                    "led_mode": "warm_breath",
                },
            )
            self._emit_tts_segment_queued(
                pipeline,
                prepared_reply,
                1,
                first_queue_elapsed_ms=0.0,
                fast_path="prepared_knowledge",
            )
            barge_in = make_barge_in_guard().start()
            if realtime_tts and not no_tts:
                self._speak_fixed_realtime_tts(
                    prepared_reply,
                    tts_client=tts_client,
                    local_tts_fallback=local_tts_fallback,
                    output_device=output_device,
                    pipeline=pipeline,
                    interrupt_event=barge_in.stop_event,
                    prewarmed_tts=early_realtime_tts,
                    emit_queue_event=False,
                )
                barge_in.stop()
            else:
                speak(
                    prepared_reply,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_tts_fallback,
                    output_device=output_device,
                    interrupt_event=barge_in.stop_event,
                )
                barge_in.stop()
                _emit_playback_done(pipeline, prepared_reply, 1, skipped=no_tts)
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=prepared_reply,
                action=turn.action,
                audio_path=str(wav_path),
                tts_interrupted=barge_in.interrupted,
                fast_path="prepared_knowledge",
            )

        growth_plan = self._growth_guidance_plan_for_user_text(user_text)
        if growth_plan is not None:
            pipeline.emit(
                "growth_guidance_decision",
                scene=growth_plan.scene,
                reason=growth_plan.reason,
                priority=growth_plan.priority,
                handled=growth_plan.handled,
                topic_id=growth_plan.topic_id,
            )
        if growth_plan is not None and _should_use_growth_guidance_plan(growth_plan):
            if early_realtime_tts is not None and (not realtime_tts or no_tts):
                early_realtime_tts.close_quietly()
            if growth_plan.memory_request:
                self.session.memory_manager.update(growth_plan.memory_request)
            reply = growth_plan.speak_text
            turn = self.session.record_assistant_turn(
                user_text=user_text,
                assistant_text=reply,
                action_proposal={
                    "screen_expression": _screen_expression_for(growth_plan.expression),
                    "led_mode": growth_plan.led_mode,
                },
            )
            if serial_port:
                with SerialBridge(serial_port, action_bus=self.session.action_bus) as bridge:
                    bridge.send_action(turn.action)
            self._emit_tts_segment_queued(
                pipeline,
                reply,
                1,
                first_queue_elapsed_ms=0.0,
                fast_path="growth_guidance",
                scene=growth_plan.scene,
            )
            barge_in = make_barge_in_guard().start()
            if realtime_tts and not no_tts:
                self._speak_fixed_realtime_tts(
                    reply,
                    tts_client=tts_client,
                    local_tts_fallback=local_tts_fallback,
                    output_device=output_device,
                    pipeline=pipeline,
                    interrupt_event=barge_in.stop_event,
                    prewarmed_tts=early_realtime_tts,
                    emit_queue_event=False,
                )
                barge_in.stop()
            else:
                speak(
                    reply,
                    tts_client=tts_client,
                    no_tts=no_tts,
                    local_fallback=local_tts_fallback,
                    output_device=output_device,
                    interrupt_event=barge_in.stop_event,
                )
                barge_in.stop()
                _emit_playback_done(pipeline, reply, 1, skipped=no_tts)
            return VoiceTurnResult(
                user_text=user_text,
                assistant_text=reply,
                action=turn.action,
                audio_path=str(wav_path),
                tts_interrupted=barge_in.interrupted,
                fast_path="growth_guidance",
            )
        system_prompt = self._build_turn_system_prompt(user_text, growth_plan=growth_plan)
        history = self.session.as_chat_history()
        self._stream_scene_id = 0
        self._stream_scene_callback = lambda scene_id: self._send_xingbao_scene(
            board_ui_client, scene_id, "llm"
        )
        if streaming_response:
            if realtime_tts and not no_tts:
                barge_in = make_barge_in_guard().start()
                try:
                    reply = self._generate_and_speak_realtime_tts(
                        user_text,
                        system_prompt,
                        history=history,
                        tts_client=tts_client,
                        local_tts_fallback=local_tts_fallback,
                        output_device=output_device,
                        pipeline=pipeline,
                        interrupt_event=barge_in.stop_event,
                        prewarmed_tts=early_realtime_tts,
                        lead_in_text=(
                            _fast_lead_in_for_user_text(user_text)
                            if (
                                not early_lead_in_played
                                and _looks_like_story_request(user_text)
                            )
                            else ""
                        ),
                        reply_prefix=early_lead_in_text if early_lead_in_played else "",
                    )
                finally:
                    # Cloud generation can fail before any TTS audio is
                    # produced. Always stop its wake-word worker; otherwise
                    # it survives into the next wake session and consumes the
                    # next "星宝星宝" as a stale TTS interruption.
                    barge_in.stop()
            else:
                if early_realtime_tts is not None:
                    early_realtime_tts.close_quietly()
                barge_in = make_barge_in_guard().start()
                try:
                    reply = self._generate_and_speak_streaming(
                        user_text,
                        system_prompt,
                        history=history,
                        tts_client=tts_client,
                        no_tts=no_tts,
                        local_tts_fallback=local_tts_fallback,
                        output_device=output_device,
                        pipeline=pipeline,
                        interrupt_event=barge_in.stop_event,
                    )
                finally:
                    barge_in.stop()
        else:
            if early_realtime_tts is not None:
                early_realtime_tts.close_quietly()
            reply = self.llm_client.generate_reply(
                user_text,
                system_prompt,
                history=history,
            )
            reply, self._stream_scene_id = self._scene_turn_selector.select(
                user_text, reply
            )
            barge_in = make_barge_in_guard()
        scene_id = self._stream_scene_id
        if board_ui_client is not None and not streaming_response:
            try:
                scene_result = board_ui_client.send_xingbao_scene(scene_id, source="llm")
                pipeline.emit("xingbao_scene", scene_id=scene_id, ok=bool(scene_result.get("ok")))
            except (OSError, ValueError) as exc:
                pipeline.emit("xingbao_scene_failed", scene_id=scene_id, error=type(exc).__name__)
        turn = self.session.record_assistant_turn(
            user_text=user_text,
            assistant_text=reply,
            action_proposal={
                "screen_expression": "smile",
            },
        )

        if serial_port:
            with SerialBridge(serial_port, action_bus=self.session.action_bus) as bridge:
                bridge.send_action(turn.action)

        if not streaming_response:
            speech_reply = sanitize_tts_text(reply)
            self._emit_tts_segment_queued(pipeline, speech_reply, 1)
            barge_in.start()
            speak(
                speech_reply,
                tts_client=tts_client,
                no_tts=no_tts,
                local_fallback=local_tts_fallback,
                output_device=output_device,
                interrupt_event=barge_in.stop_event,
            )
            barge_in.stop()
            _emit_playback_done(pipeline, speech_reply, 1, skipped=no_tts)
        reply_commits_to_end = _reply_commits_to_conversation_end(reply)
        if reply_commits_to_end:
            # The function-call selector is the primary mechanism.  This is
            # a narrow recovery for a contradictory model response: it has
            # already told the child that the conversation is paused, but
            # omitted end_conversation.  Never continue listening after that
            # promise.
            pipeline.emit(
                "llm_conversation_end_requested",
                user_text=user_text,
                recovered_from_reply=True,
            )
        return VoiceTurnResult(
            user_text=user_text,
            assistant_text=reply,
            action=turn.action,
            audio_path=str(wav_path),
            end_session=reply_commits_to_end,
            session_end_reason=("llm_reply_end_recovery" if reply_commits_to_end else ""),
            tts_interrupted=barge_in.interrupted,
        )

    def _update_memory_from_user_text(self, user_text: str) -> None:
        profile_result = self.session.profile_extractor.extract(user_text)
        if profile_result.updates:
            self.session.memory_manager.update(profile_result.updates)

    def handle_guided_expression_text(
        self,
        user_text: str,
    ) -> GuidedExpressionReply | None:
        """Run one reviewed scene turn, yielding unmatched text to normal routes."""
        if not DINOSAUR_SCRIPT_ENABLED:
            return None
        reply = self.guided_expression_flow.handle(
            user_text,
            memory=self.session.memory_manager.load(),
        )
        if reply is not None and reply.memory_update:
            self.session.memory_manager.update(reply.memory_update)
        return reply

    def request_guided_expression_recovery(self) -> dict[str, Any]:
        """Queue one operator-requested completion of the current script step.

        The touch UI calls this when live audio has been interrupted.  The
        active VAD capture and cancellable streaming ASR are stopped
        immediately; any late ASR result is discarded by the wake-chat loop.
        The loop then consumes the normal
        scripted input for the current stage and speaks the ordinary next
        reply from the pre-cached demonstration lines.
        """
        if not DINOSAUR_SCRIPT_ENABLED:
            self._clear_guided_expression_handoff()
            return {"ok": False, "reason": "dinosaur_script_disabled", "stage": IDLE}
        recovery_input = self.guided_expression_flow.recovery_input_for_current_step()
        snapshot = self.guided_expression_flow.snapshot()
        if not recovery_input:
            return {
                "ok": False,
                "reason": "guided_expression_not_active",
                "stage": snapshot.stage,
            }
        with self._guided_recovery_lock:
            self._guided_recovery_input = recovery_input
            self._guided_recovery_requested.set()
            active_capture = self._active_voice_capture_cancel
            active_asr_cancel = self._active_voice_asr_cancel
            if active_capture is not None:
                active_capture.set()
        if active_asr_cancel is not None:
            try:
                active_asr_cancel()
            except Exception:
                # Cancellation is best-effort. The pending-recovery flag
                # still discards this stale result if it returns afterwards.
                pass
        return {
            "ok": True,
            "stage": snapshot.stage,
            "recovery_input": recovery_input,
        }

    def request_conversation_stop(self, *, silent: bool = False) -> dict[str, Any]:
        """Stop only the current wake-chat session from the touch desktop.

        This never stops the voice service.  It clears an unfinished guided
        dinosaur handoff even when no microphone session is currently active,
        and otherwise ends only the current listening session.  The reset is
        limited to transient script state: persistent child memory and every
        other product capability remain intact.
        """
        # Stop the active PCM stream first and set every conversation TTS
        # guard's event. Realtime players discard queued fragments when that
        # event is set, so the stop button is an immediate interrupt + queue
        # flush rather than merely a later session-state change.
        _TTSBargeInGuard.stop_all()
        tts_interrupted = interrupt_active_realtime_playback()
        with self._guided_recovery_lock:
            session_active = self._voice_chat_session_active.is_set()
            handoff_active = self._guided_expression_handoff_active.is_set()
            if session_active:
                self._conversation_stop_requested.set()
                if silent:
                    self._conversation_stop_silent.set()
                else:
                    self._conversation_stop_silent.clear()
            # A direct stop has higher priority than a queued recovery step.
            self._clear_guided_expression_handoff_locked()
            active_capture = self._active_voice_capture_cancel
            active_asr_cancel = self._active_voice_asr_cancel
            if session_active and active_capture is not None:
                active_capture.set()
        if not session_active:
            return {
                "ok": handoff_active,
                "tts_interrupted": tts_interrupted,
                "reason": (
                    "guided_expression_handoff_cancelled"
                    if handoff_active
                    else "no_active_voice_session"
                ),
            }
        if active_asr_cancel is not None:
            try:
                active_asr_cancel()
            except Exception:
                pass
        return {
            "ok": True,
            "reason": "manual_stop",
            "tts_interrupted": tts_interrupted,
        }

    def _clear_guided_expression_handoff(self) -> None:
        """End only transient dinosaur-script state, retaining saved memory."""
        with self._guided_recovery_lock:
            self._clear_guided_expression_handoff_locked()

    def _clear_guided_expression_handoff_locked(self) -> None:
        """Locked implementation shared by normal completion and cancellation."""
        self._guided_recovery_input = ""
        self._guided_recovery_requested.clear()
        self._guided_expression_handoff_active.clear()
        self._scripted_followup_requested.clear()
        self._scripted_followup_kind = ""
        self._scripted_memory_recall_armed.clear()
        self._synthetic_wake_requested.clear()
        self.guided_expression_flow.reset()

    def request_synthetic_wake(self) -> dict[str, Any]:
        """Treat the touch command as one trusted ``星宝星宝`` wake phrase."""
        if self._voice_chat_session_active.is_set():
            return {"ok": False, "reason": "voice_session_already_active"}
        with self._guided_recovery_lock:
            self._synthetic_wake_requested.set()
            active_wake_wait = self._active_wake_wait_cancel
            if active_wake_wait is not None:
                active_wake_wait.set()
        return {"ok": True, "keyword": self.settings.wake_word}

    def request_scripted_followup(self, kind: str) -> dict[str, Any]:
        """Open one no-wake listening turn required by the reviewed finals script."""
        if not DINOSAUR_SCRIPT_ENABLED:
            self._clear_guided_expression_handoff()
            return {"ok": False, "reason": "dinosaur_script_disabled"}
        clean_kind = str(kind or "").strip()
        snapshot = self.guided_expression_flow.snapshot()
        if clean_kind == "drawing_consent":
            if snapshot.stage != "wait_drawing_consent":
                return {"ok": False, "reason": "drawing_consent_not_pending"}
        elif clean_kind == "memory_recall":
            if not self._scripted_memory_recall_armed.is_set():
                return {"ok": False, "reason": "memory_recall_not_armed"}
            self._scripted_memory_recall_armed.clear()
        else:
            return {"ok": False, "reason": "unsupported_scripted_followup"}
        with self._guided_recovery_lock:
            self._scripted_followup_kind = clean_kind
            self._scripted_followup_requested.set()
            active_wake_wait = self._active_wake_wait_cancel
            if active_wake_wait is not None:
                active_wake_wait.set()
        return {"ok": True, "kind": clean_kind}

    def _begin_synthetic_wake_wait(self) -> threading.Event:
        cancel_event = threading.Event()
        with self._guided_recovery_lock:
            self._active_wake_wait_cancel = cancel_event
            if (
                self._synthetic_wake_requested.is_set()
                or self._scripted_followup_requested.is_set()
                or self._external_read_aloud_active.is_set()
            ):
                cancel_event.set()
        return cancel_event

    def _begin_external_read_aloud(self) -> None:
        """Disable wake and ASR while UI subtitle point-read audio plays."""
        with self._guided_recovery_lock:
            self._external_read_aloud_depth += 1
            self._external_read_aloud_active.set()
            active_wake_wait = self._active_wake_wait_cancel
            active_capture = self._active_voice_capture_cancel
            active_asr_cancel = self._active_voice_asr_cancel
            if active_wake_wait is not None:
                active_wake_wait.set()
            if active_capture is not None:
                active_capture.set()
        if active_asr_cancel is not None:
            try:
                active_asr_cancel()
            except Exception:
                # Cancellation is best-effort; the active flag still makes
                # any late recognition result ineligible for LLM processing.
                pass

    def _finish_external_read_aloud(self) -> None:
        with self._guided_recovery_lock:
            self._external_read_aloud_depth = max(0, self._external_read_aloud_depth - 1)
            if self._external_read_aloud_depth == 0:
                self._external_read_aloud_active.clear()

    def _finish_synthetic_wake_wait(self, cancel_event: threading.Event) -> None:
        with self._guided_recovery_lock:
            if self._active_wake_wait_cancel is cancel_event:
                self._active_wake_wait_cancel = None

    def _take_synthetic_wake_request(self) -> bool:
        with self._guided_recovery_lock:
            if not self._synthetic_wake_requested.is_set():
                return False
            self._synthetic_wake_requested.clear()
            return True

    def _take_scripted_followup_request(self) -> str:
        with self._guided_recovery_lock:
            if not self._scripted_followup_requested.is_set():
                return ""
            kind = self._scripted_followup_kind
            self._scripted_followup_kind = ""
            self._scripted_followup_requested.clear()
            return kind

    @staticmethod
    def _wait_for_wake_word_with_cancel(
        detector: Any,
        cancel_event: threading.Event,
    ) -> str:
        """Use cancellation when supported, retaining compatibility with fakes."""
        try:
            return detector.wait_for_wake_word(stop_event=cancel_event)
        except TypeError as exc:
            # Older test doubles and third-party detectors may not accept the
            # optional cancellation argument. Only retry their original
            # signature; do not hide a TypeError raised inside a compatible
            # implementation.
            if "stop_event" not in str(exc):
                raise
            return detector.wait_for_wake_word()

    def _begin_guided_recovery_capture(self) -> threading.Event:
        cancel_event = threading.Event()
        with self._guided_recovery_lock:
            self._active_voice_capture_cancel = cancel_event
            if (
                self._guided_recovery_requested.is_set()
                or self._conversation_stop_requested.is_set()
                or self._external_read_aloud_active.is_set()
            ):
                cancel_event.set()
        return cancel_event

    def _finish_guided_recovery_capture(self, cancel_event: threading.Event) -> None:
        with self._guided_recovery_lock:
            if self._active_voice_capture_cancel is cancel_event:
                self._active_voice_capture_cancel = None

    def _begin_guided_recovery_asr(
        self,
        cancel: Callable[[], Any] | None,
    ) -> None:
        """Expose one cancellable ASR operation to the touch recovery action."""
        if cancel is None:
            return
        with self._guided_recovery_lock:
            self._active_voice_asr_cancel = cancel
            cancel_now = (
                self._guided_recovery_requested.is_set()
                or self._conversation_stop_requested.is_set()
                or self._external_read_aloud_active.is_set()
            )
        if cancel_now:
            try:
                cancel()
            except Exception:
                pass

    def _finish_guided_recovery_asr(
        self,
        cancel: Callable[[], Any] | None,
    ) -> None:
        if cancel is None:
            return
        with self._guided_recovery_lock:
            if self._active_voice_asr_cancel is cancel:
                self._active_voice_asr_cancel = None

    def _has_guided_recovery_request(self) -> bool:
        return self._guided_recovery_requested.is_set()

    def _has_conversation_stop_request(self) -> bool:
        return self._conversation_stop_requested.is_set()

    def _raise_if_conversation_stop_requested(self) -> None:
        if self._has_conversation_stop_request():
            raise ConversationStopRequested("Conversation stopped from the touch UI.")

    def _take_conversation_stop_request(self) -> bool:
        with self._guided_recovery_lock:
            if not self._conversation_stop_requested.is_set():
                return False
            self._conversation_stop_requested.clear()
            return True

    def _take_guided_recovery_input(self) -> str:
        with self._guided_recovery_lock:
            if not self._guided_recovery_requested.is_set():
                return ""
            recovery_input = self._guided_recovery_input
            self._guided_recovery_input = ""
            self._guided_recovery_requested.clear()
            return recovery_input

    def _guided_expression_is_active(self) -> bool:
        if not DINOSAUR_SCRIPT_ENABLED:
            return False
        snapshot = self.guided_expression_flow.snapshot()
        return snapshot.stage != IDLE and not snapshot.suspended

    def _looks_like_guided_expression_candidate(self, text: str) -> bool:
        """Reserve the deterministic audio route for the reviewed dinosaur scene."""
        if not DINOSAUR_SCRIPT_ENABLED:
            return False
        if self._guided_expression_is_active():
            return True
        compact = _compact_chinese_text(text)
        return "恐龙" in compact and any(
            marker in compact
            for marker in ("我叫", "我是", "叫我", "喜欢", "感兴趣")
        )

    def observe_vision_state(self, message: dict[str, Any]) -> bool:
        """Feed only a high-level emotion label into the guided scene."""
        if not DINOSAUR_SCRIPT_ENABLED:
            return False
        if str(message.get("type") or "").strip() != "vision_state":
            return False
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return False
        state = str(payload.get("state") or payload.get("event") or "").strip()
        if state != "child_emotion_detected":
            return False
        return self.guided_expression_flow.observe_emotion(
            str(payload.get("emotion") or ""),
            confidence=payload.get("confidence", 1.0),
        )

    def _growth_guidance_plan_for_user_text(
        self,
        user_text: str,
    ) -> GrowthGuidancePlan | None:
        text = (user_text or "").strip()
        if not text:
            return None
        return self.growth_guidance_engine.plan(
            {
                "type": "dialogue_event",
                "source": "dialogue",
                "priority": 1,
                "payload": {"text": text},
            },
            GrowthContext(
                state="listening",
                child_memory=self.session.memory_manager.load(),
                recent_topics=tuple(self.session.memory_manager.load().get("recent_topics", [])),
                child_is_speaking=False,
            ),
        )

    def _prepared_reply_for_user_text(self, user_text: str) -> str:
        assert self.session.prompt_builder is not None
        knowledge_base = getattr(self.session.prompt_builder, "knowledge_base", None)
        if knowledge_base is None:
            return ""
        prepared = knowledge_base.prepared_reply(user_text)
        # Weather is now supplied by the real-time agent so the parent-selected
        # city is honoured. Keep the deterministic local fast paths for other
        # reviewed knowledge, such as festivals.
        if prepared is not None and prepared.source == "weather":
            return ""
        return prepared.text if prepared is not None else ""

    def _build_turn_system_prompt(
        self,
        user_text: str,
        *,
        growth_plan: GrowthGuidancePlan | None = None,
    ) -> str:
        assert self.session.prompt_builder is not None
        base_prompt = self.session.prompt_builder.build_system_prompt(user_text)
        scenario_prompt = _scenario_prompt_for_user_text(user_text)
        additions = []
        additions.append(scene_catalog_prompt())
        if scenario_prompt:
            additions.append(f"当前对话场景：\n{scenario_prompt}")
        guidance_prompt = _growth_guidance_prompt(growth_plan)
        if guidance_prompt:
            additions.append(guidance_prompt)
        return base_prompt + "\n\n" + "\n\n".join(additions)

    def _llm_dinosaur_script_fallback(self, user_text: str) -> str:
        """Convert one validated LLM command into canonical reviewed input.

        The model is never allowed to choose a reply, a UI command, or an arm
        command here.  A valid command only asks the existing deterministic
        dinosaur flow to process a canonical self-introduction.
        """
        if not DINOSAUR_SCRIPT_ENABLED or not _looks_like_dinosaur_script_trigger_candidate(user_text):
            return ""
        try:
            response = self.llm_client.generate_reply(
                user_text,
                self._build_turn_system_prompt(user_text),
                history=self.session.as_chat_history(),
            )
        except Exception:
            response = ""
        canonical = _canonical_dinosaur_intro_from_llm_json(response)
        if canonical:
            return canonical
        # Never pass a malformed command response to streaming TTS.  ASR
        # often retains the nickname but loses “我叫”; recover only the
        # canonical local input and let the reviewed flow own the reply.
        return _canonical_dinosaur_intro_from_candidate(user_text)

    def _generate_and_speak_realtime_tts(
        self,
        user_text: str,
        system_prompt: str,
        *,
        history: list[dict[str, str]],
        tts_client: DashScopeTTSClient | None,
        local_tts_fallback: bool,
        output_device: int | None,
        pipeline: VoiceInteractionPipeline,
        interrupt_event: threading.Event | None = None,
        prewarmed_tts: _RealtimeTTSHandle | None = None,
        lead_in_text: str = "",
        reply_prefix: str = "",
    ) -> str:
        tts_handle = prewarmed_tts or _RealtimeTTSHandle(
            settings=self.settings,
            voice_profile=self.voice_profile,
            output_device=output_device,
            pipeline=pipeline,
            interrupt_event=interrupt_event,
        )
        tts_handle.set_interrupt_event(interrupt_event)
        if prewarmed_tts is None:
            tts_handle.start_background(phase="prewarm")

        speech_lead_in = sanitize_tts_text(lead_in_text)
        speech_prefix = sanitize_tts_text(reply_prefix)
        reply_parts: list[str] = []
        if speech_prefix:
            reply_parts.append(speech_prefix)
        elif speech_lead_in:
            reply_parts.append(speech_lead_in)
        chunk_index = 0
        speech_pending = ""
        use_sentence_fallback = False
        # A tool acknowledgement may play while a camera/weather/search call
        # waits tens of seconds for its result.  Do not leave the answer's
        # websocket idle during that wait: DashScope can close it, and a later
        # enqueue would otherwise end the entire voice session.
        answer_stream_reset_required = False
        llm_started_at = time.perf_counter()
        delta_index = 0
        first_tts_chunk_elapsed_ms: float | None = None
        defer_camera_snapshot_clear = False

        def ensure_answer_stream_ready() -> bool:
            nonlocal tts_handle, answer_stream_reset_required
            if answer_stream_reset_required:
                tts_handle = _RealtimeTTSHandle(
                    settings=self.settings,
                    voice_profile=self.voice_profile,
                    output_device=output_device,
                    pipeline=pipeline,
                    interrupt_event=interrupt_event,
                )
                tts_handle.start_background(
                    phase="answer_after_realtime_query",
                    fast_path="realtime_query_answer",
                )
                answer_stream_reset_required = False
            return tts_handle.wait_ready()

        if speech_lead_in:
            chunk_index = 1
            self._emit_tts_segment_queued(
                pipeline,
                speech_lead_in,
                chunk_index,
                streaming=True,
                first_queue_elapsed_ms=0.0,
                fast_path="lead_in",
            )
            if not tts_handle.wait_ready():
                use_sentence_fallback = True
            else:
                try:
                    tts_handle.enqueue(speech_lead_in)
                except Exception as exc:
                    tts_handle.close_quietly()
                    can_fallback = not tts_handle.audio_started
                    pipeline.emit(
                        "tts_stream_failed",
                        message=str(exc),
                        fallback=can_fallback,
                        audio_started=tts_handle.audio_started,
                    )
                    if not can_fallback:
                        raise
                    use_sentence_fallback = True
        def on_agent_event(event: dict[str, Any]) -> None:
            nonlocal tts_handle, defer_camera_snapshot_clear, answer_stream_reset_required
            if self._forward_camera_snapshot_agent_event(pipeline, event):
                if event.get("type") == "camera_snapshot_ready":
                    defer_camera_snapshot_clear = True
                return
            if event.get("type") != "realtime_query_started":
                return
            self._cancel_board_processing_notification(pipeline)
            pipeline.emit("realtime_query_started", **event)
            voice_prompt = sanitize_tts_text(str(event.get("voice_prompt") or ""))
            if not voice_prompt or (interrupt_event is not None and interrupt_event.is_set()):
                return
            # This is enqueued before the final LLM request starts streaming,
            # so the child hears the acknowledgement while the lookup runs.
            self._emit_tts_segment_queued(
                pipeline,
                voice_prompt,
                chunk_index,
                streaming=True,
                fast_path="realtime_query_prompt",
                clear_camera_snapshot=False,
            )
            # Always use a short, dedicated stream for a tool prompt.  The
            # answer stream is created only when the model begins responding,
            # so it cannot expire while the tool call is in progress.
            tts_handle.close_quietly()
            self._speak_realtime_query_prompt(
                voice_prompt,
                rate=_voice_prompt_rate(event.get("voice_prompt_rate")),
                output_device=output_device,
                pipeline=pipeline,
                interrupt_event=interrupt_event,
            )
            answer_stream_reset_required = True

        for delta in self._stream_llm_reply(
            user_text,
            system_prompt,
            history=history,
            on_agent_event=on_agent_event,
        ):
            if interrupt_event is not None and interrupt_event.is_set():
                break
            delta_index += 1
            delta_elapsed_ms = round((time.perf_counter() - llm_started_at) * 1000, 1)
            pipeline.emit(
                "llm_delta",
                text=delta,
                index=delta_index,
                elapsed_ms=delta_elapsed_ms,
                first_delta_elapsed_ms=delta_elapsed_ms if delta_index == 1 else None,
            )
            reply_parts.append(delta)
            speech_pending += sanitize_tts_stream_delta(delta)
            chunks, speech_pending = split_realtime_tts_chunks(speech_pending)
            for chunk in chunks:
                chunk_index += 1
                if first_tts_chunk_elapsed_ms is None:
                    first_tts_chunk_elapsed_ms = round(
                        (time.perf_counter() - llm_started_at) * 1000,
                        1,
                    )
                self._emit_tts_segment_queued(
                    pipeline,
                    chunk,
                    chunk_index,
                    streaming=True,
                    clear_camera_snapshot=not defer_camera_snapshot_clear,
                    first_queue_elapsed_ms=first_tts_chunk_elapsed_ms
                    if chunk_index == 1
                    else None,
                )
                if use_sentence_fallback:
                    continue
                if not ensure_answer_stream_ready():
                    use_sentence_fallback = True
                    continue
                try:
                    tts_handle.enqueue(chunk)
                except Exception as exc:
                    tts_handle.close_quietly()
                    can_fallback = not tts_handle.audio_started
                    pipeline.emit(
                        "tts_stream_failed",
                        message=str(exc),
                        fallback=can_fallback,
                        audio_started=tts_handle.audio_started,
                    )
                    if not can_fallback:
                        raise
                    use_sentence_fallback = True

        final_chunk = speech_pending.strip()
        if final_chunk and not (interrupt_event is not None and interrupt_event.is_set()):
            chunk_index += 1
            if first_tts_chunk_elapsed_ms is None:
                first_tts_chunk_elapsed_ms = round(
                    (time.perf_counter() - llm_started_at) * 1000,
                    1,
                )
            self._emit_tts_segment_queued(
                pipeline,
                final_chunk,
                chunk_index,
                streaming=True,
                clear_camera_snapshot=not defer_camera_snapshot_clear,
                first_queue_elapsed_ms=first_tts_chunk_elapsed_ms
                if chunk_index == 1
                else None,
            )
            if not use_sentence_fallback:
                if not ensure_answer_stream_ready():
                    use_sentence_fallback = True
                else:
                    try:
                        tts_handle.enqueue(final_chunk)
                    except Exception as exc:
                        tts_handle.close_quietly()
                        can_fallback = not tts_handle.audio_started
                        pipeline.emit(
                            "tts_stream_failed",
                            message=str(exc),
                            fallback=can_fallback,
                            audio_started=tts_handle.audio_started,
                        )
                        if not can_fallback:
                            raise
                        use_sentence_fallback = True

        pipeline.emit(
            "llm_stream_finished",
            elapsed_ms=round((time.perf_counter() - llm_started_at) * 1000, 1),
            delta_count=delta_index,
            text_length=len("".join(reply_parts)),
        )
        if use_sentence_fallback:
            tts_handle.close_quietly()
            reply = "".join(reply_parts).strip()
            self._speak_existing_text_streaming(
                reply,
                tts_client=tts_client,
                local_tts_fallback=local_tts_fallback,
                output_device=output_device,
                pipeline=pipeline,
                interrupt_event=interrupt_event,
                clear_camera_snapshot=not defer_camera_snapshot_clear,
            )
            if defer_camera_snapshot_clear:
                self._clear_camera_snapshot_preview(pipeline)
            return reply
        try:
            if not tts_handle.wait_ready():
                raise RuntimeError("Realtime TTS prewarm failed.") from tts_handle.error
            tts_handle.close()
        except Exception as exc:
            # A timed-out prewarm thread must not later start speaking over
            # the batch-TTS fallback.  Closing is best-effort because this
            # path is specifically handling a broken network/audio stream.
            tts_handle.close_quietly()
            can_fallback = not tts_handle.audio_started
            pipeline.emit(
                "tts_stream_failed",
                message=str(exc),
                fallback=can_fallback,
                audio_started=tts_handle.audio_started,
            )
            if not can_fallback:
                raise
            reply = "".join(reply_parts).strip()
            self._speak_existing_text_streaming(
                reply,
                tts_client=tts_client,
                local_tts_fallback=local_tts_fallback,
                output_device=output_device,
                pipeline=pipeline,
                interrupt_event=interrupt_event,
                clear_camera_snapshot=not defer_camera_snapshot_clear,
            )
            if defer_camera_snapshot_clear:
                self._clear_camera_snapshot_preview(pipeline)
            return reply
        if defer_camera_snapshot_clear:
            self._clear_camera_snapshot_preview(pipeline)
        return "".join(reply_parts).strip()

    def _speak_realtime_query_prompt(
        self,
        text: str,
        *,
        rate: float,
        output_device: int | None,
        pipeline: VoiceInteractionPipeline,
        interrupt_event: threading.Event | None,
    ) -> None:
        """Play a tool acknowledgement at a rate without changing the reply voice."""
        prompt_profile = replace(self.voice_profile, rate=rate)
        prompt_handle = _RealtimeTTSHandle(
            settings=self.settings,
            voice_profile=prompt_profile,
            output_device=output_device,
            pipeline=pipeline,
            interrupt_event=interrupt_event,
        )
        try:
            if not prompt_handle.ensure_started(
                phase="realtime_query_prompt",
                fast_path="realtime_query_prompt",
            ):
                return
            prompt_handle.enqueue(text)
            prompt_handle.close()
        except Exception as exc:
            prompt_handle.close_quietly()
            pipeline.emit(
                "tts_query_prompt_failed",
                message=str(exc),
                rate=rate,
            )

    def _speak_fixed_realtime_tts(
        self,
        text: str,
        *,
        tts_client: DashScopeTTSClient | None,
        local_tts_fallback: bool,
        output_device: int | None,
        pipeline: VoiceInteractionPipeline,
        interrupt_event: threading.Event | None = None,
        prewarmed_tts: _RealtimeTTSHandle | None = None,
        emit_queue_event: bool = True,
        close_after_enqueue: bool = True,
    ) -> None:
        speech_text = sanitize_tts_text(text)
        if emit_queue_event:
            self._emit_tts_segment_queued(
                pipeline,
                speech_text,
                1,
                first_queue_elapsed_ms=0.0,
                fast_path="fixed_reply",
            )
        tts_handle = prewarmed_tts or _RealtimeTTSHandle(
            settings=self.settings,
            voice_profile=self.voice_profile,
            output_device=output_device,
            pipeline=pipeline,
            interrupt_event=interrupt_event,
        )
        tts_handle.set_interrupt_event(interrupt_event)
        try:
            if prewarmed_tts is None:
                ready = tts_handle.ensure_started(
                    phase="fixed_reply",
                    fast_path="fixed_reply",
                )
            else:
                ready = tts_handle.wait_ready()
            if not ready:
                raise RuntimeError("Realtime TTS prewarm failed.") from tts_handle.error
            tts_handle.enqueue(speech_text)
            if close_after_enqueue:
                tts_handle.close()
        except Exception as exc:
            tts_handle.close_quietly()
            can_fallback = not tts_handle.audio_started
            pipeline.emit(
                "tts_stream_failed",
                message=str(exc),
                fallback=can_fallback,
                audio_started=tts_handle.audio_started,
                phase="fixed_reply",
            )
            if not can_fallback:
                raise
            speak(
                speech_text,
                tts_client=tts_client,
                no_tts=False,
                local_fallback=local_tts_fallback,
                output_device=output_device,
                interrupt_event=interrupt_event,
            )
            _emit_playback_done(pipeline, speech_text, 1, skipped=False)
            return

    def _speak_existing_text_streaming(
        self,
        text: str,
        *,
        tts_client: DashScopeTTSClient | None,
        local_tts_fallback: bool,
        output_device: int | None,
        pipeline: VoiceInteractionPipeline,
        interrupt_event: threading.Event | None = None,
        clear_camera_snapshot: bool = True,
    ) -> None:
        player = StreamingSpeechPlayer(
            tts_client=tts_client,
            no_tts=False,
            local_fallback=local_tts_fallback,
            output_device=output_device,
            on_segment_start=lambda segment, index: pipeline.emit(
                "playback_started",
                text=segment,
                index=index,
            ),
            on_segment_done=lambda segment, index: pipeline.emit(
                "playback_finished",
                text=segment,
                index=index,
            ),
            on_synthesis_start=lambda segment, index: pipeline.emit(
                "tts_synthesis_started",
                text=segment,
                index=index,
            ),
            on_synthesis_done=lambda segment, index, wav_path, elapsed_seconds: pipeline.emit(
                "tts_synthesis_skipped" if wav_path is None else "tts_synthesis_finished",
                text=segment,
                index=index,
                audio_path=str(wav_path) if wav_path is not None else "",
                elapsed_ms=round(elapsed_seconds * 1000, 1),
            ),
            interrupt_event=interrupt_event,
        )
        pending = sanitize_tts_text(text)
        segment_index = 0
        try:
            segments, pending = split_streaming_segments(pending)
            for segment in segments:
                speech_segment = sanitize_tts_text(segment)
                if not speech_segment:
                    continue
                segment_index += 1
                self._emit_tts_segment_queued(
                    pipeline,
                    speech_segment,
                    segment_index,
                    fallback=True,
                    clear_camera_snapshot=clear_camera_snapshot,
                )
                player.enqueue(speech_segment)
            speech_pending = sanitize_tts_text(pending)
            if speech_pending:
                segment_index += 1
                self._emit_tts_segment_queued(
                    pipeline,
                    speech_pending,
                    segment_index,
                    fallback=True,
                    clear_camera_snapshot=clear_camera_snapshot,
                )
                player.enqueue(speech_pending)
        except Exception as exc:
            # The visible/textual reply is still valid if ALSA or the
            # fallback TTS transport is temporarily unavailable.  Do not
            # convert an audio-device contention into a conversation-ending
            # Python exception.
            pipeline.emit(
                "tts_stream_failed",
                message=str(exc),
                fallback=True,
                audio_started=False,
                phase="sentence_fallback",
            )
        finally:
            try:
                player.close()
            except Exception as exc:
                pipeline.emit(
                    "tts_stream_failed",
                    message=str(exc),
                    fallback=True,
                    audio_started=False,
                    phase="sentence_fallback_close",
                )

    def _generate_and_speak_streaming(
        self,
        user_text: str,
        system_prompt: str,
        *,
        history: list[dict[str, str]],
        tts_client: DashScopeTTSClient | None,
        no_tts: bool,
        local_tts_fallback: bool,
        output_device: int | None,
        pipeline: VoiceInteractionPipeline,
        interrupt_event: threading.Event | None = None,
    ) -> str:
        player = StreamingSpeechPlayer(
            tts_client=tts_client,
            no_tts=no_tts,
            local_fallback=local_tts_fallback,
            output_device=output_device,
            on_segment_start=lambda segment, index: None
            if no_tts
            else pipeline.emit("playback_started", text=segment, index=index),
            on_segment_done=lambda segment, index: pipeline.emit(
                "playback_skipped" if no_tts else "playback_finished",
                text=segment,
                index=index,
            ),
            on_synthesis_start=lambda segment, index: pipeline.emit(
                "tts_synthesis_started",
                text=segment,
                index=index,
            ),
            on_synthesis_done=lambda segment, index, wav_path, elapsed_seconds: pipeline.emit(
                "tts_synthesis_skipped" if wav_path is None else "tts_synthesis_finished",
                text=segment,
                index=index,
                audio_path=str(wav_path) if wav_path is not None else "",
                elapsed_ms=round(elapsed_seconds * 1000, 1),
            ),
            interrupt_event=interrupt_event,
        )
        reply_parts: list[str] = []
        pending = ""
        segment_index = 0
        llm_started_at = time.perf_counter()
        delta_index = 0
        first_tts_segment_elapsed_ms: float | None = None
        defer_camera_snapshot_clear = False
        try:
            def on_agent_event(event: dict[str, Any]) -> None:
                nonlocal defer_camera_snapshot_clear
                if self._forward_camera_snapshot_agent_event(pipeline, event):
                    if event.get("type") == "camera_snapshot_ready":
                        defer_camera_snapshot_clear = True
                    return
                if event.get("type") != "realtime_query_started":
                    return
                self._cancel_board_processing_notification(pipeline)
                pipeline.emit("realtime_query_started", **event)
                voice_prompt = sanitize_tts_text(str(event.get("voice_prompt") or ""))
                if not voice_prompt or (
                    interrupt_event is not None and interrupt_event.is_set()
                ):
                    return
                self._emit_tts_segment_queued(
                    pipeline,
                    voice_prompt,
                    segment_index,
                    streaming=True,
                    fast_path="realtime_query_prompt",
                    clear_camera_snapshot=False,
                )
                player.enqueue(voice_prompt)

            for delta in self._stream_llm_reply(
                user_text,
                system_prompt,
                history=history,
                on_agent_event=on_agent_event,
            ):
                if interrupt_event is not None and interrupt_event.is_set():
                    break
                delta_index += 1
                delta_elapsed_ms = round((time.perf_counter() - llm_started_at) * 1000, 1)
                pipeline.emit(
                    "llm_delta",
                    text=delta,
                    index=delta_index,
                    elapsed_ms=delta_elapsed_ms,
                    first_delta_elapsed_ms=delta_elapsed_ms if delta_index == 1 else None,
                )
                reply_parts.append(delta)
                pending += delta
                segments, pending = split_streaming_segments(pending)
                for segment in segments:
                    speech_segment = sanitize_tts_text(segment)
                    if not speech_segment:
                        continue
                    segment_index += 1
                    if first_tts_segment_elapsed_ms is None:
                        first_tts_segment_elapsed_ms = round(
                            (time.perf_counter() - llm_started_at) * 1000,
                            1,
                        )
                    self._emit_tts_segment_queued(
                        pipeline,
                        speech_segment,
                        segment_index,
                        clear_camera_snapshot=not defer_camera_snapshot_clear,
                        first_queue_elapsed_ms=first_tts_segment_elapsed_ms
                        if segment_index == 1
                        else None,
                    )
                    player.enqueue(speech_segment)
            speech_pending = sanitize_tts_text(pending)
            if speech_pending and not (
                interrupt_event is not None and interrupt_event.is_set()
            ):
                segment_index += 1
                if first_tts_segment_elapsed_ms is None:
                    first_tts_segment_elapsed_ms = round(
                        (time.perf_counter() - llm_started_at) * 1000,
                        1,
                    )
                self._emit_tts_segment_queued(
                    pipeline,
                    speech_pending,
                    segment_index,
                    clear_camera_snapshot=not defer_camera_snapshot_clear,
                    first_queue_elapsed_ms=first_tts_segment_elapsed_ms
                    if segment_index == 1
                    else None,
                )
                player.enqueue(speech_pending)
            pipeline.emit(
                "llm_stream_finished",
                elapsed_ms=round((time.perf_counter() - llm_started_at) * 1000, 1),
                delta_count=delta_index,
                text_length=len("".join(reply_parts)),
            )
        finally:
            try:
                player.close()
            finally:
                if defer_camera_snapshot_clear:
                    self._clear_camera_snapshot_preview(pipeline)
        return "".join(reply_parts).strip()

    def _stream_llm_reply(
        self,
        user_text: str,
        system_prompt: str,
        *,
        history: list[dict[str, str]],
        on_agent_event: Callable[[dict[str, Any]], None],
    ):
        """Stream an LLM reply while temporarily subscribing to tool feedback.

        The attribute-based subscription preserves the existing public
        ``stream_reply`` signature, including lightweight test clients.
        """
        client = self.llm_client
        marker_filter = SceneMarkerStreamFilter()
        scene_dispatched = False
        missing = object()
        previous = getattr(client, "on_agent_event", missing)
        setattr(client, "on_agent_event", on_agent_event)
        try:
            for delta in client.stream_reply(user_text, system_prompt, history=history):
                visible = marker_filter.feed(delta)
                if marker_filter.scene_decided and not scene_dispatched:
                    marker = "[[XINGBAO_SCENE:{}]]".format(marker_filter.scene_id) if marker_filter.scene_id else ""
                    _, self._stream_scene_id = self._scene_turn_selector.select(user_text, marker)
                    if self._stream_scene_callback is not None:
                        self._stream_scene_callback(self._stream_scene_id)
                    scene_dispatched = True
                if visible:
                    yield visible
            final_tail, raw_scene_id = marker_filter.finish()
            if not scene_dispatched:
                marker = "[[XINGBAO_SCENE:{}]]".format(raw_scene_id) if raw_scene_id else ""
                _, self._stream_scene_id = self._scene_turn_selector.select(user_text, marker)
                if self._stream_scene_callback is not None:
                    self._stream_scene_callback(self._stream_scene_id)
            if final_tail:
                yield final_tail
        finally:
            if previous is missing:
                try:
                    delattr(client, "on_agent_event")
                except AttributeError:
                    pass
            else:
                setattr(client, "on_agent_event", previous)

    def _emit_tts_segment_queued(
        self,
        pipeline: VoiceInteractionPipeline,
        text: str,
        index: int,
        *,
        clear_camera_snapshot: bool = True,
        **data: Any,
    ) -> None:
        if clear_camera_snapshot and sanitize_tts_text(text):
            self._clear_camera_snapshot_preview(pipeline)
        pipeline.emit(
            "tts_segment_queued",
            text=text,
            index=index,
            voice_profile_id=self.voice_profile.id,
            voice_profile_label=self.voice_profile.label,
            model=self.voice_profile.model,
            voice=self.voice_profile.voice,
            **data,
        )

    def _forward_camera_snapshot_agent_event(
        self,
        pipeline: VoiceInteractionPipeline,
        event: dict[str, Any],
    ) -> bool:
        """Convert private LLM camera events into typed voice events."""
        event_type = str(event.get("type") or "")
        if event_type == "camera_snapshot_ready":
            self._clear_camera_snapshot_preview(pipeline)
            self._camera_snapshot_preview_active = True
            pipeline.emit(
                "camera_snapshot_ready",
                data_uri=str(event.get("data_uri") or ""),
                width=int(event.get("width") or 0),
                height=int(event.get("height") or 0),
                # A local camera preview is intentionally mirrored for the
                # child, whereas an image fetched from the web must retain
                # its original left/right orientation.  Preserve the source
                # flag instead of letting the UI bridge default every image
                # to mirrored.
                mirror=bool(event.get("mirror", True)),
            )
            return True
        if event_type == "camera_snapshot_clear":
            self._clear_camera_snapshot_preview(pipeline, force=True)
            return True
        return False

    def _clear_camera_snapshot_preview(
        self,
        pipeline: VoiceInteractionPipeline,
        *,
        force: bool = False,
    ) -> None:
        if not force and not self._camera_snapshot_preview_active:
            return
        self._camera_snapshot_preview_active = False
        pipeline.emit("camera_snapshot_clear")

    def _is_activity_exit_text(self, text: str) -> bool:
        normalized = (text or "").strip()
        compact = "".join(ch for ch in normalized if not ch.isspace())
        if "不玩了" in compact:
            return True
        activity_words = ("游戏", "小游戏", "活动", "主界面", "桌面", "回家")
        exit_words = ("退出", "结束", "停止", "回到", "返回")
        return any(word in compact for word in activity_words) and any(
            word in compact for word in exit_words
        )

    def _build_wake_word_detector(
        self,
        *,
        input_device: int | None = None,
        show_input_level: bool = False,
        wake_level_interval_seconds: float = 1.0,
        wake_word_threshold: float | None = None,
    ) -> Any:
        if os.environ.get("XINGBAO_WAKE_BACKEND", "kws").strip().lower() == "asr":
            return ASRWakeWordDetector(
                self.settings,
                input_device=input_device,
            )
        return OpenWakeWordDetector(
            WakeWordConfig.from_settings(
                self.settings,
                input_device=input_device,
                threshold=wake_word_threshold,
            ),
            show_input_level=show_input_level,
            level_report_interval_seconds=wake_level_interval_seconds,
        )


def split_streaming_segments(text: str) -> tuple[list[str], str]:
    """Split stable sentence chunks from a growing text buffer."""
    segments: list[str] = []
    buffer = text
    while buffer:
        cut_at = _find_hard_cut(buffer)
        if cut_at < 0 and len(buffer) >= STREAMING_SOFT_LIMIT_CHARS:
            cut_at = _find_soft_cut(buffer)
        if cut_at < 0:
            break
        segment = buffer[: cut_at + 1].strip()
        buffer = buffer[cut_at + 1 :]
        if segment:
            segments.append(segment)
    return segments, buffer


def split_realtime_tts_chunks(text: str) -> tuple[list[str], str]:
    """Split a live text buffer into phrase-sized chunks for realtime TTS."""
    chunks: list[str] = []
    buffer = text
    while buffer:
        cut_at = _find_realtime_tts_cut(buffer)
        if cut_at < 0:
            break
        chunk = buffer[: cut_at + 1].strip()
        buffer = buffer[cut_at + 1 :]
        if chunk:
            chunks.append(chunk)
    return chunks, buffer


def _streaming_asr_backend() -> str:
    """Resolve the streaming recognizer without coupling it to API credentials.

    `cloud` uses the shared DashScope API key with Qwen-Audio ASR; `local`
    keeps the bundled Sherpa-ONNX streaming implementation available offline.
    """
    backend = os.getenv("XINGBAO_ASR_BACKEND", "cloud").strip().lower()
    aliases = {"dashscope": "cloud", "qwen": "cloud", "sherpa": "local"}
    backend = aliases.get(backend, backend)
    if backend not in {"cloud", "local"}:
        raise ValueError(
            "XINGBAO_ASR_BACKEND must be 'cloud' or 'local', "
            f"got {backend!r}."
        )
    return backend


def _is_recoverable_streaming_asr_error(exc: BaseException) -> bool:
    """Return whether DashScope closed a streaming ASR session transiently."""
    return "speech recognition has stopped" in str(exc).casefold()


def normalize_asr_text(text: str) -> str:
    """Normalize common ASR mistakes around Xingbao and the dinosaur 腕龙."""
    normalized = (text or "").strip()
    for variant in ASR_COMPANION_NAME_VARIANTS:
        normalized = normalized.replace(variant, "星宝")
    for variant in ASR_BRACHIOSAURUS_VARIANTS:
        normalized = normalized.replace(variant, "腕龙")
    normalized = re.sub(r"\bwan[\s_-]*long\b\s*", "腕龙", normalized, flags=re.IGNORECASE)
    return normalized


def _reply_commits_to_conversation_end(text: str) -> bool:
    """Return true only when the assistant explicitly says this chat is ending.

    The normal route is the dedicated ``end_conversation`` function call.
    This deliberately narrow check protects a child from a contradictory
    reply such as “好的，星宝先暂停对话” followed by another listening turn.
    It does not react to explanatory questions about how to pause a chat.
    """
    compact = _compact_chinese_text(text)
    if not compact:
        return False
    end_phrases = (
        "星宝先暂停对话",
        "我先暂停对话",
        "我们先暂停对话",
        "现在暂停对话",
        "本次对话先暂停",
        "星宝先结束对话",
        "我先结束对话",
        "我们先结束对话",
        "现在结束对话",
        "本次对话结束",
        "星宝先退出对话",
        "我先退出对话",
        "我们先退出对话",
        "现在退出对话",
    )
    return any(phrase in compact for phrase in end_phrases)


def _has_exact_emotion_keyword(text: str) -> bool:
    """Match only the literal keyword required by the fixed demo route."""
    return "情绪" in str(text or "")


def sanitize_tts_text(text: str) -> str:
    """Remove visual-only characters and normalize whitespace before TTS."""
    cleaned = (text or "").translate(str.maketrans("", "", TTS_DROP_CHARS))
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip()
    return cleaned if _has_spoken_content(cleaned) else ""


def sanitize_tts_stream_delta(text: str) -> str:
    """Clean one streaming text delta without waiting for a full sentence."""
    cleaned = (text or "").translate(str.maketrans("", "", TTS_DROP_CHARS))
    return " ".join(cleaned.split())


def _has_spoken_content(text: str) -> bool:
    stripped = (text or "").strip(" ,.!?;:，。！？；：、~～…\"'“”‘’()（）[]【】<>《》-—_")
    return bool(stripped)


def _voice_vad_config(
    *,
    low_latency_voice: bool,
    listen_timeout_seconds: float = 0.0,
    manual_threshold: float = 0.0,
    end_silence_ms: int = 0,
    debug_level_interval_ms: float = 0.0,
) -> VADConfig:
    if not low_latency_voice:
        return VADConfig(
            listen_timeout_seconds=listen_timeout_seconds,
            manual_threshold=manual_threshold,
            end_silence_ms=end_silence_ms if end_silence_ms > 0 else VADConfig.end_silence_ms,
            debug_level_interval_ms=debug_level_interval_ms,
        )
    return VADConfig(
        calibrate_seconds=0.18,
        # Children often pause while looking for their next word.  A prior
        # 420 ms deadline treated those natural mid-sentence pauses as an end
        # of turn, which could advance the guided finals script too early.
        # Keep fast turn-taking while leaving enough room for a natural
        # mid-sentence pause. The board launcher can calibrate this per venue.
        end_silence_ms=end_silence_ms if end_silence_ms > 0 else 1000,
        min_utterance_ms=650,
        start_hold_ms=60,
        pre_roll_ms=240,
        listen_timeout_seconds=listen_timeout_seconds,
        manual_threshold=manual_threshold,
        debug_level_interval_ms=debug_level_interval_ms,
    )


def _barge_in_vad_config(
    base_config: VADConfig | None,
    *,
    debug_level_interval_ms: float = 0.0,
) -> VADConfig:
    base = base_config or VADConfig()
    return VADConfig(
        frame_ms=base.frame_ms,
        calibrate_seconds=min(base.calibrate_seconds, 0.2),
        pre_roll_ms=0,
        start_hold_ms=min(base.start_hold_ms, 90),
        end_silence_ms=base.end_silence_ms,
        min_utterance_ms=min(base.min_utterance_ms, 180),
        max_utterance_seconds=base.max_utterance_seconds,
        threshold_multiplier=base.threshold_multiplier,
        min_rms=base.min_rms,
        end_threshold_ratio=base.end_threshold_ratio,
        manual_threshold=base.manual_threshold,
        listen_timeout_seconds=0.0,
        debug_level_interval_ms=debug_level_interval_ms,
    )


def _aec3_barge_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _is_wake_only_text(text: str, wake_word: str = "星宝星宝") -> bool:
    normalized = _compact_chinese_text(text)
    wake = _compact_chinese_text(wake_word)
    companion = _compact_chinese_text("星宝")
    return normalized in {wake, companion}


def _compact_chinese_text(text: str) -> str:
    return "".join(char for char in (text or "").strip() if "\u4e00" <= char <= "\u9fff")


def _emit_playback_done(
    pipeline: VoiceInteractionPipeline,
    text: str,
    index: int,
    *,
    skipped: bool,
) -> None:
    pipeline.emit(
        "playback_skipped" if skipped else "playback_finished",
        text=text,
        index=index,
    )


def _voice_prompt_rate(value: Any) -> float:
    """Normalize an optional tool-prompt rate to DashScope's supported range."""
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(2.0, max(0.5, rate))


def _find_hard_cut(text: str) -> int:
    indexes = [text.find(char) for char in HARD_SENTENCE_BOUNDARIES if char in text]
    return min(indexes) if indexes else -1


def _find_soft_cut(text: str) -> int:
    indexes = [
        text.rfind(char, 0, STREAMING_SOFT_LIMIT_CHARS + 1)
        for char in SOFT_SENTENCE_BOUNDARIES
    ]
    indexes = [index for index in indexes if index >= 0]
    if indexes:
        return max(indexes)
    return STREAMING_SOFT_LIMIT_CHARS - 1


def _find_realtime_tts_cut(text: str) -> int:
    hard_cut = _find_hard_cut(text)
    if hard_cut >= 0:
        return hard_cut

    soft_cut = _find_first_soft_cut(text)
    if (
        soft_cut >= REALTIME_TTS_MIN_CHARS - 1
        and (
            soft_cut == len(text) - 1
            or len(text) >= REALTIME_TTS_SOFT_LIMIT_CHARS
        )
    ):
        return soft_cut

    if len(text) >= REALTIME_TTS_FORCE_LIMIT_CHARS:
        return REALTIME_TTS_SOFT_LIMIT_CHARS - 1
    return -1


def build_expression_demo_events() -> list[dict[str, Any]]:
    """Return the scripted expression events used by the CLI demo."""
    return [
        {
            "type": "touch_event",
            "source": "demo",
            "payload": {"event": "child_touched_xingbao"},
        },
        {
            "type": "memory_write_request",
            "source": "demo",
            "payload": {
                "memory_kind": "interest",
                "content": "三角龙",
            },
        },
        {
            "type": "child_unclear_text",
            "source": "dialogue",
            "payload": {"text": "今天那个……他不让我……"},
        },
        {
            "type": "game_event",
            "source": "mini_game",
            "payload": {"event": "game_started", "game_id": "emotion_planet"},
        },
        {
            "type": "game_event",
            "source": "mini_game",
            "payload": {"event": "child_made_mistake", "game_id": "emotion_planet"},
        },
        {
            "type": "vision_event",
            "source": "demo",
            "payload": {
                "event": "drink_water_reminder_due",
                "simulated": True,
            },
        },
        {
            "type": "growth_record_request",
            "source": "dialogue",
            "payload": {
                "session_id": "demo_session_001",
                "summary_hint": "今天你能把“我有点难过”说出来，还愿意再试一次。",
            },
        },
    ]


def _screen_expression_for(expression: str) -> str:
    mapping = {
        "smile": "smile",
        "happy": "smile",
        "encouraging": "smile",
        "caring": "smile",
        "comforting": "smile",
        "listening": "curious",
        "thinking": "thinking",
        "confused": "curious",
        "calm": "neutral",
        "neutral": "neutral",
        "sleepy": "sleepy",
        "sad": "sad",
        "surprised": "surprised",
    }
    return mapping.get((expression or "").strip(), "neutral")


def _led_mode_for(expression: str) -> str:
    mapping = {
        "happy": "warm_breath",
        "smile": "warm_breath",
        "encouraging": "warm_breath",
        "caring": "blue_breath",
        "comforting": "blue_breath",
        "listening": "blue_breath",
        "thinking": "blue_breath",
    }
    return mapping.get((expression or "").strip(), "off")


def _expression_output_from_growth_plan(plan: GrowthGuidancePlan) -> ExpressionOutput:
    return ExpressionOutput(
        intent=plan.scene,
        speak_text=plan.speak_text,
        screen_text=plan.screen_text,
        expression=plan.expression,
        tts=bool(plan.speak_text),
        priority=plan.priority,
        memory_request=plan.memory_request,
        state=plan.next_state,
        interrupt_policy=plan.interrupt_policy,
        source=plan.source,
        handled=plan.handled,
        reason=plan.reason,
    )


def _should_use_growth_guidance_plan(plan: GrowthGuidancePlan) -> bool:
    # Growth guidance now supplies an LLM communication goal only.  No scene
    # may bypass the model with a local fixed utterance.
    return False


def _growth_guidance_prompt(plan: GrowthGuidancePlan | None) -> str:
    if plan is None or not plan.handled:
        return ""
    goals = {
        "expression_scaffold": "耐心帮助孩子把没说清楚的意思说完整，可以提出一个简单澄清问题。",
        "emotion_naming": "先接住孩子的感受，再帮助孩子辨认情绪；不要机械复述固定句子。",
        "opinion_encouragement": "尊重孩子的观点，用自然追问鼓励他说出原因。",
        "safety_support": "用自然、简短、明确的话提供安全支持；鼓励立刻向身边可信赖的大人求助，不要机械复述固定句子。",
        "privacy_boundary": "不要复述或索取隐私信息；自然地说明不需要这类信息，并引导到安全的话题，不要机械复述固定句子。",
    }
    goal = goals.get(plan.scene)
    if not goal:
        return ""
    return (
        "成长引导要求：规则层只提供沟通目标，不提供最终台词。"
        f"本轮目标是：{goal}"
        "请结合上下文自行组织自然表达，避免重复此前用过的句式。"
    )


def _scenario_prompt_for_user_text(user_text: str) -> str:
    text = (user_text or "").strip()
    if not text:
        return ""
    additions: list[str] = []
    if _looks_like_story_request(text):
        topic = _story_topic_from_text(text)
        topic_line = f"孩子正在请求关于“{topic}”的故事。" if topic else "孩子正在请求一个故事。"
        additions.append(
            f"{topic_line}\n"
            "这不是普通短问答，可以突破默认 80 字限制，控制在 140 到 220 个中文字符左右。\n"
            "回复长度上限：220个中文字符。\n"
            "请直接开始讲，不要只说“我来讲故事”。用 4 到 6 个短句，句子之间用清楚标点断开，方便流式 TTS 尽快播放。\n"
            "故事要有趣、温暖，并自然包含 1 个真实科普点；最后用 1 个小问题引导孩子继续了解。\n"
            "如果主题是恐龙，可以选择三角龙、霸王龙、梁龙、翼龙等儿童容易理解的例子，但不要加入恐怖、追咬或危险细节。"
        )
    if _looks_like_dinosaur_script_trigger_candidate(text):
        additions.append(
            "恐龙表达剧本触发协议：当且仅当孩子是在自我介绍，并明确表达喜欢恐龙时，"
            "包括“我叫小雨/小羽/小宇，我喜欢恐龙”及同音字、少量 ASR 漏字或语序变化，"
            "必须只返回一行合法 JSON，不要解释、不要 Markdown、不要附带给孩子的话。\n"
            "JSON 固定格式："
            '{"type":"xingbao","action":"dinosaur_script","name":"识别到的称呼"}\n'
            "name 只填写 1 到 8 个中文字符的称呼；无法可靠识别称呼时不要返回 JSON，"
            "按普通对话回答。任何不满足上述条件的内容都不得返回该 JSON。"
        )
    return "\n\n".join(additions)


def _looks_like_dinosaur_script_trigger_candidate(text: str) -> bool:
    """Keep the LLM JSON fallback limited to a self-introduction intent."""
    compact = _compact_chinese_text(text)
    if "恐龙" not in compact or not any(
        marker in compact for marker in ("喜欢", "最爱", "感兴趣")
    ):
        return False
    return any(
        marker in compact
        for marker in ("我叫", "我是", "叫我", "名字", "小雨", "小羽", "小宇")
    )


def _canonical_dinosaur_intro_from_llm_json(response: str) -> str:
    """Validate the one LLM JSON command accepted by the voice runtime."""
    raw = str(response or "").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    if (
        payload.get("type") != DINOSAUR_SCRIPT_JSON_TYPE
        or payload.get("action") != DINOSAUR_SCRIPT_JSON_ACTION
    ):
        return ""
    name = str(payload.get("name") or "").strip()
    if re.fullmatch(r"[\u4e00-\u9fff]{1,8}", name) is None:
        return ""
    return f"我叫{name}，我喜欢恐龙"


def _canonical_dinosaur_intro_from_candidate(user_text: str) -> str:
    """Recover safe name aliases when ASR omitted the self-introduction cue."""
    compact = _compact_chinese_text(user_text)
    name = next((alias for alias in ("小雨", "小羽", "小宇") if alias in compact), "")
    if not name:
        match = re.search(
            r"(?:我叫|我是|叫我|名字叫)([\u4e00-\u9fff]{1,8}?)(?=(?:我)?(?:最|特别|很)?喜欢|最爱|感兴趣|恐龙|$)",
            compact,
        )
        if match is not None:
            name = match.group(1)
    if not name:
        # The candidate predicate already requires an introduction marker and
        # dinosaur interest.  Use a non-persistent neutral form rather than
        # let a malformed LLM command reach speech playback.
        name = "小朋友"
    return f"我叫{name}，我喜欢恐龙"


def _fast_lead_in_for_user_text(user_text: str) -> str:
    text = (user_text or "").strip()
    if not text:
        return ""
    compact = _compact_chinese_text(text)
    if _looks_like_story_request(text):
        topic = _story_topic_from_text(text)
        if topic:
            return f"好呀，我先给你准备一个{topic}小故事。"
        return "好呀，我先给你准备一个小故事。"
    if any(word in compact for word in ("你好", "在吗", "你在干什么", "你在做什么")):
        return "我在呢，正等你一起玩。"
    if any(word in compact for word in ("我不会", "不知道", "不会做", "帮帮我")):
        return "没关系，我们一步一步来。"
    return ""


def _looks_like_story_request(text: str) -> bool:
    return any(word in text for word in ("故事", "小故事", "绘本"))


def _story_topic_from_text(text: str) -> str:
    topics = (
        "三角龙",
        "霸王龙",
        "翼龙",
        "梁龙",
        "恐龙",
        "动物",
        "太空",
        "星星",
        "火山",
        "机器人",
    )
    for topic in topics:
        if topic in text:
            return topic
    return ""


def _find_first_soft_cut(text: str) -> int:
    indexes = [text.find(char) for char in SOFT_SENTENCE_BOUNDARIES if char in text]
    return min(indexes) if indexes else -1
