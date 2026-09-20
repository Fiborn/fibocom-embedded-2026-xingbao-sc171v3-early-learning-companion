# 游戏固定意图表 V0

本文档定义语音侧可以发送给触控小游戏的第一版固定 intent。游戏只处理这些固定 intent，不需要理解孩子自由文本。

## 设计原则

- 语音侧把孩子自然语言归类成固定 `intent`。
- 游戏侧只处理固定 `intent`。
- 游戏返回结构化 `game_response`。
- 未知 intent 必须返回错误，不要静默执行。
- 播报给孩子的 `message` 要短，一次只说一件事。

## 第一版 intent

| intent | 含义 | 孩子可能怎么说 | 游戏需要返回 |
| --- | --- | --- | --- |
| `get_rule` | 获取玩法规则 | 这个怎么玩？怎么玩呀？ | 当前游戏规则说明 |
| `get_goal` | 获取当前目标 | 现在要做什么？我要找什么？ | 当前要孩子完成的目标 |
| `get_hint` | 获取提示 | 我不会。提示一下。帮帮我。 | 一个简短提示 |
| `get_score` | 获取分数 | 我多少分了？我得了几分？ | 当前分数 |
| `get_progress` | 获取进度 | 我玩到哪了？还有几关？ | 当前关卡、轮次、剩余任务 |
| `repeat_prompt` | 重复当前题目 | 再说一次。刚才说什么？ | 当前题目或当前目标文本 |
| `restart_round` | 重开本轮 | 重新来。再来一次。 | 本轮重置后的状态 |
| `next_round` | 进入下一轮 | 下一关。下一个。 | 新一轮目标和状态 |
| `pause_game` | 暂停游戏 | 等一下。暂停。 | 暂停状态 |
| `exit_game` | 退出游戏 | 不玩了。换一个。退出。 | 退出状态或确认结果 |

## 返回示例

### get_rule

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_rule",
  "message": "先看目标形状，再点最像的那个。",
  "state": {
    "current_goal": "找到圆形"
  }
}
```

### get_goal

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_goal",
  "message": "现在请找到圆形。",
  "state": {
    "current_goal": "找到圆形"
  }
}
```

### get_hint

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_hint",
  "message": "先找最像圆形的那个。",
  "state": {
    "hint_count": 1
  }
}
```

### get_score

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_score",
  "message": "你现在有 20 分。",
  "state": {
    "score": 20
  }
}
```

### get_progress

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_progress",
  "message": "现在是第一关第二轮。",
  "state": {
    "level": 1,
    "round": 2,
    "remaining_rounds": 3
  }
}
```

### repeat_prompt

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "repeat_prompt",
  "message": "请找到圆形。",
  "state": {
    "current_goal": "找到圆形"
  }
}
```

### restart_round

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "restart_round",
  "message": "好，我们重新来这一轮。",
  "state": {
    "round": 1,
    "current_goal": "找到圆形"
  }
}
```

### next_round

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "next_round",
  "message": "好，准备进入下一轮。",
  "state": {
    "round": 2,
    "current_goal": "找到三角形"
  }
}
```

### pause_game

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "pause_game",
  "message": "好的，游戏先暂停一下。",
  "state": {
    "paused": true
  }
}
```

### exit_game

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "exit_game",
  "message": "好的，我们先退出小游戏。",
  "state": {
    "exited": true
  }
}
```

## 游戏侧需要确认

每个小游戏需要确认：

- 哪些 intent 已经支持。
- 哪些 intent 暂时不支持，原因是什么。
- 每个 intent 是否会改变游戏状态。
- 每个 intent 返回什么 `message`。
- 每个 intent 返回什么 `state` 字段。
- 是否需要新增游戏独有 intent。
