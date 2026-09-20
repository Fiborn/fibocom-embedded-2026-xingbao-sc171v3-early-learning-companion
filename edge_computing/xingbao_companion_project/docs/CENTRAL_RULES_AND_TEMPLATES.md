# 星宝语音中枢固定规则、模板回答与动作归档

本文档归档当前项目里已经预先写好的模板回答、固定动作规则和板卡联动动作。当前中枢已按“两条线”拆分：

- 固定动作规则线：只做规则匹配和结构化动作执行，不负责生成口播回复。
- 回答线：负责调用 `qwen-plus` 生成自然语言回复，并受 80 字左右的短回复限制。

## 1. 当前两条线

### 1.1 固定动作规则线

输入来自 ASR 文本。中枢先用 `IntentRouter` 和 `BoardUIClient` 做固定规则匹配。

如果匹配到动作，只发送结构化 `ui_command` 给主界面；如果没有匹配动作，则跳过动作线。

动作线不再使用模板回复，也不请求 UI 侧 TTS：

```json
{
  "speech": {
    "text": "",
    "request_tts": false,
    "interrupt": false
  }
}
```

### 1.2 回答线

动作线执行或跳过后，用户回复统一进入回答线。

回答线调用：

- LLM：`qwen-plus`
- 字数限制：`config/settings.json` 中 `max_reply_chars = 80`
- 提示词位置：`intelligence/prompt_builder.py`
- 裁剪位置：`intelligence/llm_client.py`

回答线负责“怎么自然地说”，动作线负责“要不要执行动作”。

## 2. 固定动作规则

### 2.1 打开游戏中心

触发词来自 `core/intent_router.py`：

| 用户可能说法 | 意图 | UI 指令 |
| --- | --- | --- |
| 我要玩游戏 | `open_tool / mini_game_hub` | `open_game_center` |
| 玩小游戏 | `open_tool / mini_game_hub` | `open_game_center` |
| 一起玩 | `open_tool / mini_game_hub` | `open_game_center` |
| 闯关 | `open_tool / mini_game_hub` | `open_game_center` |

输出：

```json
{
  "name": "open_game_center",
  "params": {}
}
```

### 2.2 直接进入指定小游戏

指定小游戏映射来自 `core/board_ui_client.py` 的 `_requested_game_id()`。

| 用户可能说法 | `game_id` | UI 指令 |
| --- | --- | --- |
| 找颜色、颜色游戏、颜色、色彩 | `color_game` | `start_game` |
| 认形状、形状游戏、形状、图形 | `shape_game` | `start_game` |
| 记忆游戏、记忆、小路 | `memory_game` | `start_game` |
| 数数游戏、数数、数字 | `counting_game` | `start_game` |
| 英语游戏、英语、英文 | `english_game` | `start_game` |
| 挑战 | `skill_game` | `start_game` |

输出示例：

```json
{
  "name": "start_game",
  "params": {
    "game_id": "shape_game",
    "difficulty": 1
  }
}
```

### 2.3 回到主界面

| 用户可能说法 | 意图 | UI 指令 |
| --- | --- | --- |
| 不玩了 | `exit_activity` | `return_to_desktop` |
| 退出 | `exit_activity` | `return_to_desktop` |
| 结束 | `exit_activity` | `return_to_desktop` |
| 回家 | `exit_activity` | `return_to_desktop` |
| 停一下 | `exit_activity` | `return_to_desktop` |

输出：

```json
{
  "name": "return_to_desktop",
  "params": {}
}
```

注意：这不是退出语音会话，只是让 `desktop.py` 从游戏回到主界面。

### 2.4 语音获取游戏状态

这类规则属于固定动作规则线，但它会产生一条可播报的真实状态回答。原因是答案必须来自当前小游戏，而不是由 `qwen-plus` 猜测。

流程：

