# 当前画面物品理解 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Qwen 仅在它判断需要当前画面时调用摄像头工具，用一帧图像回答孩子关于眼前物品或画面的提问。

**Architecture:** 新建单职责的 `intelligence/camera_inspection.py`，只负责读取一帧和内存 JPEG 编码。`DashScopeLLMClient` 扩展为先做工具仲裁，调用相机工具后再发出一次带图片的 Qwen 请求；`XingbaoApp` 复用现有实时工具事件，在最终流式回复之前显示“正在识别中”。

**Tech Stack:** Python 3.8+, OpenCV, NumPy, 百炼 OpenAI-compatible Chat Completions, pytest。

**Spec:** `docs/superpowers/specs/2026-08-21-camera-object-understanding-design.md`

## Global Constraints

- 摄像头源：`http://127.0.0.1:4445/?action=stream`；每次只读一帧，最多等待 2 秒。
- 只有包含“这/那个/看/手上/画面”等当前画面候选语义的提问才进入 Qwen 工具仲裁；其中也仅当 Qwen 调用 `inspect_current_camera` 才能读帧。普通聊天不得读帧或上传画面。
- 图像只存在内存，最长边 1024、JPEG 质量 80，以 data URI 发到第二阶段；禁止写图片和记录 base64。
- 取帧/请求失败或无法判断时固定回答：`我现在看不清，能把它靠近一点、拿稳一点吗？`。
- 工具调用时仅显示对话优先级字幕 `正在识别中`，不播等待语音。
- 不改动原生 Wayland 启动链或现有 YOLO、人脸、情绪、手势、击掌视觉进程。

---

### Task 1: 实现内存单帧抓取器

**Files:**
- Create: `intelligence/camera_inspection.py`
- Create: `tests/test_camera_inspection.py`

**Interfaces:**
- Produces: `CameraSnapshot(data_uri: str, width: int, height: int)`。
- Produces: `capture_current_camera_frame(source: str = CAMERA_STREAM_URL, timeout_seconds: float = 2.0) -> CameraSnapshot`。
- Produces: `CameraInspectionError(RuntimeError)`，异常 `reason` 为 `camera_frame_timeout` 或 `camera_jpeg_encode_failed`。

- [ ] **Step 1: 写失败测试**

```python
def test_capture_returns_bounded_jpeg_data_uri_and_releases(monkeypatch):
    capture = FakeCapture([(True, np.zeros((900, 1800, 3), dtype=np.uint8))])
    monkeypatch.setattr(module.cv2, "VideoCapture", lambda _source: capture)
    snapshot = module.capture_current_camera_frame(timeout_seconds=0.1)
    assert snapshot.data_uri.startswith("data:image/jpeg;base64,")
    assert max(snapshot.width, snapshot.height) == 1024
    assert capture.released is True
```

- [ ] **Step 2: 运行失败测试**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_camera_inspection.py -q`

Expected: FAIL，因为抓取模块尚不存在。

- [ ] **Step 3: 写最小实现**

```python
CAMERA_STREAM_URL = "http://127.0.0.1:4445/?action=stream"

def capture_current_camera_frame(source=CAMERA_STREAM_URL, timeout_seconds=2.0):
    capture = cv2.VideoCapture(source)
    try:
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while time.monotonic() < deadline:
            ok, frame = capture.read()
            if ok and frame is not None and frame.size:
                return _encode_snapshot(frame)
        raise CameraInspectionError("camera_frame_timeout")
    finally:
        capture.release()
```

`_encode_snapshot` 按最长边缩放、`cv2.imencode(".jpg", ..., [cv2.IMWRITE_JPEG_QUALITY, 80])` 编码并生成 data URI。

- [ ] **Step 4: 增加空帧失败测试并运行通过**

```python
def test_capture_raises_timeout_without_valid_frame(monkeypatch):
    capture = FakeCapture([(False, None)])
    monkeypatch.setattr(module.cv2, "VideoCapture", lambda _source: capture)
    with pytest.raises(module.CameraInspectionError, match="camera_frame_timeout"):
        module.capture_current_camera_frame(timeout_seconds=0.01)
    assert capture.released is True
```

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_camera_inspection.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

Run: `git add intelligence/camera_inspection.py tests/test_camera_inspection.py && git commit -m "feat: capture one in-memory camera frame"`

### Task 2: 添加 Qwen 相机工具与图文二次请求

**Files:**
- Modify: `intelligence/llm_client.py:20-360`
- Modify: `tests/test_dashscope_clients.py`

**Interfaces:**
- Consumes: `capture_current_camera_frame() -> CameraSnapshot`。
- Produces: `CAMERA_UNCLEAR_REPLY` 和 `CAMERA_INSPECTION_TOOL`。
- Emits: `realtime_query_started` 事件：`tools=["inspect_current_camera"]`、`subtitle="正在识别中"`、`voice_prompt=""`。

- [ ] **Step 1: 写失败测试，约束仅在 tool call 后才读帧并二次发送图片**

```python
def test_camera_tool_call_adds_image_only_to_second_request(monkeypatch):
    network = ToolThenVisionNetwork("inspect_current_camera", "这是一个水杯。")
    client = DashScopeLLMClient(settings=AppSettings(proxy_mode="none"), network_client=network)
    monkeypatch.setattr(llm_module, "capture_current_camera_frame", lambda: CameraSnapshot("data:image/jpeg;base64,AA==", 320, 240))
    assert client.generate_reply("我手上拿的是什么？", "系统提示") == "这是一个水杯。"
    assert len(network.requests) == 2
    assert "image_url" not in str(network.requests[0]["payload"]["messages"])
    assert network.requests[1]["payload"]["messages"][-1]["content"][1]["type"] == "image_url"
