# 三个触控游戏状态模板

本文档是给游戏侧填写的状态模板。星宝侧不替游戏猜内部字段，游戏侧需要根据实际实现补全。

## 填写要求

每个游戏都需要提供：

- `game_id`
- `rule`
- `current_goal`
- `score`
- `level`
- `round`
- `last_result`
- 当前可交互对象
- 当前正确目标
- 支持的 intents

字段名可以微调，但需要和星宝侧最终接口对齐。

## 颜色游戏模板

```json
{
  "game_id": "color_game",
  "name": "颜色游戏",
  "rule": "",
  "current_goal": "",
  "target_color": "",
  "available_colors": [],
  "selected_color": null,
  "score": 0,
  "level": 1,
  "round": 1,
  "remaining_rounds": null,
  "last_result": null,
  "hint_count": 0,
  "paused": false,
  "supported_intents": [
    "get_rule",
    "get_goal",
    "get_hint",
    "get_score",
    "get_progress",
    "repeat_prompt",
    "restart_round",
    "next_round",
    "pause_game",
    "exit_game"
  ]
}
```

游戏侧需要回答：

- 正确颜色字段叫什么？
- 可选颜色从哪里拿？
- 孩子当前选择怎么表示？
- 答对/答错事件怎么触发？
- 提示是固定文案还是根据当前目标生成？

## 图形游戏模板

```json
{
  "game_id": "shape_game",
  "name": "图形游戏",
  "rule": "",
  "current_goal": "",
  "target_shape": "",
  "available_shapes": [],
  "selected_shape": null,
  "score": 0,
  "level": 1,
  "round": 1,
  "remaining_rounds": null,
  "last_result": null,
  "hint_count": 0,
  "paused": false,
  "supported_intents": [
    "get_rule",
    "get_goal",
    "get_hint",
    "get_score",
    "get_progress",
    "repeat_prompt",
    "restart_round",
    "next_round",
    "pause_game",
    "exit_game"
  ]
}
```

游戏侧需要回答：

- 图形 ID 使用中文、英文还是内部编号？
- 目标图形是否可能同时包含颜色和形状？
- 孩子选错时是否需要返回正确答案？
- 提示是否需要指出屏幕区域？

## 记忆游戏模板

```json
{
  "game_id": "memory_game",
  "name": "记忆游戏",
  "rule": "",
  "current_goal": "",
  "cards_total": 0,
  "flipped_cards": [],
  "matched_pairs": 0,
  "remaining_pairs": 0,
  "last_flipped_card": null,
  "score": 0,
  "level": 1,
  "round": 1,
  "remaining_rounds": null,
  "last_result": null,
  "hint_count": 0,
  "paused": false,
  "supported_intents": [
    "get_rule",
    "get_goal",
    "get_hint",
    "get_score",
    "get_progress",
    "repeat_prompt",
    "restart_round",
    "next_round",
    "pause_game",
    "exit_game"
  ]
}
```

游戏侧需要回答：

- 卡片如何编号？
- 翻开的卡片结构是什么？
- 配对成功/失败怎么表示？
- 能不能给提示？提示到什么程度？
- 记忆游戏是否允许直接进入下一轮？

## 游戏事件模板

每个游戏还需要说明会主动发哪些事件。

```json
{
  "type": "game_event",
  "game_id": "color_game",
  "event": "answer_correct",
  "message": "孩子选对了红色",
  "state": {}
}
```

建议至少支持：

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

如果某个游戏不支持某些事件，请说明原因。

