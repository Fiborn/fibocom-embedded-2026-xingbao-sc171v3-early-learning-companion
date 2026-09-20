# 发给语音同学的对接说明

下面这段可以直接转发：

> 我们的触控小游戏已经提供固定 Python 接口。语音侧负责 ASR 和 intent 识别，不要把自由文本直接交给游戏，也不需要让游戏接大模型。请把孩子的话映射为固定 intent，再在 UI 主线程调用 `src.game_api.GameCommandAdapter(app).handle_command(command)`。返回值中的 `message` 可以直接交给 TTS；`feedback` 只包含表情、动作、灯效的高层白名单名称。第一阶段请先跑通“我不会 -> get_hint -> 游戏返回提示 -> TTS 播报”。示例代码在 `examples/voice_bridge_example.py`。

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
repeat_prompt
restart_round
next_round
pause_game
exit_game
```

## 调用示例

```python
from src.game_api import GameCommandAdapter

adapter = GameCommandAdapter(app)
response = adapter.handle_command({
    "type": "game_command",
    "game_id": "shape_game",
    "intent": "get_hint",
    "user_text": "我不会",
    "context": {"source": "voice", "child_age_group": "preschool"},
})

tts_speak(response["message"])
feedback = response.get("feedback", {})
```

## 重要边界

- 语音线程不要直接改 `app.game`、分数或轮次。
- 如果 ASR 在独立线程运行，请把 `command` 投递回 UI 主线程后再调用接口。
- 如果语音和 UI 是独立进程，双方后续可以把同一个 JSON 结构放到本地 Socket 或 WebSocket 中，结构不变。
- 不要输出舵机角度、PWM、GPIO 或串口原始命令。
- 儿童播报要短，一次只说一件事，避免“状态、模块、数据、置信度”等技术词。
