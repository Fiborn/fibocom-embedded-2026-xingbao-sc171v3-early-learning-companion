# 星宝模块状态与游戏命令回放

## 目的

小游戏、触控、视觉等模块不应直接调用 TTS，也不应直接修改主界面星宝表情。它们只提交固定命令或结构化状态，由星宝核心统一转换成：

- `game_response`
- `expression_output`
- `trace`
- 可选 TTS 播放
- 可选主界面动作状态

这样游戏中星宝说话、主界面表情变化、后续板卡高层状态，都能走同一条协同链路。

## 三类入口

| 入口 | 使用场景 | 推荐调用 |
| --- | --- | --- |
| `game_command` | 语音侧把孩子的话识别为固定 intent 后询问游戏 | `GameCommandAdapter(app).handle_command(command)` |
| `mini_game_state` | 游戏主动上报局内状态或结果 | `python main.py --coordinate-state-file ...` |
| `vision_state` | 视觉检测上报孩子状态或健康提醒 | `python main.py --coordinate-state-file ...` |

## 回放语音到游戏最小闭环

直接用文件回放：

```powershell
python main.py --game-command-file docs/examples/game_command_get_hint.json --coordinate-apply
```

等价 JSON：

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

期望输出：

- `game_response.ok = true`
- `game_response.intent = get_hint`
- `game_response.message` 可以直接给 TTS
- `plan.intent.intent = game_response`
- `plan.expression_output.intent = get_hint`
- `trace[0].type = ui.expression`
- `trace[1].type = voice.speak`

## 回放新小游戏状态

```powershell
python main.py --coordinate-state-file docs/examples/mini_game_state_child_made_mistake.json --coordinate-apply
```

期望输出：

- `plan.intent.intent = mini_game_state`
- `plan.intent.reason = state_input:game_event`
- `plan.expression_output.intent = encourage_retry`
- `plan.events[0].type = mini_game_state`
- `plan.events[1].type = game_event`

## 回放视觉检测状态

```powershell
python main.py --coordinate-state-file docs/examples/vision_state_face_too_close.json --coordinate-apply
```

期望输出：

- `plan.intent.intent = vision_state`
- `plan.intent.reason = state_input:vision_event`
- `plan.expression_output.intent = eye_distance`
- `plan.events[0].type = vision_state`
- `plan.events[1].type = vision_event`

## TTS 调试

默认只规划 TTS，不实际播放。要实际调用 TTS：

```powershell
python main.py --game-command-file docs/examples/game_command_get_hint.json --coordinate-apply --expression-speak --local-tts-fallback
```

## Legacy 说明

旧的色块小游戏相关命令和文档只作为 legacy 原型保留，不再作为当前小游戏主线：

```powershell
python main.py --coordinate-color-block-command "红色放星光线" --coordinate-apply
```

除非明确要回看旧原型，否则新的小游戏联调不要使用这个入口。
