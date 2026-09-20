# 对面触控游戏/板卡包补充进度审查

审查对象：`work/incoming/xingbao_touch_game_board`

结论：对面已经补了游戏命令接口、反馈白名单、视觉双状态输入、交接文档和示例代码；但“能直接上板联调的统一运行时”还没有补完整。当前最成熟的是“中枢调用游戏命令，游戏返回文字，语音侧 TTS 播报”这条链路。打开游戏、主界面表情、跨进程消息、主动游戏语音请求、硬件动作/灯效执行仍需要补适配层。

## 已经补得比较完整

### 1. 游戏命令接口

代码位置：

- `src/game_api.py`
- `examples/voice_bridge_example.py`

可用入口：

```python
from src.game_api import GameCommandAdapter

response = GameCommandAdapter(app).handle_command({
    "type": "game_command",
    "game_id": "shape_game",
    "intent": "get_hint",
    "user_text": "我不会",
    "context": {"source": "voice", "child_age_group": "preschool"},
})
```

返回格式已经包含：

- `type=game_response`
- `ok`
- `game_id`
- `intent`
- `message`
- `state`
- `feedback`

`message` 是 UTF-8 文字，可交给我们现有 TTS 播放。

已支持游戏：

```text
color_game
shape_game
memory_game
counting_game
english_game
skill_game
```

已支持游戏 intent：

```text
get_rule
get_goal
get_hint
get_score
get_progress
repeat_prompt
restart_round
next_round
pause_game
exit_game
```

### 2. 反馈白名单和 sanitizer

代码位置：

- `config/action_schema.json`
- `src/action_schema.py`
- `src/feedback_policy.py`

表情白名单：

```text
neutral
smile
thinking
curious
sad
surprised
sleepy
```

动作白名单：

```text
stay_still
wave_hand
nod
shake_head
point_left
point_right
small_dance
```

灯效白名单：

```text
off
blue_breath
warm_breath
yellow_blink
rainbow
red_flash
```

这部分符合“只输出高层状态，不输出舵机角度/PWM/GPIO”的安全要求。

### 3. 视觉检测状态输入

代码位置：

- `src/desktop_integrations.py`
- `examples/vision_writer_example.py`
- `handoff/TO_VISION_TEAM.md`

已经提供两个视觉状态：

```json
{
  "distance_too_close": 0,
  "needs_water": 1
}
```

写入路径：

```text
saves/vision_status.json
```

同进程也可调用：

```python
desktop.update_vision_state(distance_too_close, needs_water)
```

这部分可以作为第一阶段视觉输入使用。

### 4. 文档补充较完整

对面提供了：

- `handoff/CENTRAL_CONTROLLER_UI_GAME_PROTOCOL.md`
- `handoff/REPLY_TO_BOARD_UI_GAME_TEAM.md`
- `handoff/MESSAGE_TO_CENTRAL_CODEX.md`
- `handoff/BOARD_DEPLOYMENT.md`
- `handoff/TO_VOICE_TEAM.md`
- `handoff/TO_VISION_TEAM.md`

这些文档已经说明了：游戏不做 TTS，只返回文字；中枢负责 TTS、意图识别、表情动作分发、UI 命令分发。

## 部分完成，还不能直接联调

### 1. 语音打开游戏

已有内部能力：

```python
DesktopLauncher.open_game()
```

当前只能打开游戏中心，返回内部字符串：

```text
game
```

还没有标准外部接口：

```python
open_game(game_id="shape_game", source="voice", context=None) -> dict
```

也不能直接通过 `game_id` 进入指定游戏。若要直接进指定游戏，需要对面把现有逻辑封装成主线程可调用的启动适配器。

### 2. 主界面星宝表情

已有内部能力：

```python
desktop.set_xingbao_state(state, seconds=4.0)
```

内部状态：

```text
idle
thinking
yawn
happy
celebrate
alert
blink
```

也有参考映射示例：

```text
smile -> happy
thinking -> thinking
sleepy -> yawn
surprised -> celebrate
```

但还没有标准外部接口：

```python
set_xingbao_expression(expression, screen_text="", source="voice", context=None) -> dict
```

也还没有把 `assistant_output.screen_expression` 真正接入桌面主循环。现在只是示例代码，不是已集成运行时。

### 3. 中枢到 UI 的消息分发

