"""Voice interaction events and future streaming interface contracts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


VOICE_EVENT_TYPES = frozenset(
    {
        "wake_detected",
        "scripted_followup_listening",
        "wake_wait_recovered",
        "wake_wait_empty",
        "wake_suppressed",
        "wake_ack_started",
        "wake_ack_failed",
        "wake_ui_acknowledged",
        "wake_ui_listening",
        "wake_ui_listening_failed",
        "wake_ui_processing",
        "wake_ui_processing_failed",
        "wake_ui_session_ended",
        "wake_ui_session_end_failed",
        "wake_ui_session_end_suppressed",
        "board_ui_game_command",
        "board_ui_game_command_failed",
        "board_ui_assistant_output",
        "board_ui_assistant_output_failed",
        "xingbao_scene",
        "xingbao_scene_failed",
        "network_warmup_started",
        "network_warmed",
        "network_warmup_failed",
        "audio_ready",
        "quick_ack_started",
        "listening_started",
        "listening_ready",
        "speech_captured",
        "asr_started",
        "asr_partial",
        "asr_final",
        "asr_empty",
        "asr_failed",
        "asr_reconnecting",
        "asr_suppressed",
        "voice_turn_recovered",
        "arm_action_queued",
        "arm_action_skipped",
        "finals_post_high_five_showcase_queued",
        "guided_expression_decision",
        "guided_expression_recovery",
        "conversation_stop_requested",
        "llm_conversation_end_requested",
        "growth_guidance_decision",
        "demo_game_prompt",
        "realtime_query_started",
        "camera_snapshot_ready",
        "camera_snapshot_clear",
        "llm_delta",
        "llm_stream_finished",
        "tts_synthesis_started",
        "tts_synthesis_finished",
        "tts_synthesis_skipped",
        "tts_segment_queued",
        "tts_stream_started",
        "tts_stream_prewarmed",
        "tts_stream_audio_started",
        "tts_stream_finished",
        "tts_stream_failed",
        "tts_query_prompt_failed",
        "tts_interrupted",
        "kws_barge_started",
        "aec3_kws_started",
        "aec3_kws_unavailable",
        "aec3_barge_started",
        "aec3_unavailable",
        "playback_started",
        "playback_finished",
        "playback_skipped",
        "followup_waiting",
        "session_ended",
    }
)


@dataclass(frozen=True)
class VoiceEvent:
    """A timestamped event emitted by the voice interaction pipeline."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.perf_counter)

    def __post_init__(self) -> None:
        if self.type not in VOICE_EVENT_TYPES:
            raise ValueError(f"Unsupported voice event type: {self.type}")


VoiceEventHandler = Callable[[VoiceEvent], Any]


class SpeechRecognizer(Protocol):
    """Contract for batch or streaming speech recognition implementations."""

    def transcribe(self, wav_path: Path | str) -> str:
        """Return final recognized text for one captured utterance."""


class SpeechSynthesizer(Protocol):
    """Contract for batch or streaming speech synthesis implementations."""

    def synthesize(self, text: str, out_wav: Path | str) -> Path:
        """Return a playable WAV path for one text segment."""


class VoiceInteractionPipeline:
    """Small event emitter wrapper used by the current HTTP-backed voice flow."""

    def __init__(self, handler: VoiceEventHandler | None = None) -> None:
        self.handler = handler

    def emit(self, event_type: str, **data: Any) -> VoiceEvent:
        event = VoiceEvent(event_type, data)
        if self.handler is not None:
            self.handler(event)
        return event
