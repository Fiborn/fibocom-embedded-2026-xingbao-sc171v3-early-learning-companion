"""DashScope LLM client for text replies."""

from __future__ import annotations

from collections.abc import Iterator
import json
import re
import socket
from typing import Any

from core.board_ui_client import BoardUIClient
from core.network import NetworkClient
from core.settings import AppSettings, get_dashscope_api_key
from intelligence.camera_inspection import (
    CameraInspectionError,
    CameraSnapshot,
    capture_current_camera_frame,
    search_reference_image,
)
from intelligence.realtime_tools import RealtimeInfoTools
from multimodal.asr_client import BAILIAN_COMPAT_CHAT_URL


WEB_SEARCH_POLICY = (
    "联网搜索工具可用，但必须节制使用：只有用户明确要求查询、核实、最新动态，"
    "或问题依赖会变化的外部事实（如新闻、人物职位、赛事结果、价格、政策、活动安排）"
    "时才调用。普通聊天、创作、学习讲解、稳定常识、孩子的情绪陪伴一律不要联网搜索。"
    "天气、时间、空气质量等已有本地实时工具的数据也不要联网搜索。"
    "若已联网，必须依据检索结果回答，不要把未核实的旧知识当作最新事实。"
)

CAMERA_UNCLEAR_REPLY = "我现在看不清，能把它靠近一点、拿稳一点吗？"
# Keep visual answering aligned with the board's configured Qwen3.7-plus
# dialogue model.  The capture remains behind an explicit tool call.
CAMERA_VL_MODEL = "qwen3.7-plus"
CAMERA_VL_SYSTEM_PROMPT = (
    "你是星宝的实时视觉理解助手。你只依据本次提供的摄像头照片回答用户刚才的问题，"
    "不能编造画面中没有的物体、文字、人物身份、地点或事件。"
    "先理解用户问题，再观察图片；若物体、文字或细节不清晰、被遮挡或无法确定，"
    "只回答：" + CAMERA_UNCLEAR_REPLY + "。"
    "若能判断，用适合儿童、自然简短的中文直接回答，通常不超过两句；"
    "不要提及模型、工具、提示词、图片上传过程，也不要使用 Markdown。"
)
CAMERA_INSPECTION_TOOL = {
    "type": "function",
    "function": {
        "name": "inspect_current_camera",
        "description": (
            "仅当必须观察星宝此刻现实摄像头画面时调用，例如用户问手中、"
            "面前、镜头里或图里有什么。绝不能用于搜索、查询或展示网上的图片。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

REFERENCE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "show_reference_image",
        "description": "用户要求搜索、查询、找或展示某个对象、动物、恐龙、物品或地点的网页图片、外观或样子时调用。绝不能用于识别现实摄像头画面。本地程序会自行搜索和下载图片。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "图片主体的精确名称，例如“腕龙”"},
        }, "required": ["query"]},
    },
}

CURRENT_EMOTION_TOOL = {
    "type": "function",
    "function": {
        "name": "inspect_current_emotion",
        "description": "仅当用户明确请星宝看一看、识别或判断他/她此刻的心情、表情或情绪时调用。该工具会触发一次本地摄像头人脸情绪模型推理。",
        "parameters": {"type": "object", "properties": {}},
    },
}