有参考文件：

```text
examples/central_ui_dispatcher_example.py
```

但它只是示例函数：

```python
dispatch_assistant_output(desktop, message, launch_game)
```

当前没有真实的：

- 本机 TCP/NDJSON server/client
- UI 主线程队列
- `message_id` 去重
- `command_result` ACK
- 断线重连
- 超时和错误回传

所以独立进程联调前，对面还需要补“消息投递到 UI 主线程”的实际代码。

### 4. 游戏主动说话到 TTS

游戏内部有：

```python
XingbaoApp.speak(text, page=None)
```

当前只做两件事：

- 把文字显示到 UI
- 写日志 `xingbao_speak`

它不会发送 `speech_request`，不会调用 TTS，也没有音频输出。

如果是我们主动调用 `game_command`，可以直接拿 `game_response.message` 播 TTS，这条链路能做。

但如果是游戏自己在某个时刻主动说话，例如开局提示、答对鼓励、失败提醒，目前还缺一个把 `speak(text)` 转发给中枢 TTS 的 hook 或消息通道。

## 未完成，需要对面或硬件侧补

### 1. 硬件动作和灯效真实执行

当前只有高层 proposal：

```json
{
  "arm_action": "stay_still",
  "led_mode": "warm_breath"
}
```

没有真实函数：

```python
apply_board_feedback(arm_action="stay_still", led_mode="off", source="voice", context=None) -> dict
```

也没有实际执行：

- 机械动作
- 灯效
- 串口/设备适配
- 执行结果 `applied=true/false`

这部分需要板卡硬件适配层补，但仍然只能接收高层白名单动作，不能接收舵机角度或底层控制指令。

### 2. 新小游戏的通用状态输入

对面现在给的是 6 个已有触控游戏的 `game_command/game_response/game_event`。

还没有看到“新小游戏”的通用状态输入标准，例如：

```json
{
  "type": "mini_game_state",
  "game_id": "new_game",
  "status": "running",
  "round": 1,
  "current_goal": "...",
  "available_actions": [],
  "message": "",
  "feedback": {}
}
```

如果后续要接新的小游戏，需要对面补一个统一的 `mini_game_state` 或新游戏适配模板，避免每个小游戏临时改协议。

### 3. 自动测试包缺失

README 写了 `tests/` 和 `python3 -m unittest discover -s tests -v`，但这次压缩包根目录实际没有 `tests/`。

我做了语法编译检查，当前包里的 Python 文件能通过 `compileall`。但缺少接口级测试和回归测试，后续联调不方便快速判断改坏了哪条链路。

## 建议直接找对面补的清单

下面这段可以直接转发给对面：

> 我们已经看过这次 `xingbao_touch_game_board` 包。`GameCommandAdapter(app).handle_command(command)`、`game_response.message/state/feedback`、反馈白名单、视觉 `saves/vision_status.json` 两个状态输入都可以进入联调。
>
> 还需要你们补下面几项，最好直接给可运行代码，不只给文档：
>
> 1. 请补一个标准游戏启动适配器：`open_game(game_id=None, source="voice", context=None) -> dict`。`game_id=None` 时打开游戏中心；传 `shape_game/color_game/...` 时能直接进入对应游戏和难度。这个函数必须保证在 Pygame UI 主线程执行，并返回结构化结果。
>
> 2. 请补一个标准表情适配器：`set_xingbao_expression(expression, screen_text="", source="voice", context=None) -> dict`。它内部映射到 `desktop.set_xingbao_state(...)` 和 `desktop.show_notice(...)`，未知表情降级到 `neutral/idle`，并返回是否执行成功。
>
> 3. 请把 `examples/central_ui_dispatcher_example.py` 从示例变成真实接入：UI 主线程要能接收 `assistant_output`，执行 `screen_expression` 和 `ui_command`，并返回 `command_result`。如果独立进程联调，请实现 `127.0.0.1:8765` UTF-8 NDJSON 或明确你们实际采用的通信方式。
>
> 4. 请给游戏主动说话增加 hook：当 `XingbaoApp.speak(text, page)` 被调用时，可以向中枢发 `speech_request`，或提供一个回调 `on_speech_request(payload)`。否则只有中枢主动调用 `game_command` 时才能播 TTS，游戏开局提示/答题反馈不会自动进 TTS。
>
> 5. 请补“新小游戏状态输入”的统一协议或模板。现在只有已有 6 个游戏的接口；后续新小游戏需要统一输出 `mini_game_state/game_event/game_response`，字段至少包含 `game_id/status/current_goal/round/message/feedback/available_actions`。
>
> 6. 请确认硬件动作和灯效由谁实现。如果不是 UI/游戏项目实现，请给板卡硬件适配层的函数名、文件位置、支持列表、执行返回格式。只能接收 `stay_still/wave_hand/nod/...` 和 `off/blue_breath/...` 这类高层白名单，不能接收舵机角度、PWM、GPIO 或原始串口命令。
>
> 7. 请补接口级测试或最小验收脚本，至少覆盖：打开游戏中心、直接打开 `shape_game`、`get_hint` 返回 TTS 文字、表情 `smile/thinking/sleepy` 映射、视觉 `[1,0]/[0,1]` 状态、未知指令降级。

