# 星宝处理中枢、主界面UI与小游戏通信规范V1.0

## 1.文档目的

本文档供处理中枢项目直接实现接口，统一以下链路：

1.小游戏产生文字→处理中枢→TTS播报。
2.处理中枢产生表情、动作、灯效→主界面UI与机器硬件分别执行。
3.孩子说“我要玩游戏”→ASR→处理中枢→结构化UI指令→主界面打开游戏。
4.孩子在游戏中说“我不会”→处理中枢识别固定intent→游戏返回提示→中枢TTS播报。
5.游戏答对、答错、完成→游戏事件→处理中枢→语音、表情、动作反馈。

## 2.当前代码真实状态

### 2.1小游戏当前如何“输出语音”

小游戏当前不输出音频，只产生文字。

入口位于`src/app.py`：

```python
def speak(self, text, page=None):
    self.message = text
    self.log(EventName.XINGBAO_SPEAK, page=page, payload={"text": text})
```

当前行为只有两个：

- 把文字保存到`self.message`，供游戏界面显示。
- 把文字写入JSONL日志，事件名为`xingbao_speak`。

当前没有：

- 没有调用TTS。
- 没有通过Socket、HTTP或WebSocket发送给处理中枢。
- 没有生成音频文件。
- 没有播放声音。

因此处理中枢需要新增“接收`speech_request`并执行TTS”的接口。

### 2.2游戏语音查询当前已有形式

`src/game_api.py`已有结构化接口：

```python
response = GameCommandAdapter(app).handle_command(command)
```

返回中的`message`是要交给TTS的核心文字：

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "color_game",
  "intent": "get_hint",
  "message": "提示：找到蓝色能量",
  "state": {},
  "feedback": {
    "screen_expression": "curious",
    "arm_action": "stay_still",
    "led_mode": "yellow_blink"
  }
}
```

`message`不是音频，也不是语音流，它是UTF-8文字。

### 2.3主界面表情当前状态

主界面`desktop.py`当前通过内部函数切换动画：

```python
desktop.set_xingbao_state("thinking", seconds=4.0)
```

当前内部动画状态包括：

```text
idle
thinking
yawn
happy
celebrate
alert
blink
```

目前这些状态由点击、空闲计时、积分奖励和视觉提醒触发。主界面尚未监听处理中枢输出的`screen_expression`。

### 2.4打开游戏当前状态

目前桌面通过以下方式打开游戏中心：

- 点击“小抽屉→一起玩”。
- 按`G`、回车或空格。
- 内部调用`DesktopLauncher.open_game()`。

目前没有“语音打开游戏”的跨进程接口。

## 3.总体架构

```text
孩子说话
  ↓
ASR
  ↓ child_utterance
处理中枢
  ├─意图识别
  ├─TTS
  ├─动作/表情决策
  └─UI指令分发
  ↓ assistant_output或game_command
主界面UI/小游戏
  ↓ speech_request或game_event