DRAWING_BOARD_TOOL = {
    "type": "function",
    "function": {
        "name": "open_drawing_board",
        "description": (
            "仅当用户明确希望现在打开、进入或使用星宝画板来画画、涂鸦时调用。"
            "调用后会在触控屏上直接打开画板。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

CAMERA_TOOL_INSTRUCTION = (
    "inspect_current_camera 是高成本的本地摄像头工具，默认绝不调用。"
    "只有用户本轮明确提到“摄像头”，并明确要求查看、识别或确认该摄像头当前画面时才可调用。"
    "总结、回顾、记忆、复述此前对话、普通聊天、故事、知识问答，以及仅含“看一下/这个/现在呢”"
    "但未明确提到摄像头的内容，绝不能调用。"
    "获准调用后，必须取得新的一帧，不能沿用旧画面；未调用前不得猜测画面内容。"
    "仅在已调用工具后，画面模糊、遮挡或无法确定物体时，才必须只回答："
    + CAMERA_UNCLEAR_REPLY
    + "\n工具任务必须严格区分且互斥：用户说“帮我查/搜/找/展示某某的图片”、"
    "“某某长什么样”或“给我看某某的样子”，是网页图片搜索，必须调用 "
    "show_reference_image，绝不能调用 inspect_current_camera。"
    "用户说“我手里/面前/镜头里/图里有什么”或要求你看眼前实物，才是现实画面识别，"
    "必须调用 inspect_current_camera，绝不能用网页图片代替。"
    "优先级更高的例外：用户说“我找了/找到了/拿了/给你看了某个东西或图片，"
    "你能帮我看一下吗”时，指的是此刻摆在摄像头前的现实对象；即使句中出现"
    "“找”或“图片”，也必须调用 inspect_current_camera，绝不能搜索网页图片。"
)

EMOTION_TOOL_INSTRUCTION = (
    "当用户明确请求你通过看当前表情来判断“我现在心情如何/我现在的心情/我是什么情绪”时，"
    "必须调用 inspect_current_emotion，不能根据文字猜测。工具结果只是面部表情线索，"
    "回答要温和、带不确定性，不能把它说成对用户内心的确定判断。"
    "如果工具返回 ok=false、no_face_or_uncertain、hand_interaction_active 或服务不可用，"
    "不得猜测任何情绪；只需自然说明暂时没看清表情，并请用户站到镜头前、正对镜头后再试。"
)

DRAWING_BOARD_TOOL_INSTRUCTION = (
    "open_drawing_board 是打开触控屏画板的本地工具。只有用户明确要求现在“打开/进入/开始用”"
    "画板、画画或涂鸦时才调用；只是聊天、讲画画、询问怎么画或提到一幅画时绝不能调用。"
    "是否调用必须由你根据完整上下文判断，不能把本地关键词当作指令。"
    "工具返回 ok=true 后，简短自然地告诉用户画板已经打开，可以开始画；"
    "返回 ok=false 时，诚实说明画板暂时没有打开，不要假装成功。"
)


def _inspect_current_emotion(*, host: str = "127.0.0.1", port: int = 10002) -> str:
    """Ask the running vision process for one on-demand FER inference."""
    try:
        with socket.create_connection((host, port), timeout=9.0) as client:
            client.settimeout(9.0)
            client.sendall(b'{"action":"infer_emotion_once"}\n')
            data = client.recv(8192)
        payload = json.loads(data.decode("utf-8"))
        return json.dumps(payload if isinstance(payload, dict) else {"ok": False, "error": "invalid_emotion_response"}, ensure_ascii=False)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return json.dumps({"ok": False, "error": f"emotion_service_unavailable:{type(exc).__name__}"}, ensure_ascii=False)


def _open_drawing_board() -> str:
    """Open the native drawing modal requested by the model.

    ``launch_visual_tool(draw)`` first enters the generic visual-tool bridge.
    That bridge can acknowledge the command while leaving the child on its
    activity card.  The released touch desktop already owns a real ``drawing``
    modal, so address that modal directly and only report success after its UI
    thread has acknowledged the request.
    """
    try:
        result = BoardUIClient().send_ui_command(
            {"name": "open_desktop_modal", "params": {"modal": "drawing"}},
            # Keep the fully populated handoff used by the former dinosaur
            # journey.  On the released desktop this is more than cosmetic:
            # it refreshes the active display state before the native modal
            # is drawn.
            screen_text="我们去百宝箱画一画吧",
            expression="smile",
            led_mode="warm_breath",
            duration_ms=10000,
            subtitle_priority="dialogue",
        )
    except OSError as exc:
        return json.dumps(
            {"ok": False, "error": f"drawing_board_unavailable:{type(exc).__name__}"},
            ensure_ascii=False,
        )
    response = result.get("response")
    command_results = response.get("results") if isinstance(response, dict) else []
    drawing_opened = any(
        isinstance(item, dict)
        and item.get("ok") is True
        and item.get("action") == "open_desktop_modal"
        and item.get("page") == "drawing"
        for item in (command_results if isinstance(command_results, list) else [])
    )
    if result.get("ok") and drawing_opened:
        print("[drawing-board] native drawing modal opened", flush=True)
        return '{"ok":true,"tool":"drawing_board"}'
    error = response.get("error") if isinstance(response, dict) else result.get("error")
    return json.dumps(
        {
            "ok": False,
            "error": str(error or "drawing_board_command_failed"),
        },
        ensure_ascii=False,
    )

def _disable_qwen_hybrid_thinking(payload: dict[str, Any], model: str) -> None:
    """Use Qwen3 hybrid non-thinking mode for latency-sensitive voice turns."""
    normalized = (model or "").strip().lower()
    if normalized.startswith("qwen3"):
        payload["enable_thinking"] = False


def _with_web_search_policy(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Give the model a native-search policy without exposing it to users."""
    if not messages:
        return [{"role": "system", "content": WEB_SEARCH_POLICY}]
    return [messages[0], {"role": "system", "content": WEB_SEARCH_POLICY}, *messages[1:]]


class DashScopeLLMClient:
    """Generates child-friendly replies through DashScope compatible chat."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        network_client: NetworkClient | None = None,
    ) -> None:
        self.settings = settings or AppSettings.load()
        self.network_client = network_client or NetworkClient(self.settings)
        self.realtime_tools = RealtimeInfoTools(self.settings, self.network_client)
        self.on_agent_event: Any | None = None

    def _analyze_camera_snapshot(
        self,
        *,
        user_text: str,
        snapshot: CameraSnapshot,
        api_key: str,
    ) -> str:
        """Ask the dedicated Qwen-VL model to answer from one fresh frame."""
        payload: dict[str, Any] = {
            "model": CAMERA_VL_MODEL,
            "messages": [
                {"role": "system", "content": CAMERA_VL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "用户刚才的问题是：" + str(user_text or ""),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": snapshot.data_uri},
                        },
                    ],
                },
            ],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 180,
        }
        try:
            data = self.network_client.request_json(
                "POST",
                BAILIAN_COMPAT_CHAT_URL,
                headers=_auth_headers(api_key),
                payload=payload,
                timeout=90,
            )
            reply = _display_safe_text(str(_extract_message(data).get("content") or ""))
        except (RuntimeError, KeyError, IndexError, TypeError):
            return CAMERA_UNCLEAR_REPLY
        return _camera_safe_reply(reply, "camera_inspection")

    def request_conversation_end(
        self,
        user_text: str,
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> bool:
        """Ask the model whether a natural utterance ends this chat session."""
        api_key = get_dashscope_api_key()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *list(history or [])[-self.settings.max_history_turns * 2 :],
            {
                "role": "system",
                "content": (
                    "你是对话控制工具选择器。只有当孩子明确希望结束、暂停或暂时不继续“当前和星宝的对话”时，"
                    "才调用 end_conversation。比如“我们晚点再聊”“我先不聊了”“暂停和星宝聊天”。"
                    "如果是在谈故事、游戏、音乐、动画、作业或其他对象的暂停/结束，或只是描述累、再见等非明确请求，"
                    "不要调用该工具。每一次都必须调用且只能调用一个工具：符合结束条件调用"
                    "end_conversation，其余情况调用 continue_conversation。不要输出解释或普通回答。"
                ),
            },
            {"role": "user", "content": user_text},
        ]
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "end_conversation",
                        "description": "结束或暂停当前与星宝的语音对话。仅用于用户明确要求不再继续当前对话。",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "continue_conversation",
                        "description": "继续当前对话，不结束会话。用于普通聊天以及暂停游戏、音乐、故事等非对话对象。",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
            ],
            "tool_choice": "auto",
            "stream": False,
            "temperature": 0.0,
            "max_tokens": 32,
        }
        _disable_qwen_hybrid_thinking(payload, self.settings.llm_model)
        try:
            data = self.network_client.request_json(
                "POST",
                BAILIAN_COMPAT_CHAT_URL,
                headers=_auth_headers(api_key),
                payload=payload,
                timeout=20,
            )
        except RuntimeError:
            return False
        message = _extract_message(data)
        calls = message.get("tool_calls")
        return any(
            isinstance(call, dict)
            and isinstance(call.get("function"), dict)
            and call["function"].get("name") == "end_conversation"
            for call in calls or []
        )

    def generate_reply(
        self,
        user_text: str,
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        api_key = get_dashscope_api_key()
        reply_char_limit = _reply_char_limit(
            system_prompt,
            self.settings.max_reply_chars,
        )
        recent_history = (history or [])[-self.settings.max_history_turns * 2 :]
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *recent_history,
            {"role": "user", "content": user_text},
        ]
        agent_reply, agent_messages, agent_mode = self._run_realtime_agent_if_needed(
            user_text, messages, api_key
        )
        if agent_reply is not None:
            return clip_text(_camera_safe_reply(agent_reply, agent_mode), reply_char_limit)
        if agent_messages is not None:
            messages = agent_messages
        else:
            messages = _with_web_search_policy(messages)
        # Free conversation can be more lively.  Tool-grounded replies keep
        # the conservative sampling below so weather facts are not distorted.
        response_temperature = 0.6 if agent_messages is not None else 1.0
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": False,
            "temperature": response_temperature,
            "max_tokens": _max_tokens_for_char_limit(reply_char_limit),
        }
        _disable_qwen_hybrid_thinking(payload, self.settings.llm_model)
        if agent_messages is None:
            payload["enable_search"] = True
        try:
            data = self.network_client.request_json(
                "POST",
                BAILIAN_COMPAT_CHAT_URL,
                headers=_auth_headers(api_key),
                payload=payload,
                timeout=90,
            )
        except RuntimeError:
            if agent_mode == "camera_inspection":
                return CAMERA_UNCLEAR_REPLY
            raise
        try:
            reply = _display_safe_text(str(data["choices"][0]["message"]["content"]))
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Unexpected LLM response format.") from exc
        return clip_text(_camera_safe_reply(reply, agent_mode), reply_char_limit)

    def stream_reply(
        self,
        user_text: str,
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        api_key = get_dashscope_api_key()
        reply_char_limit = _reply_char_limit(
            system_prompt,
            self.settings.max_reply_chars,
        )
        recent_history = (history or [])[-self.settings.max_history_turns * 2 :]
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *recent_history,
            {"role": "user", "content": user_text},
        ]
        agent_reply, agent_messages, agent_mode = self._run_realtime_agent_if_needed(
            user_text, messages, api_key
        )
        if agent_reply is not None:
            yield clip_text(_camera_safe_reply(agent_reply, agent_mode), reply_char_limit)
            return
        if agent_messages is not None:
            messages = agent_messages
        else:
            messages = _with_web_search_policy(messages)
        # Keep free chat expressive, but retain deterministic wording once a
        # real-time tool result is present in the prompt.
        response_temperature = 0.6 if agent_messages is not None else 1.0
        if agent_mode == "camera_inspection":
            try:
                data = self.network_client.request_json(
                    "POST",
                    BAILIAN_COMPAT_CHAT_URL,
                    headers=_auth_headers(api_key),
                    payload={
                        "model": self.settings.llm_model,
                        "messages": messages,
                        "stream": False,
                        "temperature": response_temperature,
                        "max_tokens": _max_tokens_for_char_limit(reply_char_limit),
                    },
                    timeout=90,
                )
                reply = _display_safe_text(str(_extract_message(data).get("content") or ""))
            except RuntimeError:
                reply = CAMERA_UNCLEAR_REPLY
            yield clip_text(_camera_safe_reply(reply, agent_mode), reply_char_limit)
            return
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": True,
            "temperature": response_temperature,
            "max_tokens": _max_tokens_for_char_limit(reply_char_limit),
        }
        _disable_qwen_hybrid_thinking(payload, self.settings.llm_model)
        if agent_messages is None:
            payload["enable_search"] = True

        emitted_chars = 0
        for data in self.network_client.stream_json(
            "POST",
            BAILIAN_COMPAT_CHAT_URL,
            headers=_auth_headers(api_key),
            payload=payload,
            timeout=120,
        ):
            delta = _display_safe_text(_extract_stream_delta(data))
            if not delta:
                continue
            remaining = reply_char_limit - emitted_chars
            if remaining <= 0:
                break
            piece = delta[:remaining]
            emitted_chars += len(piece)
            yield piece

    def _run_realtime_agent_if_needed(
        self,
        user_text: str,
        messages: list[dict[str, str]],
        api_key: str,
    ) -> tuple[str | None, list[dict[str, Any]] | None, str]:
        """Run one safe Function Calling round for live or visual questions."""
        if _is_conversation_summary_request(user_text):
            # A summary is grounded exclusively in the turn history already
            # supplied by the caller.  Keep it out of every MCP/tool route
            # and also suppress the cloud web-search flag in the final reply.
            return (
                None,
                [
                    *messages[:-1],
                    {
                        "role": "system",
                        "content": (
                            "用户正在要求总结、回顾或概括此前对话。只能依据本次提供的聊天记录直接回答；"
                            "不得调用任何工具、MCP、摄像头、联网搜索、天气、时间、情绪识别或画板，"
                            "也不得补充记录之外的实时信息。"
                        ),
                    },
                    messages[-1],
                ],
                "conversation_summary",
            )
        is_realtime_request = _looks_like_realtime_info_request(user_text)
        is_reference_image_request = (
            _looks_like_reference_image_request(user_text)
            or _is_contextual_reference_image_follow_up(user_text, messages)
        )
        is_camera_request = _is_explicit_camera_request(user_text) and not is_reference_image_request
        is_drawing_board_candidate = _looks_like_drawing_board_request(user_text)
        if (
            not is_realtime_request
            and not is_camera_request
            and not is_reference_image_request
            and not is_drawing_board_candidate
        ):
            return None, None, ""
        # This is an explicit local tool flow, so notify the UI before the
        # model performs its online lookup rather than waiting for a URL.
        if is_reference_image_request:
            self._emit_realtime_query_started(["show_reference_image"])
        if is_realtime_request and _looks_like_current_time_request(user_text):
            # Time is deterministic and available locally.  Do not let an
            # optional tool-selection model answer from stale context before
            # it calls the clock tool.
            self._emit_realtime_query_started(["get_current_time"])
            return _current_time_reply(self.realtime_tools.current_time()), None, ""
        forced_weather_tool = _weather_tool_for_request(user_text) if is_realtime_request else ""
        precipitation_request = _looks_like_precipitation_request(user_text) if is_realtime_request else False
        if precipitation_request:
            # Rainfall questions are particularly varied (for example
            # “傍晚出门会被淋到吗” or “两小时后会有雨吗”).  Let the model
            # inspect the full utterance and select forecast/current/minutely
            # weather itself instead of reducing the intent to keywords.
            forced_weather_tool = ""
        requested_forecast_offset = _forecast_day_offset_from_request(user_text)
        requested_history_days = _history_days_ago_from_request(user_text)
        configured_city = self.realtime_tools.default_city
        agent_messages: list[dict[str, Any]] = [
            *messages[:-1],
            {
                "role": "system",
                "content": (
                    CAMERA_TOOL_INSTRUCTION
                    + "\n"
                    + EMOTION_TOOL_INSTRUCTION
                    + "\n"
                    + (DRAWING_BOARD_TOOL_INSTRUCTION if is_drawing_board_candidate else "")
                    + "\n"
                    + (
                        "当用户明确问某样东西长什么样、想看图片或样子时，必须调用 show_reference_image。"
                    "参数 query 必须只写图片主体的精确名称；本地程序会自行联网搜索、下载并展示图片，"
                    "不需要也不得提供图片 URL；不要为普通知识问答调用。"
                        if is_reference_image_request else ""
                    )
                    + "涉及当前时间、日期、星期或天气时，必须调用提供的实时工具，"
                    "不能猜测。天气城市只可使用用户明确说出的城市或家长设置的默认城市；"
                    f"家长当前设置的真实天气城市是“{configured_city}”。"
                    "若用户本句话没有明确说出其他城市，必须以该真实城市查询和回答；"
                    "不可沿用聊天记录、旧回答或模型记忆中的城市。不得获取设备或孩子的精确位置。"
                    "询问现在或今天的天气时调用实时天气工具，"
                    "询问明天、后天或未来天气时调用天气预报工具，并如实说明温度、湿度和降水信息。"
                    "涉及下雨、降雨、降水、雨量或会不会被淋湿时，必须结合完整语义选择工具："
                    "未来两小时或很快是否下雨用分钟降水工具；具体某天用天气预报；"
                    "未指定未来时段的当前雨情用实时天气工具。工具返回前不得自行回答。"
                ),
            },
            messages[-1],
        ]
        try:
            payload: dict[str, Any] = {
                "model": self.settings.llm_model,
                "messages": agent_messages,
                "tools": [
                    *self.realtime_tools.definitions(),
                    *([CAMERA_INSPECTION_TOOL] if is_camera_request else []),
                    CURRENT_EMOTION_TOOL,
                    *([REFERENCE_IMAGE_TOOL] if is_reference_image_request else []),
                    *([DRAWING_BOARD_TOOL] if is_drawing_board_candidate else []),
                ],
                # Temperature-only questions such as “今天几度” are
                # weather questions too.  Force the relevant tool so the
                # model cannot reply from stale knowledge or claim it
                # cannot answer without attempting a lookup.
                "tool_choice": (
                    {
                        "type": "function",
                        "function": {"name": forced_weather_tool},
                    }
                    if forced_weather_tool
                    else (
                        {
                            "type": "function",
                            "function": {"name": "show_reference_image"},
                        }
                        if is_reference_image_request
                        # Opening the canvas is an imperative UI action, not
                        # an answer the model may merely *say* it performed.
                        # Require the actual call, then make the final reply
                        # depend on the Wayland UI acknowledgement.
                        else (
                            {
                                "type": "function",
                                "function": {"name": "open_drawing_board"},
                            }
                            if is_drawing_board_candidate
                            # The model must select a tool for a rain question,
                            # but no concrete function is forced: it infers
                            # the appropriate weather operation from context.
                            else (
                                {
                                    "type": "function",
                                    "function": {"name": "inspect_current_camera"},
                                }
                                if is_camera_request and not is_realtime_request
                                else "required" if precipitation_request else "auto"
                            )
                        )
                    )
                ),
                "stream": False,
                "temperature": 0.2,
                "max_tokens": 240,
                "enable_search": True,
            }
            # qwen3.7-plus enables thinking by default, but its thinking
            # mode rejects object-form tool_choice.  Xingbao needs forced
            # weather tools for factual answers, so use hybrid non-thinking
            # mode for every request made with the Qwen3 family.
            _disable_qwen_hybrid_thinking(payload, self.settings.llm_model)
            data = self.network_client.request_json(
                "POST",
                BAILIAN_COMPAT_CHAT_URL,
                headers=_auth_headers(api_key),
                payload=payload,
                timeout=45,
            )
        except RuntimeError:
            # A direct "open the drawing board" request must not degrade into
            # a plausible-sounding chat reply when the optional decision call
            # is unavailable.  Execute the same audited UI tool instead.
            if is_drawing_board_candidate:
                result = _open_drawing_board()
                return (
                    "画板已经打开，可以开始画画啦。"
                    if '"ok":true' in result
                    else "画板暂时没有打开，我们稍后再试一次。",
                    None,
                    "",
                )
            # Revert to normal chat when the optional agent decision call is
            # unavailable; it must never break an ordinary voice session.
            return None, None, ""

        message = _extract_message(data)
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            if is_drawing_board_candidate:
                # Some compatible endpoints occasionally ignore a required
                # tool choice and return prose.  Do not allow that prose to
                # falsely claim success: perform the required local action
                # and make the visible reply reflect its acknowledgement.
                result = _open_drawing_board()
                return (
                    "画板已经打开，可以开始画画啦。"
                    if '"ok":true' in result
                    else "画板暂时没有打开，我们稍后再试一次。",
                    None,
                    "",
                )
            if forced_weather_tool:
                self._emit_realtime_query_started([forced_weather_tool])
                fallback_arguments: dict[str, Any] = {
                    "city": self.realtime_tools.default_city,
                }
                if (
                    forced_weather_tool == "get_weather_forecast"
                    and requested_forecast_offset is not None
                ):
                    fallback_arguments["day_offset"] = requested_forecast_offset
                if (
                    forced_weather_tool == "get_historical_weather"
                    and requested_history_days is not None
                ):
                    fallback_arguments["days_ago"] = requested_history_days
                result = self.realtime_tools.execute(
                    forced_weather_tool,
                    fallback_arguments,
                )
                agent_messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "local-forced-weather",
                                    "type": "function",
                                    "function": {
                                        "name": forced_weather_tool,
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "local-forced-weather",
                            "content": result,
                        },
                    ]
                )
                agent_messages.append(_weather_translation_instruction())
                return None, agent_messages, ""
            content = message.get("content")
            return (str(content) if content else ""), None, ""

        tool_names = [
            str(call.get("function", {}).get("name") or "")
            for call in tool_calls
            if isinstance(call, dict) and isinstance(call.get("function"), dict)
        ]
        camera_tool_requested = "inspect_current_camera" in tool_names
        reference_tool_requested = "show_reference_image" in tool_names
        if not camera_tool_requested and not reference_tool_requested:
            self._emit_realtime_query_started(tool_names)

        agent_messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        weather_tool_used = False
        camera_snapshot: CameraSnapshot | None = None
        reference_snapshot: CameraSnapshot | None = None
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "")
            arguments = _parse_tool_arguments(function.get("arguments"))
            call_id = str(call.get("id") or "")
            if name == "show_reference_image":
                try:
                    # The model supplies only the subject.  Searching and
                    # downloading happen locally so an inaccessible or
                    # fabricated model URL can never break image display.
                    reference_snapshot = search_reference_image(
                        str(arguments.get("query") or user_text),
                        http=self.network_client.http,
                        proxies=self.network_client.select_proxies(),
                    )
                except CameraInspectionError as exc:
                    result = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                    print(
                        "[reference-image] failed source=baidu query={} error={}".format(
                            str(arguments.get("query") or user_text), exc
                        ),
                        flush=True,
                    )
                else:
                    print(
                        "[reference-image] shown source=baidu query={}".format(
                            str(arguments.get("query") or user_text)
                        ),
                        flush=True,
                    )
                    self._emit_agent_event({"type": "camera_snapshot_ready", "data_uri": reference_snapshot.data_uri, "width": reference_snapshot.width, "height": reference_snapshot.height, "mirror": False})
                    result = '{"ok":true,"source":"baidu"}'
                if call_id:
                    agent_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                continue
            if name == "inspect_current_camera":
                if camera_snapshot is None:
                    try:
                        camera_snapshot = capture_current_camera_frame()
                    except (CameraInspectionError, OSError) as exc:
                        print(
                            "[camera-inspection] failed reason={}".format(str(exc)),
                            flush=True,
                        )
                        self._emit_agent_event({"type": "camera_snapshot_clear"})
                        return CAMERA_UNCLEAR_REPLY, None, "camera_inspection"
                    print(
                        "[camera-inspection] captured width={} height={}".format(
                            camera_snapshot.width,
                            camera_snapshot.height,
                        ),
                        flush=True,
                    )
                    # Show the same captured image to the child before the
                    # camera-status prompt and before Qwen receives the data.
                    self._emit_agent_event(
                        {
                            "type": "camera_snapshot_ready",
                            "data_uri": camera_snapshot.data_uri,
                            "width": camera_snapshot.width,
                            "height": camera_snapshot.height,
                        }
                    )
                    self._emit_realtime_query_started(tool_names)
                if call_id:
                    agent_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": '{"ok":true}',
                        }
                    )
                continue
            if name == "inspect_current_emotion":
                result = _inspect_current_emotion()
                if call_id:
                    agent_messages.append(
                        {"role": "tool", "tool_call_id": call_id, "content": result}
                    )
                continue
            if name == "open_drawing_board":
                result = _open_drawing_board()
                if call_id:
                    agent_messages.append(
                        {"role": "tool", "tool_call_id": call_id, "content": result}
                    )
                continue
            # A model can repeat a city from conversation history even when
            # the child did not say one in this turn.  The parent-selected
            # city is authoritative in that case and is read afresh above.
            requested_city = str(arguments.get("city") or "").strip()
            if not _user_explicitly_mentions_city(user_text, requested_city):
                arguments["city"] = configured_city
            if (
                name == "get_weather_forecast"
                and requested_forecast_offset is not None
            ):
                # The natural-language date belongs to the child, not the
                # model's discretionary tool arguments.  This prevents
                # “7天后” from silently becoming today's weather.
                arguments["day_offset"] = requested_forecast_offset
            if (
                name == "get_historical_weather"
                and requested_history_days is not None
            ):
                arguments["days_ago"] = requested_history_days
            result = self.realtime_tools.execute(name, arguments)
            weather_tool_used = weather_tool_used or name in {
                "get_current_weather", "get_weather_forecast", "get_historical_weather",
                "get_weather_alert", "get_minutely_precipitation",
                "get_lifestyle_indices", "get_air_quality",
            }
            if call_id:
                agent_messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": result}
                )

        if weather_tool_used:
            # Put this after the tool results, closest to the final generation
            # turn.  The values remain internal evidence; the child hears a
            # natural-language explanation rather than a copied API record.
            agent_messages.append(_weather_translation_instruction())
        if camera_snapshot is not None:
            # The dialogue model only decided whether camera access is
            # necessary.  A dedicated multimodal model owns image reasoning
            # and produces the child-facing answer from this fresh frame.
            return (
                self._analyze_camera_snapshot(
                    user_text=user_text,
                    snapshot=camera_snapshot,
                    api_key=api_key,
                ),
                None,
                "camera_inspection",
            )
        if reference_snapshot is not None:
            agent_messages.append({"role": "system", "content": "图片已展示在屏幕中央。现在用简短、适合孩子的语言回答问题。"})
            return None, agent_messages, "reference_image"
        return None, agent_messages, ""

    def _emit_realtime_query_started(self, tools: list[str]) -> None:
        if "inspect_current_camera" in tools:
            self._emit_agent_event(
                {
                    "type": "realtime_query_started",
                    "tools": tools,
                    "subtitle": "让我看一看",
                    "voice_prompt": "等一小会，让我仔细看一看。",
                }
            )
            return
        if "inspect_current_emotion" in tools:
            self._emit_agent_event(
                {
                    "type": "realtime_query_started",
                    "tools": tools,
                    "subtitle": "正在识别中",
                    "voice_prompt": "等一小会，让我看看你的表情。",
                }
            )
            return
        if "show_reference_image" in tools:
            self._emit_agent_event({"type": "realtime_query_started", "tools": tools, "subtitle": "[[SEARCH]] 正在查询中", "voice_prompt": "等一小会，我正在联网搜索。"})
            return
        if "open_drawing_board" in tools:
            self._emit_agent_event(
                {
                    "type": "realtime_query_started",
                    "tools": tools,
                    "subtitle": "正在打开画板",
                    "voice_prompt": "",
                }
            )
            return
        is_time_only = bool(tools) and all(
            tool == "get_current_time" for tool in tools
        )
        self._emit_agent_event(
            {
                "type": "realtime_query_started",
                "tools": tools,
                # This is an internal control prefix.  The board UI renders a
                # native-drawn lens rather than trying to display an emoji.
                "subtitle": "[[SEARCH]] 正在查询中",
                # The local clock returns immediately.  Do not insert a
                # spoken filler before its answer; weather can take a network
                # round-trip, so it still gets the child-friendly prompt.
                "voice_prompt": "" if is_time_only else "稍等，我正在查询。",
            }
        )

    def _emit_agent_event(self, event: dict[str, Any]) -> None:
        callback = self.on_agent_event
        if not callable(callback):
            return
        try:
            callback(event)
        except Exception:
            # UI/voice feedback is auxiliary; never prevent a real-time tool
            # result from reaching the child when a feedback device is busy.
            pass

