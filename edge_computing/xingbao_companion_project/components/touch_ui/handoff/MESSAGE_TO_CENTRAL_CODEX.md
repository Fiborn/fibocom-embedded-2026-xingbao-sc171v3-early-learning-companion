# 可直接交给处理中枢Codex的任务说明

请阅读同目录的`CENTRAL_CONTROLLER_UI_GAME_PROTOCOL.md`，并严格实现V1.0接口。

## 目标

处理中枢需要连接ASR、TTS、主界面UI、小游戏和硬件动作层。

必须实现：

1.接收`child_utterance`，把自然语言映射为固定游戏intent或UI命令。
2.接收小游戏的`speech_request`和`game_response.message`，调用TTS播报UTF-8文字。
3.输出`assistant_output`，其中分别包含`speech`、`screen_expression`、`arm_action`、`led`和`ui_command`。
4.把“我要玩游戏”转换为`open_game_center`，把“我要玩找颜色”转换为`start_game`，不要让UI解析自然语言。
5.把模型输出的emoji归一化为表情白名单名称，不要直接把Unicodeemoji发给UI。
6.实现消息UUID去重、`reply_to`关联、ACK、错误码、TTS状态、断线重连和日志。
7.独立进程通信优先使用`127.0.0.1:8765`上的UTF-8 NDJSON长连接；处理中枢作为Server。

## 强制白名单

表情：

```text
neutral/smile/thinking/curious/sad/surprised/sleepy
```

动作：

```text
stay_still/wave_hand/nod/shake_head/point_left/point_right/small_dance
```

灯效：

```text
off/blue_breath/warm_breath/yellow_blink/rainbow/red_flash
```

UI命令：

```text
open_game_center/start_game/exit_game/open_drawing/open_gallery/start_focus/open_memory/go_home
```

游戏intent：

```text
get_rule/get_goal/get_hint/get_score/get_progress/repeat_prompt/restart_round/next_round/pause_game/exit_game
```

## 禁止事项

- 不允许处理中枢直接修改游戏分数、轮次或答案。
- 不允许UI通过自然语言关键词决定打开什么页面。
- 不允许输出舵机角度、PWM、GPIO或原始串口控制。
- 不允许UI和小游戏各自播放TTS，TTS只能由处理中枢统一播放，避免重复播报。
- 不允许网络线程直接操作Pygame，必须投递到UI主线程。

## 验收

至少通过以下三条闭环：

1.“我不会”→`get_hint`→游戏文字→TTS播报→思考表情。
2.“我要玩游戏”→`open_game_center`→UI打开游戏中心。
3.中枢输出`smile+wave_hand+warm_breath`→UI表情、机械动作、灯效分别执行。

实现时不要自行更改协议字段；若发现缺失字段，先记录兼容建议，再保持V1.0字段可用。
