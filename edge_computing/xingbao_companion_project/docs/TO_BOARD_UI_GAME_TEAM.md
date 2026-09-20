# 发给板卡/UI/游戏同学的接口需求

这份文档用于把星宝已经跑通的语音能力接到真实板卡软件界面、主界面星宝形象、机械臂/灯效和小游戏中。

语音链路现在已经可用：待机静默、唤醒、长轮次对话、ASR、LLM、TTS 都已经跑通。接下来需要对面提供几个可调用接口，让星宝语音调度层能把“打开游戏、播放游戏提示、更新表情、执行动作/灯效”落到真实界面和板卡上。

## 总原则

- 语音侧负责识别孩子说了什么。
- 游戏侧负责游戏规则、分数、关卡、状态。
- UI 侧负责主界面星宝表情和屏幕文字。
- 板卡/机械臂侧负责高层动作和灯效。
- 星宝核心只传高层名称，不传舵机角度、PWM、GPIO、串口原始命令。
- 所有回调尽量在 UI 主线程执行；如果不是 UI 主线程，请对面提供线程投递方法。

## 1. 游戏界面启动器

### 星宝需要什么

当孩子说“星宝我要玩游戏啦”时，星宝会识别为：

```json
{
  "intent": "open_tool",
  "target": "mini_game_hub"
}
```

对面需要提供一个打开游戏界面的函数或消息接口。

### 推荐 Python 函数

```python
def open_game(game_id: str = "shape_game", *, source: str = "voice", context: dict | None = None) -> dict:
    ...
```

### 输入示例

```python
open_game(
    "shape_game",
    source="voice",
    context={"user_text": "星宝我要玩游戏啦"}
)
```

### 返回示例

```json
{
  "ok": true,
  "game_id": "shape_game",
  "page": "game",
  "message": "图形小游戏已打开",
  "state": {
    "loaded": true
  }
}
```

### 需要支持的游戏 ID

第一阶段至少支持一个默认小游戏，推荐先用：

```text
shape_game
```

后续可扩展：

```text
color_game
shape_game
memory_game
counting_game
english_game
skill_game
```

### 如果游戏打不开

请返回：

```json
{
  "ok": false,
  "game_id": "shape_game",
  "message": "小游戏还没有准备好",
  "error": {
    "code": "not_ready",
    "detail": "游戏页面未加载"
  }
}
```

## 2. 游戏命令接口

### 星宝需要什么

孩子在游戏里说“我不会”“提示一下”“怎么玩”，语音侧会把这些话变成固定 intent，然后调用游戏。

对面游戏需要提供：

```python
def handle_command(command: dict) -> dict:
    ...
```

或者挂到 app 上：

```python
app.handle_game_command(command)
```

或：

```python
app.game.handle_command(command)
```

星宝当前代码会优先尝试这些位置。

### 输入格式：game_command

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

### 固定 intent

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

### 输出格式：game_response

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_hint",
  "message": "先找最像圆形的那个。",
  "state": {
    "round": 1,
    "score": 20,
    "current_goal": "找到圆形"
  },
  "feedback": {
    "screen_expression": "thinking",
    "led_mode": "blue_breath",
    "arm_action": "stay_still"
  }
}
```

### 重点

- `message` 会交给星宝 TTS 播放。
- `feedback.screen_expression` 会交给主界面星宝表情。
- `feedback.led_mode` 会交给灯效。
- `feedback.arm_action` 会交给机械臂/动作模块。
- 游戏不要自己直接调用 TTS，除非双方后续明确约定。

## 3. 主界面星宝表情适配器

### 星宝需要什么

当模型、游戏或视觉模块输出表情时，需要主界面星宝形象变化。

对面需要提供一个 UI 表情接口。

### 推荐 Python 函数

```python
def set_xingbao_expression(
    expression: str,
    *,
    screen_text: str = "",
    source: str = "voice",
    context: dict | None = None,
) -> dict:
    ...
```

### 输入示例

```python
set_xingbao_expression(
    "thinking",
    screen_text="先找最像圆形的那个。",
    source="game",
    context={"game_id": "shape_game", "intent": "get_hint"}
)
```

### 返回示例

```json
{
  "ok": true,
  "expression": "thinking",
  "rendered": true
}
```

### 表情白名单

```text
neutral
smile
thinking
curious
sad
surprised
sleepy
caring
encouraging
happy
```

### 如果某个表情没有资源

请返回可替代表情：

```json
{
  "ok": true,
  "expression": "encouraging",
  "rendered": true,
  "fallback_from": "happy"
}
```

## 4. 板卡动作/灯效适配器

### 星宝需要什么

模型或游戏会输出高层动作和灯效，比如：

```json
{
  "arm_action": "nod",
  "led_mode": "warm_breath"
}
```

对面需要提供一个安全动作接口。

### 推荐 Python 函数

```python
def apply_board_feedback(
    *,
    arm_action: str = "stay_still",
    led_mode: str = "off",
    source: str = "voice",
    context: dict | None = None,
) -> dict:
    ...