def clip_text(text: str, max_chars: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "..."


def _camera_safe_reply(text: str, mode: str) -> str:
    """Replace visual uncertainty with the child-facing fixed clarification."""
    cleaned = str(text or "").strip()
    if mode != "camera_inspection":
        return cleaned
    uncertainty_words = ("看不清", "看不到", "无法判断", "不能判断", "不确定", "模糊", "遮挡")
    if not cleaned or any(word in cleaned for word in uncertainty_words):
        return CAMERA_UNCLEAR_REPLY
    return cleaned


def _reply_char_limit(system_prompt: str, default: int) -> int:
    match = re.search(r"回复长度上限[：:]\s*(\d+)", system_prompt or "")
    if match is None:
        return max(1, int(default))
    return max(1, min(600, int(match.group(1))))


def _max_tokens_for_char_limit(char_limit: int) -> int:
    # Ordinary 80-character replies no longer ask the model to generate a
    # wasteful 220-token tail. Longer scenarios still receive enough budget.
    return max(96, min(480, int(char_limit) * 2))


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _extract_stream_delta(data: dict[str, Any]) -> str:
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(choice, dict):
        return ""

    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content

    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content

    text = choice.get("text")
    return text if isinstance(text, str) else ""


def _extract_message(data: dict[str, Any]) -> dict[str, Any]:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Unexpected agent response format.") from exc
    if not isinstance(message, dict):
        raise RuntimeError("Unexpected agent message format.")
    return message


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _current_time_reply(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "现在暂时无法读取时间。"
    date = _format_chinese_date(str(data.get("date") or ""))
    weekday = str(data.get("weekday") or "")
    time = str(data.get("time") or "")
    return _display_safe_text(f"现在是{date}{weekday}{time}。")


def _format_chinese_date(value: str) -> str:
    """Render the local clock's ISO date in the board-friendly 年月日 form."""
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value.strip())
    if match is None:
        return value
    year, month, day = (int(part) for part in match.groups())
    return f"{year}年{month}月{day}日"


def _display_safe_text(text: str) -> str:
    """Preserve model text; the touch UI selects a glyph fallback per character."""
    return str(text or "")


def _looks_like_realtime_info_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    keywords = (
        "天气", "温度", "湿度", "几度", "多少度", "热不热", "冷不冷",
        "下雨", "降雨", "降水", "雨量", "雨吗", "晴吗", "淋湿", "带伞", "刮风", "风大", "穿什么",
        "几点", "时间", "现在几号", "今天几号", "星期几", "周几", "日期",
    )
    return any(keyword in normalized for keyword in keywords)


def _is_conversation_summary_request(text: str) -> bool:
    """Recognize requests to summarize the already-provided chat history."""
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    if not normalized:
        return False
    direct_phrases = (
        "总结一下",
        "总结前面",
        "总结之前",
        "总结刚才",
        "概括一下",
        "回顾一下",
        "复述一下",
        "梳理一下",
        "前面聊了什么",
        "之前聊了什么",
        "刚才聊了什么",
        "之前的对话",
        "前面的对话",
        "聊天记录",
        "对话内容",
    )
    return any(phrase in normalized for phrase in direct_phrases)


def _looks_like_drawing_board_request(text: str) -> bool:
    """Only decide whether to offer the tool; the model decides the intent."""
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    return any(word in normalized for word in ("画板", "画画", "涂鸦"))


def _looks_like_current_camera_candidate(text: str) -> bool:
    """Route broad deictic visual questions to Qwen's tool decision, not capture."""
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    return any(
        phrase in normalized
        for phrase in (
            "这是什么", "那是什么", "这个", "那个", "手上", "手里", "拿着",
            "拿的", "你看", "看我", "看到了", "画面", "镜头", "面前", "桌上",
            "照片", "图片", "图里", "看清", "再看", "看看", "看一下", "看一眼", "瞧瞧",
        )
    )


def _is_explicit_camera_request(text: str) -> bool:
    """Allow capture only for an explicit request about the camera itself."""
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    if "摄像头" not in normalized:
        return False
    if any(word in normalized for word in ("总结", "回顾", "复述", "记忆", "之前对话", "刚才对话")):
        return False
    return any(word in normalized for word in ("看", "识别", "画面", "拍到", "拍的", "镜头", "确认"))


def _looks_like_presented_camera_request(text: str) -> bool:
    """Recognize an object the child says is already in front of Xingbao.

    A phrase such as “我找了腕龙图片，你能帮我看一下吗” means “inspect
    the image I have presented”, rather than “find a web image of a
    brachiosaurus”.  This intentionally takes precedence over generic image
    search keywords.
    """
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    has_presented_object = any(
        phrase in normalized
        for phrase in (
            "我找了", "我找到", "我拿了", "我拿着", "我给你看", "给你看了",
            "放在这", "摆在这", "就在这里", "在我面前", "在手里", "在桌上",
        )
    )
    asks_to_inspect = any(
        phrase in normalized
        for phrase in ("帮我看", "你能看", "看一下", "看一看", "看看", "瞧瞧", "识别", "这是什么")
    )
    return has_presented_object and asks_to_inspect


def _looks_like_reference_image_request(text: str) -> bool:
    """Identify explicit requests to see a general reference image online."""
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    if any(
        phrase in normalized
        for phrase in (
            "长什么样", "长啥样", "看看图片", "看张图片", "给我看图片",
            "找张图片", "看看它的样子", "看看样子", "显示图片",
        )
    ):
        return True
    # “帮我查一下万龙的图片” is a network image request, not a request to
    # inspect an image that is currently in front of the camera.  Keep this
    # separate from “图里有什么” and “看我手里的图片”, which remain camera use.
    image_word = (
        "图片" in normalized
        or "照片" in normalized
        or ("图" in normalized and "图里" not in normalized)
    )
    return image_word and any(
        verb in normalized
        for verb in ("查", "查询", "搜", "搜索", "搜寻", "找", "展示", "显示", "网页", "联网", "网上")
    )


def _is_contextual_reference_image_follow_up(
    user_text: str,
    messages: list[dict[str, str]],
) -> bool:
    """Keep a web-image conversation out of the live-camera route."""
    normalized = re.sub(r"\s+", "", str(user_text or "").lower()).rstrip("。！？?!")
    if normalized not in {"再看一下", "再看一眼", "换一张", "换个图片", "这个呢", "这个怎么样"}:
        return False
    recent_dialogue = " ".join(
        str(message.get("content") or "") for message in messages[-5:-1]
    )
    return _looks_like_reference_image_request(recent_dialogue)


def _is_contextual_camera_follow_up(
    user_text: str,
    messages: list[dict[str, str]],
) -> bool:
    """Recognize a short visual retry from its recent dialogue context."""
    normalized = re.sub(r"\s+", "", str(user_text or "").lower()).rstrip("。！？?!")
    if normalized not in {"现在呢", "这样呢", "这次呢", "现在可以吗", "现在好了吗"}:
        return False
    recent_dialogue = " ".join(
        str(message.get("content") or "") for message in messages[-5:-1]
    )
    return any(
        marker in recent_dialogue
        for marker in (
            CAMERA_UNCLEAR_REPLY,
            "看不清",
            "摄像头",
            "画面",
            "镜头",
            "手上",
            "手里",
            "拿着",
            "物体",
            "这是什么",
            "看一下",
            "看到了",
        )
    )


def _looks_like_current_time_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    keywords = ("几点", "时间", "现在几号", "今天几号", "星期几", "周几", "日期")
    return any(keyword in normalized for keyword in keywords)


def _looks_like_precipitation_request(text: str) -> bool:
    """Recognize the broad domain, leaving the exact tool to the LLM."""
    normalized = re.sub(r"\s+", "", (text or "").lower())
    return any(
        word in normalized
        for word in ("下雨", "降雨", "降水", "雨量", "雨", "淋湿", "带伞")
    )


def _user_explicitly_mentions_city(user_text: str, city: str) -> bool:
    """Whether this turn, rather than history, contains the requested city."""
    normalized_text = re.sub(r"\s+", "", (user_text or "").lower())
    normalized_city = re.sub(r"\s+", "", (city or "").lower()).strip()
    if not normalized_city:
        return False
    aliases = {normalized_city}
    if normalized_city.endswith("市") and len(normalized_city) > 1:
        aliases.add(normalized_city[:-1])
    return any(alias in normalized_text for alias in aliases)


def _weather_tool_for_request(text: str) -> str:
    normalized = re.sub(r"\s+", "", (text or "").lower())
    if any(word in normalized for word in ("空气质量", "aqi", "雾霾", "pm2.5")):
        return "get_air_quality"
    if any(word in normalized for word in ("穿什么", "穿衣指数", "适合运动", "运动指数", "紫外线", "防晒", "洗车指数")):
        return "get_lifestyle_indices"
    if any(word in normalized for word in ("分钟降水", "马上下雨", "雨什么时候", "两小时会下雨")) or re.search(
        r"(?:未来|过|后)?(?:一|两|二|三|1|2|3)(?:个)?小时.*(?:下雨|降雨|降水|有雨)",
        normalized,
    ):
        return "get_minutely_precipitation"
    weather_words = (
        "天气", "温度", "湿度", "几度", "多少度", "热不热", "冷不冷",
        "下雨", "降雨", "降水", "雨量", "雨吗", "晴吗", "刮风", "风大", "穿什么",
    )
    if not any(word in normalized for word in weather_words):
        return ""
    if any(word in normalized for word in ("预警", "警报", "台风预警", "暴雨预警", "雷暴预警", "大风预警")):
        return "get_weather_alert"
    if _history_days_ago_from_request(normalized) is not None:
        return "get_historical_weather"
    if _forecast_day_offset_from_request(normalized) is not None or any(
        word in normalized for word in ("未来", "预报", "一周", "七天")
    ):
        return "get_weather_forecast"
    return "get_current_weather"


def _history_days_ago_from_request(text: str) -> int | None:
    """Extract a supported historical day offset from natural Chinese speech."""
    normalized = re.sub(r"\s+", "", (text or "").lower())
    if "昨天" in normalized:
        return 1
    if "前天" in normalized:
        return 2
    if "上周" in normalized:
        return 7
    match = re.search(r"(\d{1,2})天前", normalized)
    if match is not None:
        return int(match.group(1))
    chinese_match = re.search(r"([一二三四五六七八九十两]+)天前", normalized)
    if chinese_match is not None:
        return _chinese_day_number(chinese_match.group(1))
    return None


def _forecast_day_offset_from_request(text: str) -> int | None:
    """Extract an explicit future day from Chinese or Arabic phrasing."""
    normalized = re.sub(r"\s+", "", (text or "").lower())
    if "明天" in normalized:
        return 1
    if "后天" in normalized:
        return 2
    if "一周后" in normalized or "下周" in normalized:
        return 7
    match = re.search(r"(\d{1,2})天后", normalized)
    if match is not None:
        return int(match.group(1))
    chinese_match = re.search(r"([一二三四五六七八九十两]+)天后", normalized)
    if chinese_match is not None:
        return _chinese_day_number(chinese_match.group(1))
    return None


def _chinese_day_number(value: str) -> int | None:
    """Parse the Chinese day counts used in weather questions (1–99)."""
    digits = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "两": 2,
    }
    if value == "十":
        return 10
    if "十" not in value:
        return digits.get(value)
    left, right = value.split("十", 1)
    tens = digits.get(left, 1) if left else 1
    ones = digits.get(right, 0) if right else 0
    return tens * 10 + ones


def _weather_translation_instruction() -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "请把刚才的天气工具结果转述成自然、儿童友好的中文回答，"
            "绝不能照抄 JSON、字段名或 API 原文。必须自然地说出温度和相对湿度；"
            "若是预报，还要自然说明温度范围、湿度范围和降水可能性，并给一句简短建议。"
            "若是历史天气，必须说明对应日期或“几天前”，并根据工具结果说明温度范围、湿度、降水和天气变化；"
            "不能把历史结果说成今天或当前天气。"
            "若是天气预警，必须先说明有无当前生效的官方预警；有预警时只转述工具提供的事件、级别和安全指引，"
            "提醒孩子马上告诉身边大人、按官方指引做好防护，不能淡化风险或编造解除时间。"
        ),
    }
