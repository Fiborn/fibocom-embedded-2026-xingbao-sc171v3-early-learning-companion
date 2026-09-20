# 给游戏同学的任务说明

这份说明可以直接发给负责颜色、图形、记忆三个触控游戏的同学。

## 背景

我们现在要做的是星宝和触控游戏的协同。星宝负责听孩子说话、理解孩子想问什么、把游戏结果用儿童友好的语言说出来。游戏负责自己的规则、状态、分数和进度。

你这边不需要接大模型，也不需要理解孩子自由说话。

星宝会把孩子的话转成固定 `intent`，再调用你的游戏接口。你只需要处理这些固定 `intent`，然后返回结构化数据。

## 你需要实现什么

每个游戏提供一个命令处理函数。

如果是 Python：

```python
def handle_command(command: dict) -> dict:
    ...
```

如果是 JavaScript：

```js
function handleCommand(command) {
  return response
}
```

输入示例：

```json
{
  "type": "game_command",
  "game_id": "color_game",
  "intent": "get_hint",
  "user_text": "我不会",
  "context": {
    "source": "voice"
  }
}
```

输出示例：

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "color_game",
  "intent": "get_hint",
  "message": "请找一个红色方块",
  "state": {
    "level": 1,
    "round": 1,
    "score": 20,
    "current_goal": "找红色方块"
  }
}
```

## 第一版需要支持的 intent

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

如果某个游戏暂时不支持某个 intent，请返回：

```json
{
  "type": "game_response",
  "ok": false,
  "game_id": "color_game",
  "intent": "next_round",
  "message": "当前还不能进入下一关",
  "error": {
    "code": "not_available",
    "detail": "当前题目还没有完成"
  },
  "state": {}
}
```

不要静默失败。

## 第一版最小闭环

我们先跑通这一条：

```text
孩子说“我不会”
→ 星宝识别为 get_hint
→ 游戏返回当前提示
→ 星宝播报提示
```

只要颜色、图形、记忆三个游戏都能跑通这条，就说明协同模式成立了。

## 你需要补充给我们的内容

请你基于三个游戏分别补充：

1. 每个游戏有哪些状态字段。
2. 每个 intent 怎么处理。
3. 每个 intent 会不会改变游戏状态。
4. 每个 intent 返回什么 `message`。
5. 哪些 intent 当前不能支持。
6. 游戏会主动发哪些事件。
7. 每个游戏推荐使用什么表情、光效、动作反馈。

状态模板请看：

```text
docs/GAME_STATE_TEMPLATE.md
```

接口规范请看：

```text
docs/GAME_XINGBAO_API_SPEC.md
```

动作和表情交付说明请看：

```text
docs/ACTION_EXPRESSION_HANDOFF.md
```

动作、表情和灯效的可行性回填模板请看：

```text
docs/ACTION_EXPRESSION_FEASIBILITY_TEMPLATE.md
```

## 关于机械臂和表情

你还需要评估星宝当前动作、表情、光效哪些能实现。

请返回一份：

```text
ACTION_EXPRESSION_FEASIBILITY.md
```

里面说明：

- 哪些机械臂动作能做。
- 哪些机械臂动作不能做。
- 哪些动作有安全风险。
- 哪些动作建议用屏幕表情或光效替代。
- 每个星宝表情对应哪个资源或动画。
- 是否建议新增或删除动作/表情/光效。

注意：星宝不会给你发舵机角度、PWM、GPIO 或原始串口指令，只会发白名单里的高层动作名。

## 最重要的分工

```text
游戏管规则和状态。
星宝管理解和表达。
```

游戏不用接大模型，星宝也不会直接改游戏状态。双方通过固定 command 和 response 协作。
