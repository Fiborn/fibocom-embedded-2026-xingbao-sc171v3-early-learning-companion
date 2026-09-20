# 板卡/UI/游戏侧接口回传说明

本文档用于回复`TO_BOARD_UI_GAME_TEAM.md`。以下内容均按当前实际代码填写，区分“已可直接调用”“已有内部能力但缺少对外适配器”“需要其他模块实现”。

## 一、回传结论总表

| 对方需求 | 当前状态 | 当前可用入口 | 是否能直接联调 |
| --- | --- | --- | --- |
| 打开游戏界面 | 部分完成 | `DesktopLauncher.open_game()` | 只能打开游戏中心，暂不支持传`game_id`直接打开指定游戏 |
| 游戏命令接口 | 已完成 | `src.game_api.handle_command(app,command)`或`GameCommandAdapter(app).handle_command(command)` | 可以 |
| 主界面表情接口 | 部分完成 | `DesktopLauncher.set_xingbao_state(state,seconds)` | 内部可用，缺少对方要求的标准外部函数 |
| 机械臂动作接口 | 未在UI项目实现 | 只有动作白名单和反馈proposal | 不可以，需要硬件适配层 |
| 灯效接口 | 未在UI项目实现 | 只有灯效白名单和反馈proposal | 不可以，需要硬件适配层 |
| TTS播放入口 | 未在UI项目实现 | 游戏只输出文字`message` | 使用语音侧现有TTS |
| UI主线程投递 | 尚无独立跨进程投递器 | 当前事件循环在Pygame主线程 | 跨线程调用前需要增加队列或自定义Pygame事件 |

## 二、游戏界面启动器回传

### 1.当前真实函数

文件：`desktop.py`

```python
class DesktopLauncher:
    def open_game(self):
        self.save_preferences()
        self.running = False
        return "game"
```

当前调用位置：

- 点击主界面“小抽屉→一起玩”。
- 按`G`、回车或空格。
- 桌面事件循环返回`"game"`。
- `desktop.py`外层循环调用`game.activate_display(...)`。
- 已预加载的`XingbaoApp`进入小游戏中心。

### 2.当前返回值

当前返回内部字符串：

```text
game
```

当前还不是对方建议的结构化返回：

```json
{
  "ok": true,
  "game_id": "shape_game",
  "page": "game"
}
```

### 3.当前边界

- 能打开完整小游戏中心。
- 游戏中心已经预加载，切换时不重新创建游戏对象。
- 不能通过现有`open_game()`参数直接指定`shape_game`。
- 如果要直接打开指定游戏，需要在外层场景切换完成后调用：

```python
game.activate_display(fullscreen=True)
game.start_game("shape", difficulty=1)
```

外部游戏ID与内部ID映射：

```text
color_game→color
shape_game→shape
memory_game→memory
counting_game→counting
english_game→english
skill_game→skill
```

### 4.建议给语音侧的当前第一阶段调用

第一阶段建议先打开游戏中心，不直接指定游戏：

```text
open_tool/mini_game_hub
→UI主线程调用DesktopLauncher.open_game()
→进入游戏中心
→孩子触控选择游戏
```

如果第一阶段必须默认直接打开一个游戏，建议默认：

```text
shape_game
```

但需要UI侧再补一个带`game_id`的外部启动适配器，现有函数签名尚不满足。

## 三、游戏命令接口回传

### 1.状态

该部分已经完成，可以直接联调。

文件：

```text
src/game_api.py
```

### 2.当前函数名

方式一：

```python
from src.game_api import handle_command

response = handle_command(app, command)
```

方式二：

```python
from src.game_api import GameCommandAdapter

adapter = GameCommandAdapter(app)
response = adapter.handle_command(command)
```

### 3.输入格式

```json
{
  "type": "game_command",
  "game_id": "shape_game",
  "intent": "get_hint",
  "user_text": "我不会",
  "context": {
    "source": "voice",
    "child_age_group": "preschool"
  }
}
```

### 4.已支持intent

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

### 5.输出格式

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_hint",
  "message": "提示：找到圆形",
  "state": {
    "round": 1,
    "score": 0,
    "current_goal": "找到圆形"
  },
  "feedback": {
    "screen_expression": "curious",
    "arm_action": "stay_still",
    "led_mode": "yellow_blink"
  }
}
```

### 6.语音侧如何使用

```python
response = adapter.handle_command(command)