## 我们这边可以先接的链路

第一阶段可以先接：

```text
孩子说“我不会”
-> 中枢映射 get_hint
-> GameCommandAdapter(app).handle_command(...)
-> response.message
-> 现有 TTS 播放
-> response.feedback.screen_expression 进入 UI 表情适配器
```

第二阶段接：

```text
孩子说“星宝我要玩游戏”
-> 中枢输出 ui_command=open_game_center
-> UI 主线程调用 open_game
-> 打开游戏中心
-> 现有 TTS 播放“好呀，我们开始小游戏”
```

第三阶段再接：

```text
assistant_output
-> speech/text 进 TTS
-> screen_expression 进主界面星宝动画
-> arm_action/led_mode 进硬件适配层
-> command_result/执行日志回传
```

当前不建议直接做完整独立进程联调，因为 UI 主线程队列、ACK、speech_request 和硬件执行层还没有补齐。

## 对方二次回复后的状态更新

对方已回复称，本轮已经补齐主界面、小游戏、中枢、语音、视觉和硬件反馈之间的接口。以下内容先按“对方声明已完成”记录，最终仍需要以新代码包和测试日志为准。

### 对方声明已经完成的新增能力

1. `open_game(...)` 统一游戏启动接口

- `game_id=None` 打开游戏中心。
- 传 `shape_game/color_game/memory_game/counting_game/english_game/skill_game` 可直接进入指定小游戏。
- `context.difficulty` 支持 `1/2/3`。
- 从语音线程、网络线程或其他工作线程调用时，实际 Pygame 操作会投递到 UI 主线程。
- 返回结构化结果，包含成功状态、游戏编号、难度、来源、错误原因、是否已在 UI 主线程执行。

2. `set_xingbao_expression(...)` 统一表情接口

- 支持 `neutral/smile/thinking/curious/sad/surprised/sleepy`。
- 自动映射到 `idle/happy/thinking/celebrate/yawn` 等主界面动画。
- 支持 `screen_text`，可同步显示提示文字。
- 未知表情降级为 `neutral/idle`。

3. 中枢通信服务

- 主界面启动后开启 `127.0.0.1:8765`。
- 通信格式为 UTF-8 NDJSON。
- 中枢可发送 `assistant_output`，包含 `screen_expression/screen_text/ui_command/arm_action/led`。
- UI 执行后返回 `command_result`，包含请求编号、整体执行结果、各项指令结果和硬件反馈校验结果。

4. 小游戏主动语音

- `XingbaoApp.speak(...)` 已增加 `on_speech_request` 回调。
- 游戏开局提示、答题反馈、提示内容和结束语等都会生成 `speech_request`。
- 中枢收到后负责调用 TTS。
- 屏幕文字显示仍保留。

5. 新小游戏统一协议

- 新增统一小游戏状态模板。
- 后续小游戏统一输出 `mini_game_state/game_event/game_response`。
- 基础字段包含 `game_id/status/current_goal/round/message/feedback/available_actions`。

6. 视觉接口

- 继续使用 `saves/vision_status.json`。
- `[1,0]` 表示距离屏幕太近。
- `[0,1]` 表示需要喝水。
- 对方声明 `[1,0]` 和 `[0,1]` 已通过验收。

7. 硬件动作和灯效