处理中枢
```

职责必须分开：

- ASR只负责语音转文字。
- 处理中枢负责理解文字、选择intent、调用TTS、生成表情动作和UI指令。
- 主界面UI只执行结构化UI指令和屏幕表情，不理解孩子自由说话。
- 小游戏只处理固定`game_command`，不接大模型，不调用TTS。
- 硬件层只执行白名单高层动作，不接收模型生成的舵机角度、PWM或GPIO指令。

## 4.推荐传输方式

### 4.1同一Python进程

优先使用Python函数和线程安全队列，不需要网络协议。

### 4.2独立进程

推荐使用本机TCP长连接：

```text
127.0.0.1:8765
UTF-8
NDJSON
每行一个完整JSON对象
```

处理中枢作为Server，主界面UI作为Client。这样不需要额外Web框架，Python标准库即可实现。

所有业务JSON结构与传输方式解耦。以后换成WebSocket或UnixSocket时，payload不变。

## 5.统一消息信封

所有跨进程消息统一使用：

```json
{
  "version": "1.0",
  "message_id": "uuid",
  "type": "speech_request",
  "source": "game_ui",
  "target": "central_controller",
  "timestamp": "2026-07-03T12:00:00.000+08:00",
  "reply_to": null,
  "payload": {}
}
```

字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `version` | 是 | 当前固定`1.0` |
| `message_id` | 是 | UUID，用于去重和应答 |
| `type` | 是 | 消息类型 |
| `source` | 是 | 发送模块 |
| `target` | 是 | 接收模块 |
| `timestamp` | 是 | ISO8601时间 |
| `reply_to` | 否 | 回复哪条消息 |
| `payload` | 是 | 业务数据 |

## 6.小游戏文字→处理中枢TTS

### 6.1消息类型

```text
speech_request
```

### 6.2标准格式

```json
{
  "version": "1.0",
  "message_id": "2f8b...",
  "type": "speech_request",
  "source": "game_ui",
  "target": "central_controller",
  "timestamp": "2026-07-03T12:00:00.000+08:00",
  "reply_to": null,
  "payload": {
    "text": "请找到蓝色",
    "scene": "game",
    "game_id": "color_game",
    "page": "game_running",
    "priority": "normal",
    "interrupt": false,
    "voice": "child_friendly",
    "request_tts": true
  }
}
```

处理中枢收到后：

1.检查`message_id`，避免重复播报。
2.若`interrupt=true`，停止当前TTS。
3.将`payload.text`交给TTS。
4.播放完成后返回`speech_status`。

### 6.3TTS状态返回

```json
{
  "version": "1.0",
  "message_id": "status-uuid",
  "type": "speech_status",
  "source": "central_controller",
  "target": "game_ui",
  "timestamp": "2026-07-03T12:00:01.000+08:00",
  "reply_to": "2f8b...",
  "payload": {
    "status": "finished",
    "error": null
  }
}
```

`status`取值：

```text
queued
playing
finished
interrupted
failed
```

## 7.孩子说话→处理中枢

ASR向处理中枢发送：

```json
{
  "version": "1.0",
  "message_id": "asr-uuid",
  "type": "child_utterance",
  "source": "asr",
  "target": "central_controller",
  "timestamp": "2026-07-03T12:00:00.000+08:00",
  "reply_to": null,
  "payload": {
    "text": "我想玩找颜色",
    "confidence": 0.93,
    "is_final": true,
    "scene": "desktop",
    "current_game_id": null
  }
}
```

处理中枢不能把这句话原样发给UI。处理中枢必须转成结构化`assistant_output`。

## 8.处理中枢→主界面统一输出

### 8.1消息类型

```text
assistant_output
```

### 8.2完整格式

```json
{
  "version": "1.0",
  "message_id": "assistant-uuid",
  "type": "assistant_output",
  "source": "central_controller",
  "target": "desktop_ui",
  "timestamp": "2026-07-03T12:00:00.200+08:00",
  "reply_to": "asr-uuid",
  "payload": {
    "speech": {
      "text": "好呀，我们一起玩找颜色！",
      "request_tts": true,
      "interrupt": false
    },
    "screen_expression": {
      "name": "smile",
      "duration_ms": 4000
    },
    "arm_action": {
      "name": "wave_hand",
      "duration_ms": 1800
    },
    "led": {
      "mode": "warm_breath",
      "duration_ms": 4000
    },
    "ui_command": {
      "name": "start_game",
      "params": {
        "game_id": "color_game",
        "difficulty": 1
      }
    }
  }
}
```

字段都允许为`null`，但不允许省略`payload`。

## 9.表情与动作调用规范

### 9.1屏幕表情白名单

```text
neutral
smile
thinking
curious
sad
surprised
sleepy
```

主界面必须执行白名单校验，未知值降级为`neutral`。

### 9.2外部表情→主界面动画映射

| 中枢输出 | 主界面动画 | 当前资源情况 |
| --- | --- | --- |
| `neutral` | `idle` | 已有4帧 |
| `smile` | `happy`或`celebrate` | 已有庆祝帧，可用 |
| `thinking` | `thinking` | 已有4帧 |
| `curious` | `thinking` | 暂时复用思考动画 |
| `sad` | `thinking` | 暂时使用温和失落帧，不做哭泣 |
| `surprised` | `celebrate` | 已有4帧 |
| `sleepy` | `yawn` | 已有4帧 |

主界面收到后执行：

```python
desktop.set_xingbao_state(mapped_state, seconds=duration_ms / 1000.0)
```

必须在Pygame主线程执行。网络接收线程只能把消息放入队列，不能直接改Surface或动画状态。

### 9.3机械动作白名单

```text
stay_still
wave_hand
nod
shake_head
point_left
point_right
small_dance
```

`arm_action`由硬件适配层消费，不由主界面直接转换成舵机角度。

### 9.4灯效白名单

```text
off
blue_breath
warm_breath
yellow_blink
rainbow
red_flash
```

### 9.5“emoji”字段要求

处理中枢不要输出Unicode表情符号，例如`😊`、`😴`。必须输出稳定枚举名：

```json
{"screen_expression":{"name":"smile","duration_ms":4000}}
```

如果模型原始输出叫`emoji`，处理中枢内部要先归一化：

```text
😊→smile
🤔→thinking
😮→surprised
😴→sleepy
😢→sad
```

UI只接收归一化后的`screen_expression.name`。

## 10.语音打开游戏规范

### 10.1禁止做法

主界面不要检测“我要玩游戏”“打开找颜色”等自然语言关键词。自然语言理解属于处理中枢。

### 10.2正确链路

```text
孩子说“我想玩找颜色”
→ASR输出文字
→处理中枢识别意图
→处理中枢输出ui_command
→主界面执行start_game
```

### 10.3UI命令白名单

```text
open_game_center
start_game
exit_game
open_drawing
open_gallery
start_focus
open_memory
go_home
```

### 10.4打开游戏中心

```json
{
  "name": "open_game_center",
  "params": {}
}
```

主界面执行现有`DesktopLauncher.open_game()`逻辑。

### 10.5直接开始指定游戏

```json
{
  "name": "start_game",
  "params": {
    "game_id": "color_game",
    "difficulty": 1
  }
}
```

`game_id`白名单：

```text
color_game
shape_game
memory_game
counting_game
english_game
skill_game
```

`difficulty`只允许`1`、`2`、`3`。

如果孩子只说“我要玩游戏”，处理中枢发送`open_game_center`，让孩子触控选择。

如果孩子明确说“我要玩找颜色”，处理中枢可以发送`start_game`。

## 11.游戏中的语音命令

孩子在游戏中说话时，处理中枢将自然语言映射成已有固定intent：

| 孩子可能说 | intent |
| --- | --- |
| 怎么玩 | `get_rule` |
| 要做什么 | `get_goal` |
| 我不会、提示一下 | `get_hint` |
| 我有多少分 | `get_score` |
| 还有几题 | `get_progress` |
| 再说一次 | `repeat_prompt` |
| 重新来 | `restart_round` |
| 下一题 | `next_round` |
| 暂停 | `pause_game` |
| 不玩了 | `exit_game` |

处理中枢向游戏发送已有`game_command`：

```json
{
  "type": "game_command",
  "game_id": "color_game",
  "intent": "get_hint",
  "user_text": "我不会",
  "context": {
    "source": "voice",
    "asr_confidence": 0.91,
    "child_age_group": "preschool"
  }
}
```

游戏返回`game_response`后，处理中枢执行：

1.将`response.message`送入TTS。
2.将`response.feedback.screen_expression`发送给主界面。
3.将`response.feedback.arm_action`发送给硬件适配层。
4.将`response.feedback.led_mode`发送给灯效适配层。

## 12.游戏主动事件

游戏可发送：

```text
game_started
round_started
answer_correct
answer_wrong
hint_used
round_completed
game_completed
idle_timeout
game_paused
game_exited
```

示例：

```json
{
  "type": "game_event",
  "game_id": "shape_game",
  "event": "answer_correct",
  "message": "孩子找到了圆形",
  "state": {},
  "feedback": {
    "screen_expression": "smile",
    "arm_action": "nod",
    "led_mode": "warm_breath"
  }
}
```

处理中枢收到事件后可以补充儿童话术，但不能修改游戏分数和状态。

## 13.UI执行结果与错误

每条`ui_command`都要返回：

```json
{
  "version": "1.0",
  "message_id": "ack-uuid",
  "type": "command_result",
  "source": "desktop_ui",
  "target": "central_controller",
  "timestamp": "2026-07-03T12:00:00.500+08:00",
  "reply_to": "assistant-uuid",
  "payload": {
    "ok": true,
    "command": "start_game",
    "error": null
  }
}
```

错误码：

```text
unknown_command
invalid_params
invalid_state
not_available
internal_error
```

## 14.优先级与冲突规则

1.安全提醒优先级最高：距离太近、喝水提醒可覆盖普通表情。
2.正在播放安全提醒时，普通`smile`不能立即覆盖`alert`。
3.新`assistant_output`带`interrupt=true`时，可以中断普通TTS。
4.同一`message_id`只能执行一次。
5.UI动画超时后回到`idle`。
6.未知表情降级`neutral`，未知动作降级`stay_still`，未知灯效降级`off`。

## 15.处理中枢必须实现的接口清单

### 输入

- 接收`child_utterance`。
- 接收`speech_request`。
- 接收`game_response`。
- 接收`game_event`。
- 接收`command_result`。

### 输出

- 输出`assistant_output`。
- 输出`game_command`。
- 输出`speech_status`。

### 内部能力

- ASR文字→固定意图。
- `speech.text`→TTS播放。
- emoji或模型表情→表情白名单归一化。
- 模型动作→动作白名单归一化。
- 自然语言“玩游戏”→结构化`ui_command`。
- 消息去重、超时、断线重连和错误日志。

## 16.第一阶段最小联调闭环

### 闭环A：游戏提示

```text
孩子说“我不会”
→ASR child_utterance
→中枢get_hint
→游戏game_response.message
→中枢TTS
→主界面thinking/curious表情
```

### 闭环B：语音打开游戏

```text
孩子说“我要玩游戏”
→中枢assistant_output
→speech.text="好呀，我们一起玩"
→ui_command=open_game_center
→主界面打开游戏中心
```

### 闭环C：表情动作

```text
中枢输出smile+wave_hand+warm_breath
→UI播放smile对应动画
→硬件层执行wave_hand
→灯效层执行warm_breath
```

三条闭环全部通过后，再增加主动`game_event`、打断播报和独立进程通信。

## 17.一句话结论

小游戏输出的是UTF-8文字和结构化JSON，不是音频；处理中枢负责TTS。模型输出必须由处理中枢整理成`assistant_output`，主界面只执行白名单表情和结构化`ui_command`，绝不能依靠解析自然语言来开游戏或控制机器。
