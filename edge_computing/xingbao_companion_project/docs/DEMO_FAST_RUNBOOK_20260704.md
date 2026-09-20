# 星宝演示最短流程

这份流程只服务于现场演示，目标是先把主界面、语音、中枢和提醒链路稳定跑通。

## 1. 先启动触控主界面

在板卡的触控主界面目录运行：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge
sh board_start.sh
```

如果对面的 `desktop.py` 支持关闭小游戏主动语音，优先这样启动：

```bash
python3 desktop.py --fullscreen --low-effects --no-game-speech
```

这样可以避免小游戏自己连续说话，先把演示权收回到中枢。

## 2. 再启动语音中枢

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
export DASHSCOPE_API_KEY="你的 key"
python3 main.py --wake-chat --board-audio-output --board-ui --game-speech --input-device 0 --show-voice-events
```

## 3. 纯演示模式

如果这次先不走真实麦克风，只演示界面和语音联动，可以直接运行：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
python3 tools/demo_stage_runner.py --sequence --board-audio-output --delay-seconds 10
```

这会依次执行：

1. 打开游戏入口
2. 说“请选择一个游戏”
3. 说“请选择一个难度”
4. 说“太棒了，你答对了”
5. 说“没关系，这一题我们再试一次”
6. 说“你离屏幕有点近啦，往后坐一点吧”
7. 说“你平时也要注意喝水哦”

## 4. 单步触发

如果现场想手动控制节奏，可以单独触发某一步：

```bash
python3 tools/demo_stage_runner.py --stage open_game --board-audio-output
python3 tools/demo_stage_runner.py --stage pick_game --board-audio-output
python3 tools/demo_stage_runner.py --stage pick_difficulty --board-audio-output
python3 tools/demo_stage_runner.py --stage answer_correct --board-audio-output
python3 tools/demo_stage_runner.py --stage answer_wrong --board-audio-output
python3 tools/demo_stage_runner.py --stage face_too_close --board-audio-output
python3 tools/demo_stage_runner.py --stage drink_water --board-audio-output
```

## 5. 现在这套演示的边界

- 这套流程优先保证“能展示”，不是最终真实游戏逻辑。
- 小游戏自己的主动语音先不作为主链路。
- 表情和屏幕提示现在可以由中枢直接发到主界面。
- 真实视觉自动触发提醒这条线，后面再继续做更细的联调。
