"""Runtime settings and environment access for Xingbao Companion."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS_PATH = Path("config/settings.json")


@dataclass(frozen=True)
class AppSettings:
    proxy_mode: str = "none"
    manual_proxy: str = ""
    auto_proxy_candidates: tuple[str, ...] = ("",)
    asr_model: str = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
    realtime_asr_model: str = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
    cloud_streaming_asr_model: str = "qwen-audio-3.0-asr-flash-streaming"
    local_asr_model_dir: str = "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
    local_asr_runtime_dir: str = "tools/runtime/sherpa-onnx-v1.13.4-linux-aarch64-shared-cpu"
    local_asr_num_threads: int = 2
    local_asr_server_port: int = 6006
    llm_model: str = "qwen-plus"
    agent_default_city: str = "北京"
    agent_timezone: str = "Asia/Shanghai"
    agent_preferences_path: str = "data/agent_preferences.json"
    tts_model: str = "cosyvoice-v3-flash"
    tts_voice: str = "longanyang"
    active_voice_profile: str = "xingbao_daily"
    voice_profiles_path: str = "config/voice_profiles.json"
    record_sample_rate: int = 16000
    vad_end_silence_ms: int = 500
    max_reply_chars: int = 80
    max_history_turns: int = 20
    wake_word: str = "星宝星宝"
    wake_word_model_path: str = "model_voice/xingbao.tflite"
    wake_word_threshold: float = 0.5
    wake_word_num_threads: int = 2
    wake_word_samples_per_read: int = 800
    wake_word_cooldown_seconds: float = 1.2
    conversation_followup_timeout_seconds: float = 8.0
    # Zero means no per-session turn limit.
    max_conversation_turns: int = 0

    @classmethod
    def load(cls, path: Path | str = DEFAULT_SETTINGS_PATH) -> "AppSettings":
        settings_path = Path(path)
        if not settings_path.exists():
            return cls()

        data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected settings JSON object: {settings_path}")

        return cls(
            proxy_mode=str(data.get("proxy_mode", cls.proxy_mode)),
            manual_proxy=str(data.get("manual_proxy", cls.manual_proxy)),
            auto_proxy_candidates=tuple(
                item
                for item in data.get("auto_proxy_candidates", cls.auto_proxy_candidates)
                if isinstance(item, str)
            ),
            asr_model=str(data.get("asr_model", cls.asr_model)),
            realtime_asr_model=str(
                data.get("realtime_asr_model", cls.realtime_asr_model)
            ),
            cloud_streaming_asr_model=str(
                data.get("cloud_streaming_asr_model", cls.cloud_streaming_asr_model)
            ),
            local_asr_model_dir=str(
                data.get("local_asr_model_dir", cls.local_asr_model_dir)
            ),
            local_asr_runtime_dir=str(
                data.get("local_asr_runtime_dir", cls.local_asr_runtime_dir)
            ),
            local_asr_num_threads=_int_value(
                data.get("local_asr_num_threads"), cls.local_asr_num_threads
            ),
            local_asr_server_port=_int_value(
                data.get("local_asr_server_port"), cls.local_asr_server_port
            ),
            llm_model=str(data.get("llm_model", cls.llm_model)),
            agent_default_city=str(
                data.get("agent_default_city", cls.agent_default_city)
            ),
            agent_timezone=str(data.get("agent_timezone", cls.agent_timezone)),
            agent_preferences_path=str(
                data.get("agent_preferences_path", cls.agent_preferences_path)
            ),
            tts_model=str(data.get("tts_model", cls.tts_model)),
            tts_voice=str(data.get("tts_voice", cls.tts_voice)),
            active_voice_profile=str(
                data.get("active_voice_profile", cls.active_voice_profile)
            ),
            voice_profiles_path=str(
                data.get("voice_profiles_path", cls.voice_profiles_path)
            ),
            record_sample_rate=_int_value(data.get("record_sample_rate"), cls.record_sample_rate),
            vad_end_silence_ms=_int_value(
                data.get("vad_end_silence_ms"),
                cls.vad_end_silence_ms,
            ),
            max_reply_chars=_int_value(data.get("max_reply_chars"), cls.max_reply_chars),
            max_history_turns=_int_value(
                data.get("max_history_turns"),
                cls.max_history_turns,
            ),
            wake_word=str(data.get("wake_word", cls.wake_word)),
            wake_word_model_path=str(
                data.get("wake_word_model_path", cls.wake_word_model_path)
            ),
            wake_word_threshold=_float_value(
                data.get("wake_word_threshold"),
                cls.wake_word_threshold,
            ),
            wake_word_num_threads=_int_value(
                data.get("wake_word_num_threads"),
                cls.wake_word_num_threads,
            ),
            wake_word_samples_per_read=_int_value(
                data.get("wake_word_samples_per_read"),
                cls.wake_word_samples_per_read,
            ),
            wake_word_cooldown_seconds=_float_value(
                data.get("wake_word_cooldown_seconds"),
                cls.wake_word_cooldown_seconds,
            ),
            conversation_followup_timeout_seconds=_float_value(
                data.get("conversation_followup_timeout_seconds"),
                cls.conversation_followup_timeout_seconds,
            ),
            max_conversation_turns=_int_value(
                data.get("max_conversation_turns"),
                cls.max_conversation_turns,
            ),
        )


def get_dashscope_api_key() -> str:
    """Read DashScope credentials from the environment only."""
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set.")
    return key


def get_qweather_api_key() -> str:
    """Read the QWeather credential from the protected runtime environment."""
    key = os.environ.get("QWEATHER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("QWEATHER_API_KEY is not set.")
    return key


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float_value(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
