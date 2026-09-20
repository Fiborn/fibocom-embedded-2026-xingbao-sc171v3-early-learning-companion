import pytest

from core.settings import AppSettings, get_dashscope_api_key


def test_app_settings_loads_existing_config() -> None:
    settings = AppSettings.load()

    assert settings.proxy_mode == "none"
    assert settings.manual_proxy == ""
    assert settings.auto_proxy_candidates == ("",)
    assert settings.asr_model == "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
    assert settings.realtime_asr_model == "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
    assert settings.cloud_streaming_asr_model == "qwen-audio-3.0-asr-flash-streaming"
    assert settings.local_asr_model_dir == "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
    assert settings.local_asr_server_port == 6006
    assert settings.llm_model == "qwen-plus"
    assert settings.agent_default_city == "北京"
    assert settings.agent_timezone == "Asia/Shanghai"
    assert settings.tts_model == "cosyvoice-v3-flash"
    assert settings.tts_voice == "longanyang"
    assert settings.wake_word == "星宝星宝"
    assert settings.record_sample_rate == 16000
    assert settings.wake_word_model_path == "model_voice/xingbao.tflite"
    assert settings.wake_word_threshold == 0.5
    assert settings.wake_word_samples_per_read == 800
    assert settings.conversation_followup_timeout_seconds == 8.0
    assert settings.max_conversation_turns == 0
    assert "再见" in settings.conversation_exit_words
    assert "不聊了" in settings.conversation_exit_words


def test_default_exit_words_are_chinese() -> None:
    assert AppSettings().conversation_exit_words == (
        "退出",
        "结束",
        "停止",
        "再见",
        "拜拜",
        "不聊了",
    )


def test_get_dashscope_api_key_reads_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    assert get_dashscope_api_key() == "test-key"


def test_get_dashscope_api_key_requires_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        get_dashscope_api_key()
