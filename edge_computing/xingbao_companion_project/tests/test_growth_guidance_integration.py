import json
from pathlib import Path
from typing import Any

from app import XingbaoApp
from core.growth_guidance import GrowthGuidanceEngine
from core.knowledge_base import KnowledgeBase
from core.memory import MemoryManager
from core.session import SessionManager
from core.settings import AppSettings
from core.voice_events import VoiceEvent
from intelligence.prompt_builder import PromptBuilder


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _app_with_daily_festival(tmp_path: Path) -> XingbaoApp:
    knowledge_path = tmp_path / "knowledge.json"
    daily_path = tmp_path / "daily.json"
    role_config = tmp_path / "role.json"
    child_profile = tmp_path / "profile.json"
    memory_path = tmp_path / "memory.json"

    _write_json(knowledge_path, {"topics": [], "festivals": []})
    _write_json(
        daily_path,
        {
            "today_special_days": [
                {
                    "name": "端午节",
                    "keywords": ["端午", "粽子"],
                    "facts": ["端午节常见习俗有吃粽子、赛龙舟。"],
                    "child_hook": "可以观察粽叶是什么颜色。",
                }
            ]
        },
    )
    _write_json(
        role_config,
        {
            "default_name": "星宝",
            "identity": "住在陪伴桌里的小星球机器人",
            "age_range": "3-8岁",
            "base_style": "温暖、简短",
            "max_reply_chars": 80,
            "safety_rules": ["不询问隐私"],
        },
    )
    _write_json(child_profile, {})

    knowledge_base = KnowledgeBase(knowledge_path, daily_path)
    prompt_builder = PromptBuilder(
        role_config_path=role_config,
        child_profile_path=child_profile,
        memory_manager=MemoryManager(memory_path),
        knowledge_base=knowledge_base,
    )
    app = XingbaoApp(
        settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0),
        session=SessionManager(
            memory_manager=MemoryManager(memory_path),
            prompt_builder=prompt_builder,
        ),
    )
    app.growth_guidance_engine = GrowthGuidanceEngine(
        knowledge_base=knowledge_base,
        clock=lambda: 1000.0,
    )
    return app


def test_voice_turn_uses_growth_guidance_to_prompt_llm_not_a_fixed_reply(monkeypatch, tmp_path: Path) -> None:
    app = XingbaoApp(settings=AppSettings(proxy_mode="none", wake_word_cooldown_seconds=0))
    wav_path = tmp_path / "input.wav"

    class FakeASR:
        def transcribe(self, path: Path | str) -> str:
            assert path == wav_path
            return "今天那个他不让我然后我就不知道怎么说"

    class FakeLLM:
        def stream_reply(self, *_args: Any, **_kwargs: Any):
            yield "我在听，你愿意再多说一点吗？"

    def fake_capture_utterance_vad(**_kwargs: Any):
        return wav_path, {"utterance_ms": 700.0}

    events: list[VoiceEvent] = []
    monkeypatch.setattr("app.capture_utterance_vad", fake_capture_utterance_vad)
    app.asr_client = FakeASR()  # type: ignore[assignment]
    app.llm_client = FakeLLM()  # type: ignore[assignment]

    result = app.run_voice_once(no_tts=True, on_voice_event=events.append)

    assert result.fast_path != "growth_guidance"
    assert result.assistant_text == "我在听，你愿意再多说一点吗？"
    assert result.action["screen_expression"] == "curious"
    assert any(
        event.type == "growth_guidance_decision"
        and event.data.get("scene") == "expression_scaffold"
        for event in events
    )


def test_expression_event_can_route_through_growth_guidance(tmp_path: Path) -> None:
    app = _app_with_daily_festival(tmp_path)

    output = app.run_expression_event_json(
        json.dumps(
            {
                "type": "proactive_opportunity",
                "source": "dialogue",
                "payload": {"opportunity": "opening"},
            },
            ensure_ascii=False,
        ),
        use_growth_guidance=True,
    )

    assert output["intent"] == "proactive_topic"
    assert "端午节" in output["speak_text"]
    assert output["state"] == "proactive_topic"


def test_expression_event_keeps_legacy_dispatcher_by_default(tmp_path: Path) -> None:
    app = _app_with_daily_festival(tmp_path)

    output = app.run_expression_event_json(
        '{"type":"vision_event","source":"vision","payload":{"event":"face_too_close"}}'
    )

    assert output["intent"] == "eye_distance"