if response["ok"]:
    existing_tts_function(response["message"])
    expression = response.get("feedback", {}).get("screen_expression")
    arm_action = response.get("feedback", {}).get("arm_action")
    led_mode = response.get("feedback", {}).get("led_mode")
```

`message`是UTF-8文字，不是音频、音频路径或语音流。

### 7.线程要求

`handle_command()`中的部分intent会改变游戏状态，例如提示、重开、暂停和退出。因此应在Pygame UI主线程调用。

如果ASR/LLM在其他线程，不要直接调用，应先把`game_command`放入线程安全队列，由UI主循环取出并执行。

## 四、主界面星宝表情回传

### 1.当前内部函数

文件：`desktop.py`

```python
desktop.set_xingbao_state("thinking", seconds=4.0)
```

函数签名：

```python
def set_xingbao_state(self, state, seconds=4.0):
    ...
```

### 2.当前内部动画状态

```text
idle
thinking
yawn
happy
celebrate
alert
blink
```

对应资源位于：

```text
assets/desktop/xingbao_frames/idle_0..3.png
assets/desktop/xingbao_frames/thinking_0..3.png
assets/desktop/xingbao_frames/yawn_0..3.png
assets/desktop/xingbao_frames/celebrate_0..3.png
```

### 3.当前已有外部表情白名单

文件：

```text
config/action_schema.json
src/action_schema.py
```

当前白名单：

```text
neutral
smile
thinking
curious
sad
surprised
sleepy
```

对方需求中的以下三个名称当前不在白名单：

```text
caring
encouraging
happy
```

### 4.建议映射

| 外部expression | 当前UI动画 | 说明 |
| --- | --- | --- |
| `neutral` | `idle` | 直接支持 |
| `smile` | `happy` | 当前会使用庆祝类全身帧 |
| `thinking` | `thinking` | 直接支持 |
| `curious` | `thinking` | 暂时复用思考动画 |
| `sad` | `thinking` | 暂时复用温和失落帧 |
| `surprised` | `celebrate` | 暂时复用庆祝动画 |
| `sleepy` | `yawn` | 直接支持 |
| `caring` | `idle` | 建议降级为温和待机 |
| `encouraging` | `happy` | 建议降级为开心动画 |
| `happy` | `happy` | 可映射，但建议中枢统一归一化为`smile` |

### 5.当前缺失

目前没有对方要求的标准函数：

```python
set_xingbao_expression(expression,screen_text,source,context)
```

目前`screen_text`也没有独立中枢输入接口。主界面内部可用：

```python
desktop.show_notice(screen_text)
```

因此该部分属于“已有动画能力，缺统一外部适配器”。

### 6.线程要求

表情切换和屏幕文字必须在Pygame UI主线程执行。外部线程应投递消息，不能直接修改Pygame Surface。

## 五、机械臂与灯效回传

### 1.当前完成部分

UI/游戏项目已经完成：

- 动作白名单。
- 灯效白名单。
- 非法值sanitizer降级。
- 每个游戏intent和游戏事件的反馈proposal。

文件：

```text
config/action_schema.json
src/action_schema.py
src/feedback_policy.py
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

### 2.当前未完成部分

当前项目没有以下真实执行函数：

```python
apply_board_feedback(...)
```

当前项目不会：

- 驱动舵机。
- 写PWM。
- 写GPIO。
- 发送机械臂串口命令。
- 驱动实体灯带。

因此UI/游戏侧只能返回高层proposal，真实`applied=true`必须由板卡硬件适配层实现后才能返回。

### 3.安全建议

硬件适配层未完成前统一使用：

```json
{
  "arm_action": "stay_still",
  "led_mode": "off",
  "applied": false,
  "reason": "hardware_adapter_not_connected"
}
```

不能把“proposal已经生成”写成“机械动作已经执行”。

## 六、TTS播放入口回传

### 1.当前游戏行为

文件：`src/app.py`

```python
def speak(self, text, page=None):
    self.message = text
    self.log(EventName.XINGBAO_SPEAK, page=page, payload={"text": text})
```

当前只做：

- 把文字显示在游戏UI。
- 写入`xingbao_speak`日志。

当前不做：

- 不播放TTS。
- 不生成音频。
- 不进入板卡音频队列。

### 2.本次回传决定

TTS由语音侧已经跑通的现有TTS函数负责。

游戏侧返回：

