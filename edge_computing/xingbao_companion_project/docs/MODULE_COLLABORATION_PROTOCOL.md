# 星宝模块协作协议 V1

## 1. 协议目标

本协议用于约束星宝项目中对话、小游戏、触控、视觉感知、TTS、表情、记忆和成长记录等模块的协作方式。

当前项目的核心不是“聊天机器人 + 小游戏 + 摄像头”的功能堆叠，而是一个会陪孩子说、陪孩子玩、陪孩子学，并越来越懂孩子的成长型 AI 桌宠。所有模块都必须服务这个目标。

核心原则：

**任何模块都不直接控制星宝的嘴、脸、记忆和全局状态，只能提交事件或请求；星宝核心调度层统一决定如何回应。**

也就是说：

- 小游戏不能直接调用 TTS。
- 视觉模块不能直接让星宝说话。
- 触控模块不能直接写入长期记忆。
- 任何模块不能自行决定星宝当前人格、语气和安全边界。
- 所有外部模块只提交结构化事件或请求，由星宝核心调度层统一处理。

## 2. 模块边界

### 2.1 星宝核心调度层

星宝核心调度层是所有模块的汇合点，负责：

- 接收对话、小游戏、触控、视觉、演示模式等输入事件。
- 决定星宝是否说话、说什么、用什么语气说。
- 决定星宝显示什么表情、状态、光效和屏幕提示。
- 决定是否写入记忆或生成成长记录。
- 管理优先级、打断、排队和兜底。
- 统一儿童安全、隐私安全和人格一致性。

### 2.2 对话模块

对话模块负责：

- ASR 文本输入。
- 孩子表达引导。
- 情绪陪伴。
- 儿童适龄知识回答。
- 记忆调用建议。
- 成长记录建议。

对话模块可以提出“星宝应该回应什么”的建议，但最终仍由星宝核心调度层统一发声。

### 2.3 小游戏模块

小游戏模块负责：

- 游戏规则。
- 游戏状态。
- 触控操作。
- 游戏结果。
- 游戏中的提示意图。

小游戏模块不能直接播报语音，不能直接写成长记忆。它只能输出游戏事件或星宝表达请求。

### 2.4 触控模块

触控模块负责：

- 按钮、选项、拖拽、长按、二次确认。
- 把触控行为转成结构化事件。

触控模块不负责判断星宝应该如何人格化回应。

### 2.5 视觉感知模块

视觉感知模块负责：

- 摄像头输入。
- 孩子在位/离位检测。
- 久坐、离屏幕过近、坐姿过低等健康守护事件。
- 桌面区域、色块、卡片、教具识别。

视觉模块只输出观察事件，不直接输出医疗、生理或心理结论。比如可以输出 `sitting_too_long`，不能输出“孩子缺水”或“孩子注意力差”。

### 2.6 TTS / 表情 / 屏幕状态模块

这些模块属于星宝输出层，原则上只接受星宝核心调度层的指令：

- TTS 播放语音。
- 表情显示星宝状态。
- 屏幕显示提示文字、按钮、光效或成长记录。

其他业务模块不能绕过星宝核心调度层直接调用这些输出层。

## 3. 统一事件信封

所有模块提交给星宝核心调度层的消息，都应使用统一信封格式。