```

- [ ] **Step 2: 运行失败测试**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_dashscope_clients.py::test_camera_tool_call_adds_image_only_to_second_request -q`

Expected: FAIL，因为没有 `inspect_current_camera` 工具与图文消息。

- [ ] **Step 3: 实现统一工具仲裁**

第一阶段向 Qwen 提供 `RealtimeInfoTools.definitions()` 与以下定义：

```python
CAMERA_INSPECTION_TOOL = {"type": "function", "function": {
    "name": "inspect_current_camera",
    "description": "仅当回答必须观察星宝此刻摄像头画面时调用，例如用户问手中、面前或镜头中的物体是什么。",
    "parameters": {"type": "object", "properties": {}},
}}
```

系统指令约束该工具只用于当前画面问题，禁止泛聊、故事和记忆类问题调用；没有工具调用时保留原文本回复行为。

- [ ] **Step 4: 实现相机工具处理**

工具调用后先发“正在识别中”事件；抓取失败立刻返回 `CAMERA_UNCLEAR_REPLY`。成功时在 assistant tool call 与 `{role: "tool", content: '{"ok":true}'}` 后加入：

```python
{"role": "user", "content": [
    {"type": "text", "text": "请根据这张刚拍摄的画面回答孩子刚才的问题。看不清或不能确定时，必须只说：我现在看不清，能把它靠近一点、拿稳一点吗？"},
    {"type": "image_url", "image_url": {"url": snapshot.data_uri}},
]}
```

第二阶段 HTTP 或不确定结果均归一为固定澄清语；日志只写工具名、耗时、尺寸和错误码。

- [ ] **Step 5: 写不触发与失败测试并运行通过**

```python
def test_text_reply_without_camera_tool_never_captures(monkeypatch):
    client, network = make_text_only_client()
    monkeypatch.setattr(llm_module, "capture_current_camera_frame", lambda: pytest.fail("must not capture"))
    client.generate_reply("讲个恐龙故事", "系统提示")
    assert len(network.requests) == 1

def test_camera_failure_returns_fixed_clarification(monkeypatch):
    client = make_camera_tool_client()
    monkeypatch.setattr(llm_module, "capture_current_camera_frame", raise_camera_error)
    assert client.generate_reply("这是什么？", "系统提示") == CAMERA_UNCLEAR_REPLY
```

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_dashscope_clients.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

Run: `git add intelligence/llm_client.py tests/test_dashscope_clients.py && git commit -m "feat: let qwen inspect current camera on demand"`

### Task 3: 接入对话字幕与最终验证

**Files:**
- Modify: `app.py:4380-4490`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: agent event `realtime_query_started`，相机工具载荷为 `subtitle="正在识别中"`、空 `voice_prompt`。
- Produces: `BoardUIClient.send_ui_command(..., screen_text="正在识别中", subtitle_priority="dialogue")`；不得产生 TTS 队列项。

- [ ] **Step 1: 写失败测试**

```python
def test_camera_inspection_event_shows_dialogue_subtitle_without_waiting_tts(monkeypatch):
    app, pipeline, board, queued = make_realtime_tts_harness(monkeypatch)
    app._handle_agent_event({"type": "realtime_query_started", "tools": ["inspect_current_camera"], "subtitle": "正在识别中", "voice_prompt": ""})
    assert board.screen_texts[-1] == "正在识别中"
    assert queued == []
```

- [ ] **Step 2: 运行失败测试**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_app.py::test_camera_inspection_event_shows_dialogue_subtitle_without_waiting_tts -q`

Expected: FAIL；必要时将现有内嵌 agent-event 回调提取为可测试的 `XingbaoApp._handle_agent_event`，但保持天气逻辑不变。

- [ ] **Step 3: 实现事件转发**

对 `realtime_query_started` 的处理读取事件 `subtitle`；相机工具调用时将 `正在识别中` 作为 dialogue 优先级 UI 命令发送，空 `voice_prompt` 不调用 `_emit_tts_segment_queued`。天气的查询字幕和语音提示继续使用原有路径。

- [ ] **Step 4: 运行回归、编译和 Wayland 启动验证**

Run: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -c 'import sys, types, pytest; sys.modules["audioop"] = types.ModuleType("audioop"); raise SystemExit(pytest.main(["tests/test_app.py", "tests/test_dashscope_clients.py", "tests/test_camera_inspection.py", "tests/test_scene_animation.py", "tests/test_voice_events.py", "-q"]))'`

Run: `/usr/bin/python3 -m py_compile app.py intelligence/llm_client.py intelligence/camera_inspection.py && git diff --check && bash deploy/xingbao_service_manager.sh restart`

Expected: 全部测试通过；`autostart.log` 显示 native Wayland UI、central、vision、auth 均 ready。实际说“这是什么？”时，日志有工具名与尺寸、UI 显示“正在识别中”、无 data URI 日志。

- [ ] **Step 5: 提交 Task 3**

Run: `git add app.py intelligence/llm_client.py intelligence/camera_inspection.py tests/test_app.py tests/test_dashscope_clients.py tests/test_camera_inspection.py && git commit -m "feat: show camera inspection state in dialogue UI"`
