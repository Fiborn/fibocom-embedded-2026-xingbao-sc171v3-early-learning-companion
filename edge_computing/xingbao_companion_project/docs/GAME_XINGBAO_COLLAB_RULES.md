# 星宝与触控小游戏协同规则手册

## 一句话原则

游戏负责规则和状态，星宝负责理解孩子语言和表达反馈。

## 三方分工

### 语音侧

- 负责唤醒、ASR 和基础意图识别。
- 把孩子自由文本映射成固定 `intent`。
- 不把自由文本直接交给游戏。
- 如果语音线程独立运行，要把 `game_command` 投递回 UI 主线程后再调用游戏接口。

### 游戏侧

- 保存当前游戏状态。
- 判断触控操作是否正确。
- 维护分数、关卡、轮次和进度。
- 提供当前目标、题目、提示、规则说明。
- 接收固定 `game_command.intent` 并返回 `game_response`。
- 可主动上报 `mini_game_state`，例如答错、完成、超时。

### 星宝侧

- 把游戏返回的 `message` 变成儿童友好的 TTS/屏幕表达。
- 根据 `feedback` 生成表情、灯效和高层动作 trace。
- 统一处理 `game_response`、`mini_game_state`、`vision_state`。
- 不直接修改游戏分数、关卡、轮次或正确答案。

## 明确禁止

- 游戏侧不接大模型。
- 游戏侧不理解孩子自由语音。
- 星宝侧不绕过游戏规则判断结果。
- 语音侧不直接改 `app.game`、分数或轮次。
- 任何模块都不输出舵机角度、PWM、GPIO 或串口原始命令。
- 任意动作、表情、灯效都必须使用白名单名称。

## 第一阶段最小闭环

优先跑通：

```text
孩子说“我不会”
-> 语音侧识别为 get_hint
-> UI 主线程调用 GameCommandAdapter.handle_command(command)
-> 游戏返回当前提示
-> 星宝用儿童友好语言播报提示，并更新主界面表情
```

验证命令：

```powershell
python main.py --game-command-file docs/examples/game_command_get_hint.json --coordinate-apply
```

## 触控优先原则

孩子的主要操作应来自屏幕点触、拖拽、选择或翻卡。语音用于：

- 问规则。
- 问提示。
- 问分数。
- 问进度。
- 让星宝重复当前目标。
- 表达不会、想暂停、想退出、想重来。

语音不替代核心触控操作。

## 状态可信原则

游戏状态以游戏侧返回为准：

- 当前分数以游戏返回为准。
- 答对答错以游戏返回为准。
- 当前目标以游戏返回为准。
- 星宝不能根据 LLM 自己猜测孩子是否答对。

## 表达与执行分离

游戏返回结构化数据，星宝把它说成适合孩子听的话。

游戏返回示例：

```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "shape_game",
  "intent": "get_hint",
  "message": "先找最像圆形的那个。",
  "state": {
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

星宝播报示例：

```text
没关系，我们慢慢来。你先找最像圆形的那个。
```

## 错误处理

如果游戏无法处理某个 intent，应返回结构化错误：

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

星宝收到后不责怪孩子，而是温和解释。

## 相关文件

- `src/game_api.py`
- `examples/voice_bridge_example.py`
- `docs/TO_VOICE_TEAM.md`
- `docs/GAME_XINGBAO_API_SPEC.md`
- `docs/GAME_INTENTS_V0.md`
- `docs/XINGBAO_MODULE_EVENT_REPLAY.md`
