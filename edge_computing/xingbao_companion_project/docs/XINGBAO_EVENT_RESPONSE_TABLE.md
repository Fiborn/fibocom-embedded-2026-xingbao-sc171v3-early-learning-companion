# 星宝事件响应表 V1

## 1. 目标

本表把小游戏、触控、视觉、对话等模块发来的事件，统一映射为星宝表达策略。后续代码实现时，星宝核心调度层可以按本表生成 `speak_text`、`screen_text`、`expression`、`memory_request` 和优先级处理。

## 2. 响应字段

| 字段 | 含义 |
| --- | --- |
| `event` | 输入事件 |
| `scenario` | 表达场景 |
| `intent` | 星宝表达意图 |
| `priority` | 建议优先级 |
| `expression` | 建议表情状态 |
| `tts` | 是否建议语音播报 |
| `memory` | 是否建议写记忆 |
| `sample` | 示例话术 |

## 3. 对话事件

| event | scenario | intent | priority | expression | tts | memory | sample |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `child_said_text` | 日常聊天 | respond | 1 | listening | 是 | 视内容 | 星宝听到啦。你想先说发生了什么吗？ |
| `child_unclear_text` | 表达不清 | guide_expression | 2 | listening | 是 | 可写 `communication_style` | 没关系，我们慢慢说。是有人不让你玩吗？ |
| `child_expressed_mood` | 情绪陪伴 | comfort | 2 | comforting | 是 | 可写 `recent_mood` | 听起来你有点难过，星宝先陪你一下。 |
| `child_shared_interest` | 记忆接续 | remember_interest | 1 | happy | 是 | 写 `interest` | 我记住啦，你喜欢三角龙。 |
| `child_asked_question` | 知识问答 | explain_briefly | 1 | thinking | 是 | 否 | 我先讲一点点，如果你想听更多，星宝再继续。 |

## 4. 触控事件

| event | scenario | intent | priority | expression | tts | memory | sample |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `child_touched_xingbao` | 开场/陪伴 | greet | 1 | smile | 是 | 否 | 我在呢，要一起玩一会儿吗？ |
| `child_selected_option` | 选择确认 | confirm_choice | 1 | thinking | 可选 | 否 | 你选了这个，我们一起看看。 |
| `child_requested_hint` | 游戏提示 | hint | 1 | thinking | 是 | 否 | 星宝给你一个小提示：先看看颜色。 |
| `child_confirmed_choice` | 选择确认 | confirm | 1 | happy | 可选 | 否 | 好的，我们就选这个。 |
| `child_cancelled_choice` | 选择修正 | support_retry | 1 | calm | 可选 | 否 | 没关系，我们可以重新选。 |

## 5. 小游戏事件

| event | scenario | intent | priority | expression | tts | memory | sample |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `game_started` | 小游戏开始 | invite_play | 1 | happy | 是 | 否 | 我们一起玩一个小任务吧。 |
| `child_answered` | 游戏进行 | acknowledge | 0 | smile | 可选 | 否 | 星宝看到了。 |
| `child_made_mistake` | 游戏出错 | encourage_retry | 1 | encouraging | 是 | 否 | 这一步有点难，我们换个办法试试。 |
| `child_requested_hint` | 游戏提示 | give_hint | 1 | thinking | 是 | 否 | 你可以先看哪个图案最像答案。 |
| `round_finished` | 回合结束 | short_recap | 1 | smile | 可选 | 可写短期 | 这一轮你尝试了两种办法。 |
| `game_finished` | 游戏结束 | summarize_growth | 2 | happy | 是 | 写 `growth_note` | 你刚才没有放弃，还愿意再试一次。星宝帮你记成一颗尝试星。 |

## 6. 视觉健康事件

| event | scenario | intent | priority | expression | tts | memory | sample |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `child_present` | 回到桌前 | welcome_back | 1 | smile | 可选 | 否 | 你回来啦，我们可以继续。 |
| `child_left_seat` | 离桌 | pause | 1 | calm | 否 | 否 | 屏幕显示：星宝等你回来。 |
| `child_returned` | 回到桌前 | resume | 1 | smile | 是 | 否 | 欢迎回来，我们接着刚才的地方。 |
| `sitting_too_long` | 健康提醒 | break_reminder | 3 | caring | 是 | 否 | 我们坐了一会儿啦，要不要站起来伸个懒腰？ |
| `drink_water_reminder_due` | 健康提醒 | drink_reminder | 2 | caring | 是 | 否 | 要不要喝一小口水？喝完我们继续。 |
| `face_too_close` | 健康提醒 | eye_distance | 3 | caring | 是 | 否 | 小眼睛离屏幕有点近啦，我们往后坐一点。 |
| `camera_blocked` | 兜底 | camera_fallback | 2 | calm | 否 | 否 | 不播报固定文案，由调用方处理视觉不可用。 |

## 7. 记忆与成长事件

| event | scenario | intent | priority | expression | tts | memory | sample |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `memory_recalled` | 记忆接续 | connect_memory | 1 | smile | 是 | 否 | 我还记得你喜欢三角龙。 |
| `memory_write_approved` | 记忆确认 | acknowledge_memory | 0 | smile | 可选 | 已写 | 星宝记住啦。 |
| `growth_record_ready` | 成长记录 | share_growth | 2 | happy | 是 | 已写 | 今天你把“我有点着急”说出来了，这是一颗表达星。 |
| `memory_write_rejected` | 安全兜底 | silent_reject | 0 | neutral | 否 | 否 | 不播报，继续当前流程。 |

## 8. 错误事件

| event | scenario | intent | priority | expression | tts | memory | sample |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `asr_failed` | 兜底 | ask_repeat_or_touch | 1 | confused | 是 | 否 | 星宝刚刚没听清，可以再说一遍，也可以点屏幕。 |
| `tts_failed` | 兜底 | screen_fallback | 2 | calm | 否 | 否 | 屏幕显示文字提示。 |
| `game_state_invalid` | 兜底 | recover_game | 2 | calm | 否 | 否 | 不播报固定文案，由调用方记录并恢复。 |
| `camera_unavailable` | 兜底 | vision_off | 2 | calm | 可选 | 否 | 星宝现在先不用摄像头，也可以继续陪你玩。 |

## 9. 默认规则

如果事件不在表中：

1. 不直接调用 TTS。
2. 生成 `fallback` 场景。
3. 使用温和短句。
4. 不写入长期记忆。
5. 记录日志，等待后续补表。