- UI 不直接控制舵机角度、PWM、GPIO 或原始串口。
- UI 只校验高层动作名称，再交给板卡硬件组实现驱动。
- 动作白名单：`stay_still/wave_hand/nod/shake_head/point_left/point_right/small_dance`。
- 灯效白名单：`off/blue_breath/warm_breath/yellow_blink/rainbow/red_flash`。
- 未知动作或灯效会降级。

### 对方声明已经通过的验收项

- 打开游戏中心。
- 直接进入 `shape_game`。
- 传入游戏难度。
- `get_hint` 返回可用于 TTS 的提示文字。
- `smile/thinking/sleepy` 表情映射。
- 未知表情降级为 `neutral/idle`。
- 未知游戏指令安全返回错误。
- 视觉状态 `[1,0]` 和 `[0,1]`。
- `speak` 产生 `speech_request`。
- Pygame 任务在 UI 主线程执行。
- 共运行 32 项相关测试，全部通过。

### 现在还需要向对方索要的材料

这次文字回复已经覆盖了之前的缺口，但为了真正接入中枢，还需要对方发新版代码包和最小验证材料：

1. 新版完整代码包，包含新增的 `open_game`、`set_xingbao_expression`、NDJSON 通信服务、`on_speech_request` 和新小游戏状态模板。
2. 32 项测试的测试文件或测试日志，最好包含命令、通过结果和失败时的错误格式。
3. `assistant_output`、`command_result`、`speech_request`、`mini_game_state` 的实际 JSON 样例各 1-2 个。
4. 硬件反馈交给板卡硬件组后的函数名、进程边界或消息格式。若硬件组还未实现，需要返回 `applied=false`，不能把“已校验”当作“已执行”。
5. UI 主线程投递机制的入口说明：外部线程调用哪个函数，消息如何入队，返回如何等待或异步回调。

拿到新版代码包后，下一步应先做离线联调验证：

```text
assistant_output(open_game_center)
-> UI command_result

assistant_output(start_game shape_game difficulty=1)
-> UI command_result

game_command(get_hint)
-> game_response.message
-> TTS

XingbaoApp.speak(...)
-> speech_request
-> TTS

assistant_output(smile + warm_breath + stay_still)
-> 表情执行 + 硬件反馈校验结果
```

## 新版 `xingbao_touch_game.zip` 代码包审查结果

审查时间：2026-07-03  
代码包位置：`D:/Projects/xingbao_companion/xingbao_touch_game.zip`  
解压位置：`work/incoming/xingbao_touch_game_latest/xingbao_touch_game`

### 结论

新版代码包已经包含对方二次回复里提到的大部分真实代码，不再只是文档声明。可以进入“离线接口联调”阶段，但还不建议直接覆盖我们当前工程或直接上板重启，因为仍有几个关键接线点需要确认。

### 已在代码中确认存在

1. 统一板卡/UI 适配层

文件：`src/board_adapter.py`

已实现：

- `BoardUIAdapter`
- `open_game(game_id=None, source="voice", context=None)`
- `set_xingbao_expression(expression, screen_text="", source="voice", context=None)`
- `apply_hardware_feedback(arm_action="stay_still", led_mode="off")`
- 工作线程调用后通过队列转到 UI 主线程执行
- `pump()` 由 Pygame 主循环每帧调用

手工验收结果：

```text
open_game() -> ok=true
open_game("shape_game", difficulty=2) -> ok=true
set_expression("sleepy") -> desktop_state="yawn"
set_expression("bad") -> desktop_state="idle"
open_game("bad_game") -> ok=false, error="unknown_game_id"
```

2. 主界面接入

文件：`desktop.py`

已确认：

- 启动参数包含 `--no-central-bridge`
- 默认启动 `127.0.0.1:8765` NDJSON 服务
- `DesktopLauncher.run()` 中调用 `board_runtime.pump()`
- 桌面和游戏切换时会 `board_runtime.bind(desktop=launcher, app=game)`
- 语音请求指定游戏时，会通过 `board_runtime.pending_game` 进入对应小游戏

3. 游戏运行时接入

文件：`src/app.py`

已确认：

- 游戏主循环调用 `runtime.pump()`
- `XingbaoApp.__init__` 支持 `on_speech_request`
- `XingbaoApp.speak(text, page)` 会在回调存在时生成：

```json
{
  "type": "speech_request",
  "text": "...",
  "page": "...",
  "source": "xingbao_touch_game"
}
```

