from pathlib import Path
import copy
import re

import pytest

from core.settings import AppSettings
from core.voice_profiles import VoiceProfile
from intelligence.llm_client import (
    CAMERA_TOOL_INSTRUCTION,
    CAMERA_UNCLEAR_REPLY,
    CAMERA_VL_MODEL,
    CAMERA_VL_SYSTEM_PROMPT,
    DRAWING_BOARD_TOOL,
    DashScopeLLMClient,
    REFERENCE_IMAGE_TOOL,
    _is_contextual_reference_image_follow_up,
    _is_conversation_summary_request,
    _is_explicit_camera_request,
    _looks_like_presented_camera_request,
    _looks_like_reference_image_request,
    _display_safe_text,
    clip_text,
)
import intelligence.llm_client as llm_module
from intelligence.camera_inspection import CameraInspectionError, CameraSnapshot
from intelligence.realtime_tools import RealtimeInfoTools
from multimodal.asr_client import (
    DashScopeASRClient,
    _StreamingRecognitionCallback,
    _recognition_result_text,
    audio_to_data_uri,
)
from multimodal.tts_client import DashScopeTTSClient


class FakeNetworkClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.requests: list[dict] = []
        self.downloads: list[tuple[str, Path]] = []

    def request_json(self, method: str, url: str, **kwargs: object) -> dict:
        self.requests.append(copy.deepcopy({"method": method, "url": url, **kwargs}))
        return self.response

    def download_file(self, url: str, out_path: Path, **_kwargs: object) -> None:
        self.downloads.append((url, out_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"wav")


def test_web_image_requests_win_over_camera_image_keywords() -> None:
    assert _looks_like_reference_image_request("帮我查找万龙的图")
    assert _looks_like_reference_image_request("联网搜索腕龙照片")
    assert not _looks_like_reference_image_request("图里有什么")
    assert _is_contextual_reference_image_follow_up(
        "换一张",
        [
            {"role": "system", "content": "x"},
            {"role": "user", "content": "帮我查找腕龙的图片"},
            {"role": "assistant", "content": "这是一张腕龙图片"},
            {"role": "user", "content": "换一张"},
        ],
    )


def test_presented_image_without_camera_keyword_uses_web_image_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Camera capture requires an explicit camera request."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    request_text = "我找了腕龙图片，你能帮我看一下吗？"
    assert _looks_like_presented_camera_request(request_text)

    network = FakeNetworkClient({"choices": [{"message": {"content": "我来看看。"}}]})
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )

    assert client.generate_reply(request_text, "系统提示") == "我来看看。"
    payload = network.requests[0]["payload"]
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "show_reference_image"},
    }
    assert all(item["function"]["name"] != "inspect_current_camera" for item in payload["tools"])


def test_camera_tool_requires_explicit_camera_word_and_never_summarizes() -> None:
    assert _is_explicit_camera_request("请看一下摄像头现在拍到什么")
    assert not _is_explicit_camera_request("帮我看一下我手里的东西")
    assert not _is_explicit_camera_request("总结一下之前对话")
    assert not _is_explicit_camera_request("总结摄像头前面我们聊了什么")


def test_conversation_summary_never_enters_any_mcp_or_web_search_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    assert _is_conversation_summary_request("帮我总结一下前面的对话内容")
    assert not _is_conversation_summary_request("帮我查一下今天的天气")
    network = FakeNetworkClient({"choices": [{"message": {"content": "我们刚才聊了天气和恐龙。"}}]})
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )

    assert client.generate_reply(
        "帮我总结一下前面的对话内容",
        "系统提示",
        history=[{"role": "user", "content": "我们聊了恐龙"}],
    ) == "我们刚才聊了天气和恐龙。"

    payload = network.requests[0]["payload"]
    assert "tools" not in payload
    assert "enable_search" not in payload
    assert any("不得调用任何工具" in message["content"] for message in payload["messages"])


def test_drawing_board_is_opened_only_by_llm_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_module,
        "_open_drawing_board",
        lambda: '{"ok":true,"tool":"drawing_board"}',
    )
    network = FakeNetworkClient(
        {
            "choices": [{"message": {"tool_calls": [{
                "id": "draw-call",
                "type": "function",
                "function": {"name": "open_drawing_board", "arguments": "{}"},
            }]}}]
        }
    )
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )
    events: list[dict] = []
    client.on_agent_event = events.append

    reply, messages, reason = client._run_realtime_agent_if_needed(
        "帮我打开画板", [{"role": "user", "content": "帮我打开画板"}], "test-key"
    )

    assert reply is None
    assert reason == ""
    assert messages is not None
    assert messages[-1]["content"] == '{"ok":true,"tool":"drawing_board"}'
    assert any(
        item["function"]["name"] == "open_drawing_board"
        for item in network.requests[0]["payload"]["tools"]
    )
    assert network.requests[0]["payload"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "open_drawing_board"},
    }
    assert DRAWING_BOARD_TOOL["function"]["name"] == "open_drawing_board"
    assert events[-1]["subtitle"] == "正在打开画板"