1. ASR 文本进入 `core/game_status_query.py`。
2. 匹配到固定 `game_command.intent`。
3. 中枢通过 `BoardUIClient.send_game_command()` 发给主界面。
4. 主界面在 UI 主线程调用小游戏状态接口。
5. 小游戏返回 `game_response.message`，中枢交给 TTS 播放。

输出示例：

```json
{
  "game_command": {
    "type": "game_command",
    "game_id": "current_game",
    "intent": "get_stars",
    "user_text": "星宝，我现在有几颗星？",
    "context": {
      "source": "voice"
    }
  }
}
```

常见问法覆盖：

| 用户可能说法 | 固定 `intent` | 回答来源 |
| --- | --- | --- |
| 我有几颗星、现在有多少颗星、拿到几颗星 | `get_stars` | 当前小游戏状态 |
| 我有多少分、现在多少分、成绩怎么样 | `get_score` | 当前小游戏状态 |
| 进度怎么样、做到哪里、玩到哪里了 | `get_progress` | 当前小游戏状态 |
| 还剩几题、还有多少轮、还差多少 | `get_remaining` | 当前小游戏状态 |
| 现在第几题、当前第几关、第几轮 | `get_round` | 当前小游戏状态 |
| 现在要做什么、任务是什么、应该点哪个 | `get_goal` | 当前小游戏状态 |
| 怎么玩、规则是什么、玩法是什么 | `get_rule` | 当前小游戏规则 |
| 我不会、提示一下、给点线索 | `get_hint` | 当前小游戏提示 |
| 再说一遍、刚才说什么、没听清 | `repeat_prompt` | 当前小游戏上一句提示 |
| 现在什么游戏、当前游戏、玩的是啥 | `get_current_game` | 当前小游戏状态 |
| 我现在怎么样、游戏状态、情况怎么样 | `get_status` | 当前小游戏状态 |
| 现在几级、当前等级 | `get_level` | 当前小游戏状态 |
| 还有多少能量、现在多少体力 | `get_energy` | 当前小游戏状态 |
| 答对几个、做对几题 | `get_correct` | 当前小游戏状态 |
| 错了几个、答错几题、失败几次 | `get_errors` | 当前小游戏状态 |
| 试了几次、一共点了几次 | `get_attempts` | 当前小游戏状态 |

如果主界面或小游戏没有准备好，中枢会返回兜底短句：`当前小游戏还没有准备好，星宝先陪你等一下。`

### 2.5 当前不执行 UI 动作的匹配

这些意图可以被识别，但当前没有板卡 UI 执行动作，因此动作线跳过：

| 用户可能说法 | 意图 | 当前处理 |
| --- | --- | --- |
| 讲故事、听故事、故事、绘本 | `open_tool / story_time` | 由回答线讲故事，不打开独立窗口 |
| 画画、涂鸦、画板、涂颜色 | `open_tool / drawing_board` | 工具未准备好，暂不发 UI 指令 |
| 帮帮我、帮助我、不会、不懂、提示 | `ask_help` | 不发 UI 指令，由回答线回复 |
| 普通聊天 | `chat` | 不发 UI 指令，由回答线回复 |
| 未识别文本 | `unknown` | 不发 UI 指令，由回答线或兜底逻辑处理 |

## 3. 预定屏幕表现动作

动作线除了 `ui_command`，还会带高层屏幕状态。主界面负责映射到实际动画。

### 3.1 表情白名单

来自 `core/board_ui_client.py`：

| 表情名 | 用途 |
| --- | --- |
| `neutral` | 默认、平静 |
| `smile` | 开心、鼓励、游戏准备 |
| `thinking` | 思考、等待 |
| `curious` | 倾听、疑问 |
| `sad` | 难过 |
| `surprised` | 惊喜 |
| `sleepy` | 休眠、安静等待 |

未知表情会降级为 `neutral`。

### 3.2 表情映射

| 中枢表达状态 | 主界面表情 |
| --- | --- |
| `happy` / `smile` / `encouraging` | `smile` |
| `listening` | `curious` |
| `thinking` | `thinking` |
| `confused` | `curious` |
| `calm` / `neutral` | `neutral` |
| `sleepy` | `sleepy` |
| `sad` | `sad` |
| `surprised` | `surprised` |