```json
{
  "type": "event_type",
  "source": "module_name",
  "event_id": "optional_unique_id",
  "timestamp": "2026-06-28T10:30:00+08:00",
  "priority": 1,
  "payload": {}
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `type` | 是 | 事件类型，例如 `xingbao_expression_request`、`vision_event` |
| `source` | 是 | 来源模块，例如 `dialogue`、`mini_game`、`vision`、`touch`、`demo` |
| `event_id` | 否 | 唯一事件 ID，方便日志追踪 |
| `timestamp` | 建议 | ISO 8601 时间 |
| `priority` | 建议 | 优先级，默认 1 |
| `payload` | 是 | 事件内容 |

## 4. 事件类型

### 4.1 星宝表达请求

用于小游戏、视觉、触控或对话模块请求星宝说一句话、显示表情或给出反馈。

```json
{
  "type": "xingbao_expression_request",
  "source": "mini_game",
  "priority": 1,
  "payload": {
    "intent": "encourage",
    "text": "没关系，我们再试一次。",
    "emotion": "warm",
    "screen_state": "encouraging",
    "tts": true,
    "interrupt_policy": "queue"
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `intent` | 表达意图，例如 `encourage`、`comfort`、`hint`、`celebrate` |
| `text` | 建议话术。最终话术可由星宝核心改写 |
| `emotion` | 情绪风格，例如 `warm`、`happy`、`thinking`、`calm` |
| `screen_state` | 建议屏幕状态 |
| `tts` | 是否建议播报 |
| `interrupt_policy` | `queue`、`replace_low_priority`、`immediate` |

注意：`text` 是建议，不是最终强制播报内容。星宝核心可以根据儿童安全、上下文和当前状态改写。

### 4.2 视觉事件

用于视觉模块提交观察结果。

```json
{
  "type": "vision_event",
  "source": "vision",
  "priority": 2,
  "payload": {
    "event": "sitting_too_long",
    "confidence": 0.86,
    "duration_seconds": 1200
  }
}
```

常见视觉事件：

| 事件 | 含义 |
| --- | --- |
| `child_present` | 孩子在桌前 |
| `child_left_seat` | 孩子离开座位 |
| `child_returned` | 孩子回到座位 |
| `sitting_too_long` | 连续坐太久 |
| `break_reminder_due` | 到休息提醒时间 |
| `drink_water_reminder_due` | 到喝水提醒时间 |
| `face_too_close` | 离屏幕过近 |
| `posture_too_low` | 坐姿过低或趴太低 |
| `camera_blocked` | 摄像头被遮挡 |
| `object_in_play_zone` | 物体进入游戏区 |
| `object_placed_correctly` | 物体放置正确 |

视觉事件不能直接包含“孩子缺水”“孩子不专心”“孩子心理异常”等结论。

### 4.3 触控事件

用于触控屏提交孩子操作。

```json
{
  "type": "touch_event",
  "source": "touch_ui",
  "priority": 1,
  "payload": {
    "event": "child_selected_option",
    "target": "emotion_blue",
    "label": "有点难过"
  }
}
```

常见触控事件：

| 事件 | 含义 |
| --- | --- |
| `child_touched_xingbao` | 孩子触摸星宝 |
| `child_selected_option` | 孩子选择选项 |
| `child_requested_hint` | 孩子请求提示 |
| `child_confirmed_choice` | 孩子确认选择 |
| `child_cancelled_choice` | 孩子取消选择 |
| `child_started_game` | 孩子进入小游戏 |
| `child_finished_game` | 孩子完成小游戏 |

### 4.4 小游戏事件

用于小游戏模块提交游戏状态。

```json
{
  "type": "game_event",
  "source": "mini_game",
  "priority": 1,
  "payload": {
    "event": "round_finished",
    "game_id": "emotion_planet",
    "result": "completed",
    "growth_signal": "child_identified_emotion"
  }
}
```

常见小游戏事件：

| 事件 | 含义 |
| --- | --- |
| `game_started` | 游戏开始 |
| `round_started` | 回合开始 |
| `child_answered` | 孩子完成一次回答 |
| `child_made_mistake` | 孩子选错或操作失败 |
| `child_requested_hint` | 孩子请求提示 |
| `round_finished` | 回合结束 |
| `game_finished` | 游戏结束 |

小游戏只提交状态和成长线索，不直接生成最终成长记录。

### 4.5 记忆写入请求

用于模块请求写入非敏感记忆。

```json
{
  "type": "memory_write_request",
  "source": "dialogue",
  "priority": 1,
  "payload": {
    "memory_kind": "interest",
    "content": "孩子喜欢三角龙。",
    "sensitivity": "non_sensitive",
    "ttl": "long_term",
    "evidence": "孩子主动说：我喜欢三角龙。"
  }
}
```

允许的记忆类型：

| 类型 | 说明 |
| --- | --- |
| `interest` | 兴趣，例如恐龙、积木、颜色 |
| `communication_style` | 表达方式，例如说话慢、喜欢选择题 |
| `recent_mood` | 近期情绪，短期保存 |
| `learning_preference` | 学习偏好，例如喜欢图像提示 |
| `growth_note` | 成长记录，例如今天能说出“我有点着急” |
| `game_preference` | 喜欢的游戏或玩法 |

禁止写入：

- 家庭住址。
- 电话。
- 学校。
- 班级。
- 精确位置。
- 家长联系方式。
- 人脸身份数据。
- 原始照片、视频、录音。

### 4.6 成长记录请求

用于请求生成一次“今日成长记录”。

```json
{
  "type": "growth_record_request",
  "source": "dialogue",
  "priority": 1,
  "payload": {
    "session_id": "demo_session_001",
    "signals": [
      "child_expressed_emotion",
      "child_completed_game",
      "child_accepted_encouragement"
    ],
    "summary_hint": "孩子今天能说出自己有点着急，并完成一次情绪选择任务。"
  }
}
```

成长记录由星宝核心统一生成，语气必须温和、非评判、非排名。

### 4.7 错误事件

任何模块失败时，不应该直接崩溃或静默失败，应输出错误事件。

```json
{
  "type": "module_error",
  "source": "vision",
  "priority": 2,
  "payload": {
    "error_code": "camera_unavailable",
    "message": "摄像头不可用",
    "recoverable": true
  }
}
```

常见错误：

| 错误 | 处理原则 |
| --- | --- |
| `camera_unavailable` | 切换模拟视觉事件或忽略视觉输入 |
| `tts_failed` | 改为屏幕文字提示 |
| `asr_failed` | 请求孩子再说一遍或提供触控选项 |
| `game_state_invalid` | 回到小游戏安全状态 |
| `memory_write_rejected` | 不影响当前流程 |

## 5. 优先级规则

优先级分为 0 到 3。

| 优先级 | 类型 | 示例 |
| --- | --- | --- |
| 0 | 低优先级反馈 | 小游戏轻提示、普通动画 |
| 1 | 正常交互 | 普通对话、游戏提示、触控确认 |
| 2 | 重要陪伴 | 情绪安慰、表达引导、关键任务提示 |
| 3 | 安全/健康 | 离屏幕过近、久坐提醒、摄像头遮挡、异常中断 |

规则：

- 高优先级可以覆盖低优先级。
- 低优先级不能打断高优先级。
- 健康提醒可以延后几秒温和插入，不应粗暴打断孩子表达。
- 安全类提醒优先级最高，但仍要使用儿童友好话术。

## 6. 打断与排队规则

### 6.1 孩子正在说话

- 不允许普通游戏提示打断。
- 不允许低优先级视觉提醒打断。
- 星宝应保持聆听状态。
- 安全提醒可以等待孩子说完后立即插入。

### 6.2 星宝正在 TTS

- 低优先级请求进入队列。
- 同类低优先级请求可以合并。
- 高优先级请求可替换低优先级播报。
- 不能同时播放多条 TTS。

### 6.3 游戏进行中

- 小游戏状态提示优先级不应超过孩子主动表达。
- 游戏反馈要短，不要过度播报。
- 游戏结束后由星宝核心统一做复盘和成长记录。

### 6.4 健康提醒

- 久坐、喝水、离屏幕过近等提醒应温和、短句、低压力。
- 不使用“你不健康”“你坐姿不好”这类否定表达。
- 推荐表达：
  - “我们坐了一会儿啦，要不要站起来伸个懒腰？”
  - “小眼睛离屏幕有点近啦，我们往后坐一点。”
  - “要不要喝一小口水？喝完我们继续。”

## 7. 星宝状态机

星宝核心应维护一个全局状态，避免各模块各自判断。

建议状态：

| 状态 | 含义 |
| --- | --- |
| `idle` | 待机 |
| `listening` | 正在听孩子说话 |
| `thinking` | 正在理解或生成回应 |
| `speaking` | 正在 TTS 播报 |
| `comforting` | 正在情绪安慰 |
| `guiding_expression` | 正在引导孩子表达 |
| `playing_game` | 正在陪孩子玩 |
| `health_reminding` | 正在健康提醒 |
| `summarizing` | 正在生成成长记录 |
| `fallback` | 兜底状态 |

模块请求必须尊重当前状态。例如：

- `speaking` 状态下低优先级播报排队。
- `listening` 状态下普通提示不打断。
- `comforting` 状态下小游戏提示降级。

## 8. 演示模式规则

评委展示时可以使用演示模式，但演示模式不能绕开协议。

演示按钮、预设台词、模拟视觉事件都必须走同一套事件格式。

示例：

```json
{
  "type": "vision_event",
  "source": "demo",
  "priority": 2,
  "payload": {
    "event": "sitting_too_long",
    "confidence": 1.0,
    "duration_seconds": 1200,
    "simulated": true
  }
}
```

这样真实模式和演示模式只是在 `source` 和 `simulated` 字段上不同，主流程不用写两套。

## 9. 日志与调试

所有模块事件建议记录到统一日志，至少包含：

- 时间。
- 来源模块。
- 事件类型。
- 优先级。
- 是否被执行。
- 是否被排队。
- 是否被丢弃。
- 最终星宝输出。

示例日志：

```json
{
  "timestamp": "2026-06-28T10:30:12+08:00",
  "source": "mini_game",
  "type": "xingbao_expression_request",
  "priority": 1,
  "decision": "queued",
  "reason": "xingbao_speaking"
}
```

## 10. 模块合并风险清单

后续开发时重点避免以下问题：

1. 多个模块同时调用 TTS，导致语音重叠。
2. 小游戏自己写话术，导致星宝人格不一致。
3. 视觉模块直接输出健康结论，造成误判风险。
4. 各模块自行写 memory，导致记忆污染或误存敏感信息。
5. 表情、语音、屏幕文字不同步。
6. 演示模式和真实模式两套逻辑，后期难合并。
7. 没有优先级，普通提示打断孩子表达。
8. 没有兜底，摄像头或 TTS 失败后流程中断。
9. 小游戏脱离星宝，变成普通游戏界面。
10. 触控、视觉、语音事件命名不统一，后期对接困难。

## 11. 当前阶段建议实现的最小协议

第一阶段不需要一次实现全部能力，但至少要实现以下 5 类事件：

1. `xingbao_expression_request`
2. `touch_event`
3. `vision_event`
4. `game_event`
5. `memory_write_request`

并且至少支持：

- 单条 TTS 播放队列。
- 星宝基础状态：`idle`、`listening`、`thinking`、`speaking`、`playing_game`。
- 优先级 0 到 3。
- 演示模式模拟事件。
- 非敏感记忆写入检查。

## 12. 责任分配

| 模块 | 负责人 | 必须遵守的协议 |
| --- | --- | --- |
| 星宝对话与成长陪伴 | 对话负责人 | 统一表达、记忆、安全边界 |
| 触控主界面和小游戏 | 互动负责人 | 只提交触控/游戏事件，不直接调 TTS |
| 视觉感知与健康守护 | 视觉负责人 | 只提交视觉事件，不直接下健康结论 |
| TTS / 表情 / 屏幕状态 | 星宝核心调度层 | 统一调度输出 |
| 演示模式 | 所有人协作 | 模拟事件也必须走协议 |

## 13. 最终判断标准

一个模块是否合格，不看它能不能单独跑，而看它是否满足：

- 能用统一事件格式接入星宝核心。
- 不绕过星宝核心直接控制输出。
- 不破坏星宝人格一致性。
- 不写入敏感儿童信息。
- 出错时能输出错误事件并进入兜底流程。
- 能服务“星宝陪孩子成长”的主线体验。

