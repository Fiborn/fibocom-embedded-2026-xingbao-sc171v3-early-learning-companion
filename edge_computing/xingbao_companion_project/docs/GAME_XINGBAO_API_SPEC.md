# 星宝与触控小游戏接口规范

本文档定义星宝侧、语音侧和触控小游戏之间的数据格式。当前仓库已经提供 Python 适配器：

```python
from src.game_api import GameCommandAdapter

response = GameCommandAdapter(app).handle_command(command)
```

语音侧示例见 `examples/voice_bridge_example.py`，可转发说明见 `docs/TO_VOICE_TEAM.md`。

## 分工边界

- 语音侧负责 ASR 和固定 intent 识别。
- 游戏侧负责规则、状态、分数、关卡和进度。
- 星宝侧负责把游戏返回组织成适合孩子听的播报和主界面表达。
- 游戏不接大模型，不理解孩子自由文本。
- 星宝不直接修改游戏分数、轮次或正确答案。
- 任意反馈只能使用高层白名单名称，不得输出舵机角度、PWM、GPIO 或串口原始命令。

## 固定游戏 ID

```text
color_game
shape_game
memory_game
counting_game
english_game
skill_game
```

## 固定 intent

```text
get_rule
get_goal
get_hint
get_score
get_progress
get_stars
get_remaining
get_round
get_current_game
get_status
get_level
get_energy
get_correct
get_errors
get_attempts
repeat_prompt
restart_round
next_round
pause_game
exit_game
```

## 星宝发给游戏：game_command

```json
{
  "type": "game_command",
  "game_id": "shape_game",
  "intent": "get_hint",
  "user_text": "我不会",
  "context": {
    "source": "voice",
    "asr_confidence": null,
    "child_age_group": "preschool"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | string | 是 | 固定为 `game_command` |
| `game_id` | string | 是 | 固定游戏 ID |
| `intent` | string | 是 | 固定 intent |
| `user_text` | string | 否 | 孩子原始 ASR 文本，仅用于记录 |
| `context` | object | 否 | 来源、置信度、年龄段等上下文 |

## 游戏返回星宝：game_response

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_hint",
  "message": "先找最像圆形的那个。",
  "state": {
    "level": 1,
    "round": 1,
    "total_rounds": 5,
    "remaining_rounds": 4,
    "score": 20,
    "stars": 3,
    "total_stars": 8,
    "energy": 5,
    "energy_max": 5,
    "success_count": 3,
    "error_count": 1,
    "attempt_count": 4,
    "current_goal": "找到圆形",
    "last_result": null
  },
  "feedback": {
    "screen_expression": "thinking",
    "led_mode": "blue_breath",
    "arm_action": "stay_still"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | string | 是 | 固定为 `game_response` |
| `ok` | boolean | 是 | 命令是否处理成功 |
| `game_id` | string | 是 | 固定游戏 ID |
| `intent` | string | 是 | 对应请求 intent |
| `message` | string | 是 | 给星宝/TTS 使用的儿童友好短句 |
| `state` | object | 是 | 当前游戏状态，由游戏侧维护 |
| `feedback` | object | 否 | 建议的表情、灯效、动作，高层白名单名称 |
| `error` | object | 否 | `ok=false` 时说明错误原因 |

### 状态查询 intent 说明

| `intent` | 用户可能说法 | 游戏应返回 |
| --- | --- | --- |
| `get_stars` | 目前几颗星、我有多少星 | 当前星星数量 |
| `get_score` | 多少分、现在分数 | 当前分数 |
| `get_progress` | 进度怎么样、做到哪里 | 当前进度概览 |
| `get_remaining` | 还剩几题、还有几轮 | 剩余题数或轮数 |
| `get_round` | 现在第几关、第几题 | 当前轮次、关卡或题号 |
| `get_current_game` | 现在什么游戏、玩的是啥 | 当前小游戏名称 |
| `get_status` | 我现在怎么样、游戏状态 | 综合状态短句 |
| `get_level` | 现在几级、当前等级 | 当前等级 |
| `get_energy` | 还有多少能量、体力多少 | 当前能量和满能量 |
| `get_correct` | 答对几个、做对几题 | 正确次数 |
| `get_errors` | 错了几个、失败几次 | 错误次数 |
| `get_attempts` | 试了几次、点了几次 | 尝试次数 |

## 错误返回

```json
{
  "type": "game_response",
  "ok": false,
  "game_id": "shape_game",
  "intent": "next_round",
  "message": "我们先完成这一题，再进入下一关。",
  "state": {},
  "feedback": {
    "screen_expression": "thinking",
    "led_mode": "blue_breath",
    "arm_action": "stay_still"
  },
  "error": {
    "code": "not_available",
    "detail": "当前题目还没有完成"
  }
}
```

建议错误码：

| code | 说明 |
| --- | --- |
| `unknown_intent` | 游戏不支持该 intent |
| `unknown_game` | 游戏 ID 未登记 |
| `not_available` | 当前状态不能执行 |
| `invalid_state` | 游戏状态异常 |
| `missing_data` | 缺少必要数据 |
| `internal_error` | 游戏内部错误 |

## feedback 白名单

表情：

```json
["neutral", "smile", "thinking", "curious", "sad", "surprised", "sleepy", "caring", "encouraging", "happy"]
```

灯效：

```json
["off", "blue_breath", "warm_breath", "yellow_blink", "rainbow", "red_flash"]
```

高层动作：

```json
["stay_still", "wave_hand", "nod", "shake_head", "point_left", "point_right", "small_dance", "bow"]
```

这些是高层动作名，不是硬件控制命令。PC 侧和 LLM 都不能输出底层硬件命令。

## 最小闭环

第一阶段先跑通：

```text
孩子说“我不会”
-> 语音侧识别为 get_hint
-> GameCommandAdapter.handle_command(command)
-> 游戏返回 game_response.message
-> 星宝 TTS 播报，并更新主界面表情 trace
```

电脑端验证命令：

```powershell
python main.py --game-command-file docs/examples/game_command_get_hint.json --coordinate-apply
```

期望看到：

- `game_response.intent = get_hint`
- `plan.intent.intent = game_response`
- `plan.expression_output.intent = get_hint`
- `trace[0].type = ui.expression`
- `trace[1].type = voice.speak`