### 3.3 灯效白名单

当前 UI 只校验高层灯效名，底层硬件先不接。

| 灯效 | 用途 |
| --- | --- |
| `off` | 关闭 |
| `blue_breath` | 倾听、思考、安抚 |
| `warm_breath` | 开心、鼓励 |
| `yellow_blink` | 提醒 |
| `rainbow` | 庆祝 |
| `red_flash` | 警示 |

### 3.4 高层动作白名单

当前不直接控制机械臂，只保留高层动作名：

| 动作 | 说明 |
| --- | --- |
| `stay_still` | 保持不动 |
| `wave_hand` | 挥手 |
| `nod` | 点头 |
| `shake_head` | 摇头 |
| `point_left` | 指向左侧 |
| `point_right` | 指向右侧 |
| `small_dance` | 小幅庆祝 |
| `bow` | 鞠躬，开场欢迎/礼貌回应 |

## 4. 现有模板回答归档

以下模板是项目中已有的固定话术。改造后，固定动作线不再使用这些模板作为动作回复；它们只作为历史归档、事件兜底或安全兜底参考。

### 4.1 语音系统级固定提示

| 场景 | 模板 |
| --- | --- |
| 只听到唤醒词 | 我在呢。你想聊什么？ |
| 结束语音会话 | 好的，星宝先安静等你。想继续聊的时候，再叫我一声星宝星宝。 |

### 4.2 快速确认短句

来自 `config/voice_profiles.json` 和低延迟前置回复：

| 场景 | 模板 |
| --- | --- |
| 默认 quick ack | 星宝收到啦，我想一想。 |
| 安慰音色 quick ack | 星宝在听呢，慢慢说。 |
| 故事音色 quick ack | 好呀，星宝准备讲给你听。 |
| 提示音色 quick ack | 收到，星宝马上处理。 |
| 故事前置 | 好呀，我先给你准备一个小故事。 |
| 指定主题故事前置 | 好呀，我先给你准备一个{topic}小故事。 |
| 打招呼前置 | 我在呢，正等你一起玩。 |
| 求助前置 | 没关系，我们一步一步来。 |

### 4.3 文本意图旧模板

来自 `core/coordinator.py`。这些模板已不再作为动作线口播使用。

| 意图 | 旧模板 |
| --- | --- |
| 打开小游戏中心 | 好呀，我们准备打开新的小游戏入口。星宝会先露出笑脸，再帮你进入游戏。 |
| 打开色块牌阵 | 好呀，我们一起玩色块小游戏。星宝先露出笑脸，然后帮你打开游戏窗口。 |
| 故事时间 | 好呀，我们进入故事时间。你想听恐龙、星星，还是小动物的故事？ |
| 工具不可用 | {工具名} 还在准备中，我们可以先换一个玩法。 |
| 工具未登记 | 这个小工具还没有准备好，星宝先陪你在主界面玩。 |
| 帮助 | 没关系，星宝陪你一步一步来。你可以说要提示，也可以点屏幕。 |
| 回主界面 | 好呀，我们先停一下，星宝在主界面等你。 |
| 未听清 | 星宝刚刚没有听清，可以再说一遍，或者点屏幕选一个玩法。 |
| 普通聊天占位 | 星宝听到啦，我们慢慢聊。 |

### 4.4 表达事件模板

来自 `core/expression.py`。