```text
game_response.message
```

语音侧调用：

```python
existing_tts_function(response["message"])
```

当前UI/游戏项目不提供独立`speak_text()`队列，避免与语音侧重复播放。

## 七、推荐总适配器回传

对方建议的`XingbaoBoardRuntime`目前不能完整返回，因为五项能力分属不同模块。

当前可以组成：

```python
class XingbaoBoardRuntime:
    def __init__(self, desktop, game_app, board_adapter=None, tts=None):
        self.desktop = desktop
        self.game_app = game_app
        self.board_adapter = board_adapter
        self.tts = tts

    def handle_game_command(self, command):
        from src.game_api import GameCommandAdapter
        return GameCommandAdapter(self.game_app).handle_command(command)
```

以下函数仍需补适配层：

```text
open_game(game_id,...)
set_xingbao_expression(...)
apply_board_feedback(...)
speak_text(...)
```

其中：

- `open_game`和`set_xingbao_expression`由UI侧补。
- `apply_board_feedback`由硬件侧补。
- `speak_text`直接复用语音侧现有TTS，UI侧不重复实现。

## 八、对方要求的七项信息正式回复

### 1.打开游戏界面的函数名、参数、返回值

当前函数：

```python
DesktopLauncher.open_game()
```

当前无参数，返回内部字符串`"game"`。可以打开游戏中心，但不能直接指定`game_id`。标准化外部接口仍需补充。

### 2.默认打开哪个游戏ID

当前默认行为是打开游戏中心，不默认进入单个游戏。

如果语音侧第一阶段必须指定默认游戏，双方建议使用：

```text
shape_game
```

### 3.游戏是否提供`handle_command(command)`

是，已经提供：

```python
GameCommandAdapter(app).handle_command(command)
```

### 4.主界面表情函数名、支持列表

当前内部函数：

```python
DesktopLauncher.set_xingbao_state(state,seconds=4.0)
```

内部状态：

```text
idle/thinking/yawn/happy/celebrate/alert/blink
```

标准外部`set_xingbao_expression()`仍需补充。

### 5.机械臂/灯效函数名、支持列表

没有真实硬件执行函数。

已有白名单：

```text
动作：stay_still/wave_hand/nod/shake_head/point_left/point_right/small_dance
灯效：off/blue_breath/warm_breath/yellow_blink/rainbow/red_flash
```

### 6.TTS由谁播放

由语音侧现有TTS播放。游戏只返回`message`文字，UI侧没有自己的TTS队列。

### 7.线程要求

- `handle_game_command()`：UI主线程。
- `set_xingbao_state()`：UI主线程。
- 打开或切换游戏场景：UI主线程。
- 机械臂/灯效：按硬件适配层线程规则，但不能阻塞UI主线程。
- ASR/LLM线程必须通过队列或Pygame自定义事件投递到UI主线程。

## 九、第一条联调当前可执行方案

### 链路一：打开游戏

当前可执行到游戏中心：

```text
孩子说“星宝我要玩游戏”
→语音侧识别open_tool/mini_game_hub
→投递到UI主线程
→调用DesktopLauncher.open_game()
→桌面返回"game"
→外层循环切换到已预加载的XingbaoApp
→显示小游戏中心
→语音侧现有TTS说“好呀，我们开始小游戏”
```

当前`smile`需要映射到UI内部`happy`；`warm_breath`只能形成proposal，实体灯效等待硬件适配层。

### 链路二：游戏提示

该链路游戏部分已可执行：

```python
response = GameCommandAdapter(game_app).handle_command({
    "type": "game_command",
    "game_id": "shape_game",
    "intent": "get_hint",
    "user_text": "我不会",
    "context": {"source": "voice", "child_age_group": "preschool"},
})

existing_tts_function(response["message"])
```

随后：

- `screen_expression`交给待补的UI表情适配器。
- `arm_action`和`led_mode`交给待补的硬件适配器。

## 十、最终回传结论

目前可以立即联调的是`handle_game_command(command)`和游戏返回的`message/state/feedback`。

打开游戏已有内部能力，但缺少标准`open_game(game_id,source,context)`外部接口。表情已有动画和内部状态函数，但缺少标准`set_xingbao_expression(...)`。机械臂、实体灯效和TTS执行器不属于当前UI/游戏项目：机械臂与灯效需硬件侧实现，TTS使用语音侧现有能力。