def test_reference_image_tool_uses_local_search_not_model_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    class ReferenceToolNetwork(FakeNetworkClient):
        def request_json(self, method: str, url: str, **kwargs: object) -> dict:
            self.requests.append(copy.deepcopy({"method": method, "url": url, **kwargs}))
            return {"choices": [{"message": {"tool_calls": [{
                "id": "reference-call",
                "type": "function",
                "function": {
                    "name": "show_reference_image",
                    "arguments": '{"query":"腕龙","image_url":"https://invalid.example/not-used.jpg"}',
                },
            }]}}]}

    searched: list[str] = []
    monkeypatch.setattr(
        llm_module,
        "search_reference_image",
        lambda query, **_kwargs: searched.append(query) or CameraSnapshot("data:image/jpeg;base64,AA==", 320, 240),
    )
    network = ReferenceToolNetwork({})
    network.http = object()  # type: ignore[attr-defined]
    network.select_proxies = lambda: {}  # type: ignore[attr-defined]
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )
    events: list[dict] = []
    client.on_agent_event = events.append

    reply, messages, reason = client._run_realtime_agent_if_needed(
        "腕龙长什么样", [{"role": "user", "content": "腕龙长什么样"}], "test-key"
    )

    assert reply is None
    assert reason == "reference_image"
    assert searched == ["腕龙"]
    assert messages is not None
    assert '"source":"baidu"' in messages[-2]["content"]
    assert next(event for event in events if event["type"] == "camera_snapshot_ready")["mirror"] is False
    assert REFERENCE_IMAGE_TOOL["function"]["parameters"]["required"] == ["query"]


class CameraToolNetwork(FakeNetworkClient):
    def __init__(self) -> None:
        super().__init__({})
        self.calls = 0

    def request_json(self, method: str, url: str, **kwargs: object) -> dict:
        self.requests.append(copy.deepcopy({"method": method, "url": url, **kwargs}))
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [{"message": {"tool_calls": [{
                    "id": "camera-call",
                    "type": "function",
                    "function": {"name": "inspect_current_camera", "arguments": "{}"},
                }]}}]
            }
        return {"choices": [{"message": {"content": "这是一个水杯。"}}]}


def test_camera_tool_uses_qwen37_plus_for_the_final_visual_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    network = CameraToolNetwork()
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )
    events: list[dict] = []
    client.on_agent_event = events.append
    monkeypatch.setattr(
        llm_module,
        "capture_current_camera_frame",
        lambda: CameraSnapshot("data:image/jpeg;base64,AA==", 320, 240),
    )

    reply = client.generate_reply("请用摄像头看一下我手上拿的是什么？", "系统提示")

    assert reply == "这是一个水杯。"
    assert len(network.requests) == 2
    first_messages = network.requests[0]["payload"]["messages"]  # type: ignore[index]
    second_messages = network.requests[1]["payload"]["messages"]  # type: ignore[index]
    assert "image_url" not in str(first_messages)
    assert network.requests[0]["payload"]["model"] == client.settings.llm_model
    assert network.requests[1]["payload"]["model"] == CAMERA_VL_MODEL
    assert second_messages[0]["content"] == CAMERA_VL_SYSTEM_PROMPT
    assert second_messages[-1]["content"][1]["type"] == "image_url"
    preview = next(event for event in events if event["type"] == "camera_snapshot_ready")
    assert preview["data_uri"] == "data:image/jpeg;base64,AA=="
    assert preview["width"] == 320
    assert preview["height"] == 240
    assert second_messages[-1]["content"][1]["image_url"]["url"] == preview["data_uri"]
    camera_status = next(event for event in events if event["type"] == "realtime_query_started")
    assert camera_status["subtitle"] == "让我看一看"
    assert camera_status["voice_prompt"] == "等一小会，让我仔细看一看。"
    assert "voice_prompt_rate" not in camera_status
    assert events.index(preview) < events.index(camera_status)