| 事件 | 模板 |
| --- | --- |
| `child_unclear_text` | 不播报固定文案，由对话 LLM 结合上下文追问。 |
| `child_expressed_mood` | 不播报固定文案，由对话 LLM 结合上下文安慰。 |
| `child_touched_xingbao` | 我在呢，要一起玩一会儿吗？ |
| `child_requested_hint` | 星宝给你一个小提示：先看看颜色。 |
| `child_cancelled_choice` | 没关系，我们可以重新选。 |
| `game_started` | 我们一起玩一个小任务吧。 |
| `child_made_mistake` | 这一步有点难，我们换个办法试试。 |
| `game_finished` | 你刚才没有放弃，还愿意再试一次。星宝帮你记成一颗尝试星。 |
| `child_returned` | 欢迎回来，我们接着刚才的地方。 |
| `sitting_too_long` | 我们坐了一会儿啦，要不要站起来伸个懒腰？ |
| `drink_water_reminder_due` | 要不要喝一小口水？喝完我们继续。 |
| `face_too_close` | 小眼睛离屏幕有点近啦，我们往后坐一点。 |
| `camera_blocked` | 不播报固定文案，由调用方处理视觉不可用。 |
| `memory_write_request` 成功 | 星宝记住啦。 |
| `growth_record_request` 默认 | 今天你愿意表达，也愿意继续尝试。星宝帮你记成一颗成长星。 |
| `asr_failed` | 星宝刚刚没听清，可以再说一遍，也可以点屏幕。 |
| `tts_failed` | 星宝先把话显示在屏幕上 |
| 默认错误 | 不播报固定文案，由调用方记录并恢复。 |
| 未支持事件 | 星宝刚刚有一点没跟上，我们可以点屏幕继续，也可以再说一遍。 |
| 未支持 payload event | 星宝收到这个变化了，我们先慢慢继续。 |

### 4.5 成长引导模板

来自 `core/growth_guidance.py`。当前只有安全/隐私类会直接使用固定模板；表达、情绪、观点类会把目标交给 `qwen-plus` 生成自然回复。

| 场景 | 模板 |
| --- | --- |
| 表达脚手架 | 不使用固定台词；提示 LLM 依据上下文耐心澄清，不猜测具体事件。 |
| 情绪命名 | 你的感受很重要。你现在更像是生气，还是有点难过？ |
| 观点鼓励 | 你的想法很重要。可以告诉我，你为什么这样觉得吗？ |
| 倾听支持 | 星宝听见啦。你可以继续说，我会慢慢听。 |
| 选择确认 | 星宝听懂了一点。我们可以这样说：我现在觉得{label}。 |
| 尊重拒绝 | 好的，我们先不聊这个。你想换一个话题吗？ |
| 游戏鼓励 | 这一点有点难，没关系。我们换个线索再试一次。 |
| 游戏成长总结 | 你刚才愿意继续尝试，星宝帮你记成一颗成长星。 |
| 游戏支持 | 星宝陪你一起玩，我们一步一步来。 |
| 久坐提醒 | 我们坐了一会儿啦，要不要站起来伸个懒腰？ |
| 喝水提醒 | 要不要喝一小口水？喝完星宝陪你继续。 |
| 距离提醒 | 小眼睛离屏幕有点近啦，我们往后坐一点。 |
| 安全支持 | 不使用固定台词；交由 LLM 按安全规则自然引导向可信赖的大人求助。 |
| 隐私边界 | 不使用固定台词；交由 LLM 自然说明边界且不复述隐私内容。 |

## 5. 小游戏到语音中枢的反向模板

小游戏不直接播放音频，而是通过 `127.0.0.1:8766` 发 `speech_request` 给中枢。这里的文本可能来自小游戏自己的规则，不属于“语音打开软件动作线”。

示例：

```json
{
  "type": "speech_request",
  "source": "shape_game",
  "text": "请选择一个圆形",
  "page": "game_running"
}
```

中枢收到后调用 TTS 播放。

## 6. 当前原则

1. 固定动作规则只输出结构化动作，不输出固定口播。
2. 没有匹配到动作时，动作线跳过，不向 UI 发送无意义命令。
3. 面向孩子的回答默认交给 `qwen-plus`。
4. `qwen-plus` 回复保持短句、日常聊天风格，默认不超过 80 个中文字符。
5. UI、灯效、动作只接收白名单高层状态，不接收底层硬件命令。
