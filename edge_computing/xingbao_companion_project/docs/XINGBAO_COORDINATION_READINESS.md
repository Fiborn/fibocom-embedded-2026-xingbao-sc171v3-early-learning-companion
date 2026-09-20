# 星宝电脑侧协同准备说明

## 当前目标

在没有连接板卡之前，先把电脑侧主链路跑通：

```text
孩子语音 / 触控 / 模块状态
-> 固定 intent 或状态归一化
-> 游戏接口或星宝表达协议
-> 星宝表情、屏幕文字、TTS 计划
-> trace 调试记录
```

这一阶段不直接控制板卡，也不下发舵机、串口、GPIO、PWM 等底层命令。电脑侧只输出高层状态，后续板卡接入时再由安全适配器映射。

## 主线调整

旧的实物色块小游戏不再作为主线小游戏继续推进。相关代码和文档只作为 legacy 原型保留，用于参考规则、视觉反馈和测试写法。

当前主线改为：

- 孩子说“星宝我要玩游戏啦”时，路由到 `mini_game_hub` 预留入口。
- 具体新小游戏尚未接入前，`mini_game_hub` 的 `tool_request.status` 可以是 `unavailable`。
- 语音侧和小游戏对接时，优先使用固定 `game_command`：语音侧把孩子的话识别成固定 intent，再调用 `src.game_api.GameCommandAdapter(app).handle_command(command)`。
- 游戏返回 `game_response`，其中 `message` 可以交给 TTS，`feedback` 只允许表情、动作、灯效等高层白名单名称。
- 游戏主动上报局内状态时，可提交 `mini_game_state`。
- 视觉检测模块提交 `vision_state`，用于用眼距离、离座、回座、久坐、桌面物体等信号。

## 已有协同骨架

- `src.game_api.GameCommandAdapter`
  - 语音和游戏之间的固定 intent 适配器。
  - 支持 `color_game`、`shape_game`、`memory_game`、`counting_game`、`english_game`、`skill_game`。
  - 支持 `get_rule`、`get_goal`、`get_hint`、`get_score`、`get_progress`、`repeat_prompt`、`restart_round`、`next_round`、`pause_game`、`exit_game`。
- `core.intent_router.IntentRouter`
  - 识别孩子文本意图。
  - 游戏请求现在指向 `mini_game_hub`。
- `core.tool_registry.ToolRegistry`
  - 登记可打开或待接入工具。
  - `color_block_game` 是 legacy 兼容项，不再作为默认游戏目标。
- `core.state_inputs.normalize_state_input`
  - 把 `game_response`、`mini_game_state`、`vision_state` 转成现有表达协议事件。
- `core.coordinator.XingbaoCoordinator`
  - 把文本、游戏响应或结构化状态转成统一计划。
- `XingbaoApp.run_game_command_json`
  - 电脑端固定游戏命令联调入口。

## 电脑端演示命令

孩子说要玩游戏，但不打开任何真实窗口：

```powershell
python main.py --coordinate-text "星宝我要玩游戏啦" --coordinate-apply
```

期望结果：

- `intent.intent = open_tool`
- `intent.target = mini_game_hub`
- `tool_request.status = unavailable`
- `tool_launched = false`
- `trace` 中出现 `ui.expression`、`voice.speak`、`tool.open`

跑通语音到游戏的最小闭环：

```powershell
python main.py --game-command-file docs/examples/game_command_get_hint.json --coordinate-apply
```

期望结果：

- `game_response.intent = get_hint`
- `game_response.message` 有儿童友好的短提示
- `plan.intent.intent = game_response`
- `plan.expression_output.intent = get_hint`
- `trace` 中出现 `ui.expression` 和 `voice.speak`

回放新小游戏状态：

```powershell
python main.py --coordinate-state-file docs/examples/mini_game_state_child_made_mistake.json --coordinate-apply
```

回放视觉检测状态：

```powershell
python main.py --coordinate-state-file docs/examples/vision_state_face_too_close.json --coordinate-apply
```

如果要实际调用 TTS，再加：

```powershell
--expression-speak --local-tts-fallback
```

## 调试 trace

`run_coordinated_text`、`run_game_command_json` 和 `run_coordinated_state_json` 都会返回 `trace`：

- `ui.expression`
  - 主界面星宝形象应渲染的表情、屏幕文字和高层动作。
  - `planned` 表示只生成计划；`applied` 表示已应用到电脑侧动作状态。
- `voice.speak`
  - 星宝应该说的话和 TTS 状态。
  - `planned` 表示已进入语音计划但本次不播放；`played` 表示已调用 TTS；`skipped` 表示本次无需语音。
- `tool.open`
  - 工具或小游戏打开请求。
  - `planned` 表示准备好但未打开；`blocked` 表示入口尚未接入；`launched` 表示已执行打开。

## 后续接板卡边界

后续接板卡时，不应改变 `IntentRouter`、`ToolRegistry`、`GameCommandAdapter`、`XingbaoCoordinator` 的核心语义。应该新增或替换适配器：

- 主界面适配器：把 `screen_expression` 映射到星宝形象动画。
- TTS 适配器：把 `message` 或 `speak_text` 排队播放。
- 小游戏适配器：把 `mini_game_hub` 绑定到具体项目窗口或 Web 页面。
- 视觉适配器：把摄像头/模型检测结果整理成 `vision_state`。
- 板卡适配器：只接收高层状态，例如 `warm_breath`、`blue_breath`、`stay_still`。

这样电脑侧测试通过的协同链路，后续可以直接迁移到真实设备联调。
