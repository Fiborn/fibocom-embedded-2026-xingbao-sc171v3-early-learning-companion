# 发给语音同学的文字

下面这段可以直接转发：

> 我们的触控游戏已经提供固定Python接口。语音侧负责ASR和意图识别，不要把自由文本直接交给游戏，也不需要让游戏接大模型。请把孩子的话映射为固定intent，再在UI主线程调用`src.game_api.GameCommandAdapter(app).handle_command(command)`。返回值中的`message`可直接交给TTS；`feedback`只包含表情、动作、灯效的高层白名单名称。第一阶段请先跑通“我不会→get_hint→游戏返回提示→TTS播报”。示例代码在`examples/voice_bridge_example.py`。

## 固定游戏ID

```text
color_game
shape_game
memory_game
counting_game
english_game
skill_game
```

## 固定intent

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
    "game_id": "color_game",
    "intent": "get_hint",
    "user_text": "我不会",
    "context": {"source": "voice", "child_age_group": "preschool"},
})

tts_speak(response["message"])
feedback = response.get("feedback", {})
```

## 重要边界

- 语音线程不要直接改`app.game`、分数或轮次。
- 如果ASR在独立线程运行，请把command投递回UI主线程后再调用接口。
- 如果语音与UI是独立进程，双方需再确定本地Socket或WebSocket；JSON结构不变。
- 不要输出舵机角度、PWM、GPIO或串口原始命令。
- 儿童播报要短，一次只说一件事，避免“状态、模块、数据、置信度”等技术词。
