# 星宝状态输入预留规范

本文档用于当前阶段的电脑端联调。旧的实物色块小游戏不再作为主线小游戏继续推进，相关代码只作为 legacy 原型和回归参考保留。

语音侧询问游戏规则、目标、提示、分数、进度时，优先使用 `game_command` 固定 intent 接口，详见 `docs/TO_VOICE_TEAM.md` 和 `examples/voice_bridge_example.py`。

游戏或视觉模块主动上报状态时，预留两个输入口：

- `mini_game_state`：未来新小游戏把局内状态交给星宝。
- `vision_state`：视觉检测模块把孩子状态、距离、姿态、桌面物体等检测结果交给星宝。

这两个输入都会先进入 `core/state_inputs.py` 做归一化，再交给 `XingbaoCoordinator` 输出统一的表情、屏幕文字、TTS 计划和 trace。这样即使现在没有连接板卡，也可以在电脑上提前验证协同链路。

## 新小游戏状态输入

推荐 JSON：

```json
{
  "type": "mini_game_state",
  "source": "new_mini_game",
  "payload": {
    "game_id": "shape_match",
    "state": "child_made_mistake",
    "confidence": 0.95,
    "progress": {
      "round": 2,
      "score": 10
    },
    "data": {
      "answer": "triangle"
    }
  }
}
```

当前预留状态：

| state | 作用 |
|---|---|
| `game_started` / `round_started` | 进入小游戏或新一轮 |
| `child_answered` | 孩子已经作答 |
| `child_succeeded` | 孩子成功完成一步 |
| `child_made_mistake` | 孩子答错或操作失误，需要鼓励 |
| `hint_requested` | 孩子请求提示 |
| `idle_timeout` | 孩子一段时间没有操作 |
| `game_finished` | 小游戏结束，可记录成长反馈 |

如果小游戏自己已经生成了要星宝说的话，可以传 `message`：

```json
{
  "type": "mini_game_state",
  "payload": {
    "game_id": "shape_match",
    "state": "child_succeeded",
    "message": "做得好，我们继续下一关。",
    "feedback": {
      "expression": "happy",
      "tts": true
    }
  }
}
```

## 视觉检测状态输入

推荐 JSON：

```json
{
  "type": "vision_state",
  "source": "vision",
  "payload": {
    "state": "face_too_close",
    "confidence": 0.9,
    "duration_seconds": 3,
    "zone": "center",
    "simulated": true
  }
}
```

当前预留状态：

| state | 作用 |
|---|---|
| `child_present` | 检测到孩子在座位上，只更新 UI，不主动说话 |
| `child_left_seat` | 孩子离开座位，只更新等待状态，不对空座位说话 |
| `child_returned` | 孩子回到座位，可以温和恢复互动 |
| `face_too_close` | 眼距提醒 |
| `posture_too_low` | 姿态过低，当前先复用眼距提醒 |
| `sitting_too_long` | 久坐休息提醒 |
| `drink_water_reminder_due` | 喝水提醒 |
| `camera_blocked` | 摄像头被遮挡或视觉不可用 |
| `object_detected` | 桌面检测到物体，只更新 UI，不绑定旧实物小游戏 |

## 电脑端调试命令

直接传 JSON：

```powershell
python main.py --coordinate-state-json '{"type":"vision_state","payload":{"state":"face_too_close","confidence":0.9,"simulated":true}}' --coordinate-apply
```

Windows 上更推荐放入文件，减少引号问题：

```powershell
python main.py --coordinate-state-file work/tmp/vision_state_face_close.json --coordinate-apply
```

如果要实际播放 TTS，再加：

```powershell
--expression-speak --local-tts-fallback
```

## 联调判断标准

一次状态输入至少要能看到：

- `plan.events[0]` 是原始 `mini_game_state` 或 `vision_state`。
- `plan.events[1]` 是归一化后的 `game_event`、`vision_event` 或 `xingbao_expression_request`。
- `trace` 中出现 `ui.expression`，说明主界面星宝形象有明确表情状态。
- 需要说话时 `trace` 中出现 `voice.speak` 且状态为 `planned` 或 `played`。
- 没有具体小游戏项目接入前，`mini_game_hub` 可以是 `unavailable`，但不能再默认打开旧实物小游戏。

## 后续接板卡时的边界

PC 侧仍然只输出高层状态，例如 `smile`、`thinking`、`caring`、`warm_breath`、`blue_breath`。不要让 LLM 或小游戏直接输出舵机角度、GPIO、PWM、串口原始命令。板卡接入后，只需要把这些高层状态映射到板卡自己的安全动作表。