```

### 输入示例

```python
apply_board_feedback(
    arm_action="nod",
    led_mode="warm_breath",
    source="game",
    context={"game_id": "shape_game", "intent": "get_hint"}
)
```

### 返回示例

```json
{
  "ok": true,
  "arm_action": "nod",
  "led_mode": "warm_breath",
  "applied": true
}
```

### 机械臂动作白名单

```text
stay_still
wave_hand
nod
shake_head
point_left
point_right
small_dance
```

### 灯效白名单

```text
off
blue_breath
warm_breath
yellow_blink
rainbow
red_flash
```

### 安全要求

- 不接收舵机角度。
- 不接收 PWM 数值。
- 不接收 GPIO 原始命令。
- 不接收串口原始命令。
- 如果动作不能做，请降级到 `stay_still`，并返回原因。

降级返回示例：

```json
{
  "ok": true,
  "arm_action": "stay_still",
  "led_mode": "warm_breath",
  "applied": true,
  "fallback_from": "small_dance",
  "reason": "动作幅度过大，儿童桌面场景暂不执行"
}
```

## 5. TTS 播放入口

### 当前情况

星宝已有 TTS 能力。游戏不需要直接播 TTS，只需要返回 `message`。

### 如果板卡软件有自己的 TTS 队列

请提供：

```python
def speak_text(
    text: str,
    *,
    source: str = "voice",
    interrupt: bool = False,
    context: dict | None = None,
) -> dict:
    ...
```

输入示例：

```python
speak_text(
    "先找最像圆形的那个。",
    source="game",
    context={"game_id": "shape_game", "intent": "get_hint"}
)
```

返回示例：

```json
{
  "ok": true,
  "queued": true,
  "playing": false
}
```

如果没有单独 TTS 队列，星宝会继续用现有 TTS 播放函数。

## 6. 推荐对接对象

如果对面愿意直接提供一个总适配器，推荐长这样：

```python
class XingbaoBoardRuntime:
    def open_game(self, game_id: str = "shape_game", *, source: str = "voice", context: dict | None = None) -> dict:
        ...

    def handle_game_command(self, command: dict) -> dict:
        ...

    def set_xingbao_expression(self, expression: str, *, screen_text: str = "", source: str = "voice", context: dict | None = None) -> dict:
        ...

    def apply_board_feedback(self, *, arm_action: str = "stay_still", led_mode: str = "off", source: str = "voice", context: dict | None = None) -> dict:
        ...

    def speak_text(self, text: str, *, source: str = "voice", interrupt: bool = False, context: dict | None = None) -> dict:
        ...
```

如果 UI 和语音是两个进程，这几个函数也可以改成本地 Socket 或 WebSocket 消息，JSON 结构保持不变。

## 7. 对面需要回传给我们的内容

请对面最终给我们以下信息：

1. 打开游戏界面的函数名、参数、返回值。
2. 默认打开哪个游戏 ID。
3. 游戏是否提供 `handle_command(command)`。
4. 主界面星宝表情函数名、支持的表情列表。
5. 机械臂/灯效函数名、支持的动作和灯效列表。
6. TTS 是否由星宝现有 TTS 播放，还是板卡 UI 有自己的 TTS 队列。
7. 这些函数必须在哪个线程调用，是否需要 UI 主线程投递。

## 8. 第一条联调目标

先不要一次接所有功能。第一条只跑：

```text
孩子说：星宝我要玩游戏
-> 星宝识别 open_tool / mini_game_hub
-> 调 open_game("shape_game")
-> UI 打开游戏界面
-> 星宝说：好呀，我们开始小游戏
-> UI 表情 smile
-> 灯效 warm_breath
```

第二条再跑：

```text
孩子在游戏里说：我不会
-> 语音识别 get_hint
-> 调 handle_game_command(command)
-> 游戏返回 message
-> TTS 播放 message
-> UI 表情 thinking
-> 灯效 blue_breath
-> 机械臂 stay_still
```
