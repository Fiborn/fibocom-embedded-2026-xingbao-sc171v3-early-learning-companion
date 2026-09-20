# 功能防回归检查清单

本文档用于每次迭代后检查既有体验是否被新方案绕过或关闭。当前产品主线是智能儿童早教陪伴桌，屏幕触控、语音互动、主界面星宝表达、状态输入协同、视觉检测预留和儿童隐私安全是优先保护对象。

旧的实物色块小游戏不再作为当前主线小游戏继续推进。相关规则、页面和测试只作为 legacy 原型保留，不应再被写成默认小游戏入口。

## 核心原则

- `pc5.py` 作为原始可用基线保留，不删除、不重写。
- 新功能默认不依赖机械臂、舵机、串口、PWM 或 GPIO。
- 星宝反馈优先使用屏幕表情、角色动画、语音、光效、桌面区域高亮和触控提示。
- 触控是主输入，不是备用输入；关键任务必须能不用键盘完成。
- 语音询问小游戏时，先把孩子自由文本映射成固定 `game_command.intent`，不要把自由文本直接交给游戏。
- 新小游戏主动上报局内状态时提交 `mini_game_state`，不要绕过星宝核心直接调用 TTS 或 UI。
- 视觉检测接入优先提交 `vision_state`，不要直接控制主界面或板卡。
- 电脑侧只输出高层状态，板卡侧后续做安全映射。

## 必须保留的功能

| 功能 | 默认状态 | 关闭参数 | 自动检查 | 人工检查 |
| --- | --- | --- | --- | --- |
| 星宝星宝唤醒 | 开启于 `--wake-loop` / `--wake-chat` | 无直接关闭；使用 `--voice-once` 会绕过唤醒 | `tests/test_app.py` wake loop/chat 测试，`tests/test_wake_word.py` | 运行 `--wake-chat`，说“星宝星宝”后进入聊天 |
| 唤醒提示音 | 开启 | `--no-wake-ack` | `wake_ack_started` 事件测试 | 唤醒成功后听到本地提示音 |
| 接收完音频提示音 | 开启 | `--no-quick-ack` 或 `--no-tts` | `quick_ack_started` 事件测试 | 说完一句后，ASR 前应听到短提示音 |
| 连续对话窗口 | 开启于 `--wake-chat` | 使用 `--wake-loop` 或 `--voice-once` 不进入连续窗口 | wake chat 超时/退出词测试 | 唤醒一次后可连续追问 |
| 对话结束/暂停 | 开启 | 无 | LLM `end_conversation` 工具调用 | 仅当 LLM 明确请求结束工具时关闭当前对话；游戏、故事等对象的暂停不关闭聊天 |
| 流式 LLM 输出 | 默认开启 | `--no-streaming-response` | 语音事件测试 | 日志出现 `llm_delta` |
| 实时音频流式 TTS | 需显式 `--realtime-tts` | 不传 `--realtime-tts` | realtime TTS 测试 | 日志出现 `tts_stream_started` 和 `tts_stream_audio_started` |
| HTTP TTS 回退 | 开启 | 无 | realtime 失败回退测试 | `tts_stream_failed` 且 `fallback=true` 时仍有播报 |
| 文本到协同计划 | 开启 | 无 | `tests/test_coordinator.py` | “星宝我要玩游戏啦”进入 `mini_game_hub` 预留入口 |
| 固定游戏命令接口 | 开启 | 无 | `tests/test_game_api.py`、`tests/test_app.py::test_app_runs_game_command_through_adapter_and_coordination` | “我不会”被映射为 `get_hint`，游戏返回 `message` 后进入 TTS 计划 |
| 新小游戏状态输入 | 开启 | 无 | `tests/test_state_inputs.py`、`tests/test_coordinator.py` | 回放 `mini_game_state` 后，trace 有 `ui.expression` 和 `voice.speak` |
| 视觉检测状态输入 | 开启 | 无 | `tests/test_state_inputs.py`、`tests/test_app.py::test_app_runs_vision_state_input_through_coordination` | 回放 `vision_state.face_too_close` 后，星宝进入用眼距离提醒 |
| 主界面星宝表达 trace | 开启 | 无 | `tests/test_output_adapters.py`、协调器测试 | trace 中出现 `ui.expression` |
| 语音计划 trace | 开启 | `--no-tts` 只影响实际播放，不应移除计划 | `tests/test_output_adapters.py`、协调器测试 | trace 中出现 `voice.speak` |
| 机械臂非主线约束 | 开启 | 无 | action safety / serial legacy 测试 | 新功能不新增舵机、PWM、GPIO 或原始串口控制 |
| legacy 色块原型 | 保留但非主线 | 显式 color-block CLI 才触发 | `tests/test_color_block_*` | 仅在回看旧原型时使用 |

## 每次迭代后的推荐检查

1. 运行语法检查：

```powershell
python -m compileall app.py main.py core multimodal tests
```

2. 运行自动测试：

```powershell
python -m pytest
```

如果本机 Python 或 pytest 环境不可用，至少运行：

```powershell
python -m compileall .
python main.py --text-demo
```

3. 检查状态输入协同：

```powershell
python main.py --coordinate-state-file docs/examples/mini_game_state_child_made_mistake.json --coordinate-apply
python main.py --coordinate-state-file docs/examples/vision_state_face_too_close.json --coordinate-apply
python main.py --game-command-file docs/examples/game_command_get_hint.json --coordinate-apply
```

4. 检查完整语音体验：

```powershell
python main.py --wake-chat --realtime-tts --show-voice-events
```

5. 人工确认：

- “星宝我要玩游戏啦”不再默认打开旧实物色块小游戏。
- “我不会”这类语音命令先归类到固定 intent，例如 `get_hint`，再交给游戏。
- `mini_game_hub` 在未绑定具体项目时可以是 `unavailable`，但 trace 必须完整。
- `mini_game_state` 和 `vision_state` 都能留下原始事件和归一化事件。
- 星宝表达通过屏幕、语音和高层光效状态表达，不依赖机械臂。
- 文档和新任务描述不再把 `color_block_game` 当作产品主线。

## 本阶段主要回归风险

| 问题 | 原因 | 防护方式 |
| --- | --- | --- |
| 新小游戏又被绑定回旧实物色块玩法 | 旧文档和旧 CLI 仍存在 | 默认路由为 `mini_game_hub`，旧入口标注 legacy |
| 视觉检测直接控制 UI/TTS | 模块绕过协调器 | 统一提交 `vision_state`，由 `state_inputs` 归一化 |
| 游戏中星宝说话和主界面星宝表情不同步 | 小游戏自己播 TTS 或改 UI | 统一走 `run_coordinated_state_json` / `XingbaoCoordinator.plan_event` |
| 接板卡后出现低层硬件命令穿透 | 适配器边界不清 | PC 侧只输出 `screen_expression`、`led_mode` 等高层状态 |