4. 中枢通信示例/服务

文件：`examples/central_ui_dispatcher_example.py`

已确认：

- 启动 `ThreadedNDJSONServer`
- 默认 `host=127.0.0.1`
- 默认 `port=8765`
- 接收 JSON 行
- 执行 `assistant_output`
- 返回 `command_result`

手工验收结果：

```text
assistant_output(smile + start_game(shape_game) + warm_breath)
-> command_result ok=true
-> expression smile 映射到 happy
-> pending_game 设置为 shape/difficulty=1
-> hardware_feedback 校验 stay_still/warm_breath 通过
```

5. 新小游戏状态模板

文件：`src/game_api.py`

已确认：

- `build_mini_game_state(...)`
- `build_mini_game_response(...)`

基础字段包含：

```text
type
game_id
status
current_goal
round
message
feedback
available_actions
```

6. 测试文件

已确认存在：

- `tests/test_board_adapter.py`
- `tests/test_game_api.py`
- `tests/test_vision_bridge.py`
- 以及其他 UI/游戏测试文件

新增接口相关测试覆盖：

- 打开游戏中心
- 直接进入 `shape_game`
- 表情映射和未知表情降级
- 工作线程任务由 `pump()` 执行
- 新小游戏状态字段
- `speak` 生成 `speech_request`

7. 新增交接文档

文件：`handoff/BOARD_INTERFACE_IMPLEMENTATION.md`

该文档已经说明：

- 中枢如何调用 `src.board_adapter`
- 如何启动 `127.0.0.1:8765` NDJSON 服务
- 游戏主动 TTS 的 `on_speech_request` 回调
- 硬件边界
- 视觉输入
- 验收命令

### 发现的风险和未闭合点

1. `speech_request` 回调有代码，但默认桌面启动时没有绑定真实中枢发送函数

`XingbaoApp` 支持 `on_speech_request`，但 `desktop.py` 创建预加载游戏对象时当前没有传入回调：

```python
game = XingbaoApp(..., preload_only=True)
```

这意味着“游戏主动说话 -> speech_request -> 中枢 TTS”还需要一个真实发送函数接线。现在它具备回调能力，但默认运行不一定会自动把 `speech_request` 发到我们的语音中枢。

2. `examples/central_ui_dispatcher_example.py` 是服务代码，但文档也提醒单独运行时没有绑定 UI

正式联调应启动 `desktop.py`，不能只单独跑示例服务。单独跑示例服务只能检查协议错误处理。

3. 压缩包里的 `dist/xingbao_touch_game_board` 可能是旧打包产物

我检查到：

```text
dist/xingbao_touch_game_board/src/board_adapter.py 不存在
```

但根目录 `src/board_adapter.py` 存在。  
所以如果上板卡，不能直接使用这个压缩包内已有的 `dist/xingbao_touch_game_board` 旧目录；应该使用根目录源码，或重新运行打包工具生成新的 board package。

4. 本机测试环境有限，未完整跑通全部测试

我已完成：

- 关键文件 AST 语法解析通过
- `BoardUIAdapter` 手工接口验收通过
- `dispatch_assistant_output` 手工验收通过

未完成：

- 完整 `pytest/unittest` 未能跑完。原因是当前电脑的 `.venv` Python 启动器指向不存在的系统 Python；内置 Python 又没有 `pygame`。
- `compileall` 在解压目录遇到 `__pycache__` 写入权限问题；这更像是压缩包内已有缓存/权限状态导致，不代表源码语法错误。

### 当前建议

这版包可以作为真实联调基础，但不要直接覆盖当前中枢工程。下一步应该做三件事：

1. 让对面重新生成一次干净板卡包，确保 `dist/xingbao_touch_game_board` 也包含 `src/board_adapter.py` 和新版 `desktop.py`。
2. 我们这边新增一个中枢侧 NDJSON 客户端，向 `127.0.0.1:8765` 发送 `assistant_output`，接收 `command_result`。
3. 明确 `speech_request` 的反向通道：游戏主动说话时，是 UI 通过同一个 socket 发给中枢，还是中枢调用 Python 回调绑定进去。

如果要上板直接调试，需要确认板卡上运行的是根目录新版源码，而不是旧的 `dist/xingbao_touch_game_board`。