def test_camera_agent_prompt_requires_history_based_tool_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catch a prompt regression that lets the model dismiss visual context before looking."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    network = FakeNetworkClient({"choices": [{"message": {"content": "好的。"}}]})
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )

    client.generate_reply(
        "请看摄像头里这个呢？",
        "系统提示",
        history=[
            {"role": "user", "content": "我正拿着一个东西给你看。"},
            {"role": "assistant", "content": "好呀，你接着问。"},
        ],
    )

    tool_prompt = network.requests[0]["payload"]["messages"][-2]["content"]  # type: ignore[index]
    assert CAMERA_TOOL_INSTRUCTION in tool_prompt
    assert "默认绝不调用" in tool_prompt
    assert "总结、回顾、记忆" in tool_prompt


def test_camera_unclear_follow_up_forces_a_fresh_frame_before_answering(monkeypatch: pytest.MonkeyPatch) -> None:
    """A visual follow-up must not answer from the prior frame or claim it is unclear."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    class FollowUpNetwork(FakeNetworkClient):
        def request_json(self, method: str, url: str, **kwargs: object) -> dict:
            self.requests.append(copy.deepcopy({"method": method, "url": url, **kwargs}))
            payload = kwargs["payload"]
            if len(self.requests) == 1 and "tools" not in payload:
                return {"choices": [{"message": {"content": "我还没看清。"}}]}
            if len(self.requests) == 1:
                return {"choices": [{"message": {"tool_calls": [{
                    "id": "fresh-camera-call",
                    "type": "function",
                    "function": {"name": "inspect_current_camera", "arguments": "{}"},
                }]}}]}
            return {"choices": [{"message": {"content": "现在看清啦，这是一个水杯。"}}]}

    network = FollowUpNetwork({})
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )
    captured: list[object] = []
    monkeypatch.setattr(
        llm_module,
        "capture_current_camera_frame",
        lambda: captured.append(object()) or CameraSnapshot("data:image/jpeg;base64,AA==", 320, 240),
    )

    assert client.generate_reply(
        "请看摄像头现在呢？",
        "系统提示",
        history=[{"role": "assistant", "content": CAMERA_UNCLEAR_REPLY}],
    ) == "现在看清啦，这是一个水杯。"
    assert len(captured) == 1
    assert len(network.requests) == 2
    assert network.requests[0]["payload"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "inspect_current_camera"},
    }


@pytest.mark.parametrize("error", [CameraInspectionError("camera_frame_timeout"), OSError("stream unavailable")])
def test_camera_capture_failure_returns_fixed_clarification(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=CameraToolNetwork(),  # type: ignore[arg-type]
    )
    events: list[dict] = []
    client.on_agent_event = events.append

    def fail_capture():
        raise error

    monkeypatch.setattr(llm_module, "capture_current_camera_frame", fail_capture)

    assert client.generate_reply("请看摄像头里这是什么？", "系统提示") == CAMERA_UNCLEAR_REPLY
    assert events[-1] == {"type": "camera_snapshot_clear"}


def test_normal_text_reply_never_captures_a_camera_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    network = FakeNetworkClient({"choices": [{"message": {"content": "恐龙喜欢吃植物。"}}]})
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        llm_module,
        "capture_current_camera_frame",
        lambda: pytest.fail("ordinary dialogue must not read camera"),
    )

    assert client.generate_reply("讲一个恐龙故事", "系统提示") == "恐龙喜欢吃植物。"
    assert len(network.requests) == 1


def test_weather_forecast_includes_temperature_humidity_and_rain_data() -> None:
    class WeatherNetwork(FakeNetworkClient):
        def __init__(self) -> None:
            super().__init__({})
            self.responses = [
                {
                    "results": [
                        {"name": "贵阳", "country": "中国", "latitude": 26.6, "longitude": 106.7}
                    ]
                },
                {
                    "daily": {
                        "time": ["2026-08-19", "2026-08-20"],
                        "weather_code": [2, 61],
                        "temperature_2m_min": [20.0, 19.0],
                        "temperature_2m_max": [28.0, 25.0],
                        "apparent_temperature_min": [21.0, 20.0],
                        "apparent_temperature_max": [29.0, 26.0],
                        "precipitation_probability_max": [20, 80],
                        "wind_speed_10m_max": [12.0, 18.0],
                    },
                    "hourly": {
                        "time": ["2026-08-20T00:00", "2026-08-20T12:00"],
                        "relative_humidity_2m": [75, 91],
                    },
                },
            ]

        def request_json(self, method: str, url: str, **kwargs: object) -> dict:
            self.requests.append({"method": method, "url": url, **kwargs})
            return self.responses.pop(0)

    network = WeatherNetwork()
    tools = RealtimeInfoTools(AppSettings(proxy_mode="none"), network)  # type: ignore[arg-type]
    forecast = tools.weather_forecast("贵阳", day_offset=1)

    assert forecast["condition"] == "小雨"
    assert forecast["temperature_min_c"] == 19.0
    assert forecast["temperature_max_c"] == 25.0
    assert forecast["precipitation_probability_max_percent"] == 80
    assert forecast["relative_humidity_min_percent"] == 75
    assert forecast["relative_humidity_max_percent"] == 91
    assert any(
        item["function"]["name"] == "get_weather_forecast"
        for item in tools.definitions()
    )


def test_display_safe_text_preserves_symbols_for_ui_font_fallback() -> None:
    value = "天气☔️ 22℃，湿度88%～✓·"
    assert _display_safe_text(value) == value


def test_weather_tool_result_is_followed_by_a_natural_language_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    class ToolCallNetwork(FakeNetworkClient):
        def request_json(self, method: str, url: str, **kwargs: object) -> dict:
            self.requests.append({"method": method, "url": url, **kwargs})
            return {
                "choices": [{"message": {"tool_calls": [{
                    "id": "weather-call",
                    "function": {"name": "get_current_weather", "arguments": "{}"},
                }]}}]
            }

    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=ToolCallNetwork({}),  # type: ignore[arg-type]
    )
    client.realtime_tools.execute = lambda _name, _args: '{"ok":true}'  # type: ignore[method-assign]
    reply, messages, _ = client._run_realtime_agent_if_needed(
        "今天几度", [{"role": "user", "content": "今天几度"}], "test-key"
    )

    assert reply is None
    assert messages is not None
    assert messages[-1]["role"] == "system"
    assert "转述" in messages[-1]["content"]
    assert "JSON" in messages[-1]["content"]
    assert client.network_client.requests[0]["payload"]["tool_choice"] == {  # type: ignore[attr-defined,index]
        "type": "function",
        "function": {"name": "get_current_weather"},
    }


def test_audio_to_data_uri_encodes_wav(tmp_path: Path) -> None:
    wav_path = tmp_path / "sample.wav"
    wav_path.write_bytes(b"abc")

    assert audio_to_data_uri(wav_path) == "data:audio/wav;base64,YWJj"


def test_recognition_result_text_joins_sentence_list() -> None:
    class FakeResult:
        def get_sentence(self) -> list[dict[str, str]]:
            return [{"text": "你好，"}, {"text": "星宝"}]

    assert _recognition_result_text(FakeResult()) == "你好，星宝"


def test_streaming_recognition_error_keeps_cloud_fields_when_sdk_str_is_broken() -> None:
    class CallbackBase:
        pass

    class BrokenResult:
        status_code = 400
        code = "InvalidParameter"
        message = "sample_rate is invalid"
        request_id = "request-123"

        def __str__(self) -> str:
            raise AttributeError("headers")

    callback = _StreamingRecognitionCallback(CallbackBase)
    callback.callback.on_error(BrokenResult())

    assert callback.error is not None
    message = str(callback.error)
    assert "status_code=400" in message
    assert "code=InvalidParameter" in message
    assert "message=sample_rate is invalid" in message
    assert "request_id=request-123" in message


def test_streaming_recognition_callback_reports_changed_partial_text() -> None:
    class CallbackBase:
        pass

    class PartialResult:
        def get_sentence(self) -> dict[str, str]:
            return {"text": "星宝你好"}

    received: list[str] = []
    callback = _StreamingRecognitionCallback(
        CallbackBase,
        on_text_changed=received.append,
    )

    callback.callback.on_event(PartialResult())
    callback.callback.on_event(PartialResult())

    assert received == ["星宝你好"]


def test_asr_client_builds_payload_without_real_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    wav_path = tmp_path / "input.wav"
    wav_path.write_bytes(b"abc")
    fake_network = FakeNetworkClient(
        {"choices": [{"message": {"content": "你好"}}]},
    )

    client = DashScopeASRClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=fake_network,  # type: ignore[arg-type]
    )

    text = client.transcribe(wav_path)

    request = fake_network.requests[0]
    assert text == "你好"
    assert request["method"] == "POST"
    assert request["headers"]["Authorization"] == "Bearer test-key"  # type: ignore[index]
    assert request["payload"]["model"] == "qwen3-asr-flash"  # type: ignore[index]
    assert request["payload"]["messages"][0]["role"] == "user"  # type: ignore[index]
    assert "encode_ms" in client.last_metrics
    assert "request_ms" in client.last_metrics


def test_llm_client_clips_reply_and_uses_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    fake_network = FakeNetworkClient(
        {"choices": [{"message": {"content": "这是一个很长的回复"}}]},
    )

    reply = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none", max_reply_chars=4),
        network_client=fake_network,  # type: ignore[arg-type]
    ).generate_reply("你好", "system prompt")

    request = fake_network.requests[0]
    assert reply == "这是一个..."
    assert request["payload"]["messages"][0]["content"] == "system prompt"  # type: ignore[index]
    assert request["payload"]["temperature"] == 0.6  # type: ignore[index]
    assert request["payload"]["max_tokens"] == 96  # type: ignore[index]


def test_llm_client_honors_extended_story_reply_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    story = "小恐龙慢慢走过森林。" * 10
    fake_network = FakeNetworkClient(
        {"choices": [{"message": {"content": story}}]},
    )

    reply = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none", max_reply_chars=80),
        network_client=fake_network,  # type: ignore[arg-type]
    ).generate_reply(
        "讲一个恐龙故事",
        "故事场景。回复长度上限：220个中文字符。",
    )

    payload = fake_network.requests[0]["payload"]  # type: ignore[index]
    assert reply == story
    assert len(reply) > 80
    assert payload["max_tokens"] == 440


def test_llm_time_query_uses_local_clock_without_llm_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    class AgentNetwork(FakeNetworkClient):
        def __init__(self) -> None:
            super().__init__({})
            self.responses = [
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": "time-call",
                                        "type": "function",
                                        "function": {
                                            "name": "get_current_time",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
                {"choices": [{"message": {"content": "现在是下午三点。"}}]},
            ]

        def request_json(self, method: str, url: str, **kwargs: object) -> dict:
            self.requests.append({"method": method, "url": url, **kwargs})
            return self.responses.pop(0)

    network = AgentNetwork()
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=network,  # type: ignore[arg-type]
    )
    agent_events: list[dict] = []
    client.on_agent_event = agent_events.append
    reply = client.generate_reply("现在几点了？", "系统提示")

    assert reply.startswith("现在是")
    assert re.search(r"\d{4}年\d{1,2}月\d{1,2}日", reply)
    assert "星期" in reply
    assert len(network.requests) == 0
    assert agent_events == [
        {
            "type": "realtime_query_started",
            "tools": ["get_current_time"],
            "subtitle": "[[SEARCH]] 正在查询中",
            "voice_prompt": "",
        }
    ]


def test_llm_stream_honors_extended_story_reply_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    class FakeStreamingNetwork:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        def stream_json(self, method: str, url: str, **kwargs: object):
            self.requests.append({"method": method, "url": url, **kwargs})
            for text in ("小恐龙慢慢走过森林。" * 6, "它抬头看见了星星。" * 4):
                yield {"choices": [{"delta": {"content": text}}]}

    fake_network = FakeStreamingNetwork()
    client = DashScopeLLMClient(
        settings=AppSettings(proxy_mode="none", max_reply_chars=80),
        network_client=fake_network,  # type: ignore[arg-type]
    )

    reply = "".join(
        client.stream_reply(
            "讲一个恐龙故事",
            "故事场景。回复长度上限：220个中文字符。",
        )
    )

    payload = fake_network.requests[0]["payload"]  # type: ignore[index]
    assert len(reply) > 80
    assert payload["max_tokens"] == 440


def test_tts_client_downloads_returned_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    fake_network = FakeNetworkClient(
        {"output": {"audio": {"url": "https://example.test/reply.wav"}}},
    )
    out_path = tmp_path / "reply.wav"

    result = DashScopeTTSClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=fake_network,  # type: ignore[arg-type]
    ).synthesize("你好", out_path)

    assert result == out_path
    assert out_path.read_bytes() == b"wav"
    assert fake_network.downloads == [("https://example.test/reply.wav", out_path)]


def test_tts_client_uses_selected_voice_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    fake_network = FakeNetworkClient(
        {"output": {"audio": {"url": "https://example.test/reply.wav"}}},
    )
    profile = VoiceProfile(
        id="story",
        label="Story",
        model="cosyvoice-v3-flash",
        voice="longxiaoxia",
        volume=64,
        rate=0.9,
    )

    DashScopeTTSClient(
        settings=AppSettings(proxy_mode="none"),
        network_client=fake_network,  # type: ignore[arg-type]
        voice_profile=profile,
    ).synthesize("讲个故事", tmp_path / "reply.wav")

    payload = fake_network.requests[0]["payload"]  # type: ignore[index]
    assert payload["model"] == "cosyvoice-v3-flash"
    assert payload["input"]["voice"] == "longxiaoxia"
    assert payload["input"]["volume"] == 64
    assert payload["input"]["rate"] == 0.9


def test_clip_text_keeps_short_text() -> None:
    assert clip_text("短句", 10) == "短句"
