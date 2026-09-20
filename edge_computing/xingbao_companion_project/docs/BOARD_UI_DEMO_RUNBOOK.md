# 星宝中枢与触控桌面 Demo 联调说明

## 目标

让中枢把语音/事件计划输出为 `assistant_output`，发送给触控桌面 `desktop.py`，由桌面执行：

- 星宝表情
- 屏幕提示文字
- 打开游戏中心或指定小游戏
- 高层动作/灯效校验

TTS 仍由中枢侧负责播放。

## 启动顺序

1. 启动触控桌面。

在对面触控游戏包根目录运行：

```bash
python desktop.py --fullscreen --low-effects
```

电脑窗口调试可用：

```bash
python desktop.py --window --no-vision
```

桌面默认会启动 `127.0.0.1:8765` UTF-8 NDJSON 服务。不要加 `--no-central-bridge`。

2. 在本中枢项目运行联调命令。

打开游戏中心：

```bash
python main.py --coordinate-text "星宝我要玩游戏啦" --board-ui
```

直接打开找颜色：

```bash
python main.py --coordinate-text "星宝我要玩找颜色" --board-ui
```

游戏提示返回 TTS 文本，并同步表情/灯效：

```bash
python main.py --game-command-file docs/examples/game_command_get_hint.json --board-ui --expression-speak --local-tts-fallback
```

视觉状态回放：

```bash
python main.py --coordinate-state-file docs/examples/vision_state_face_too_close.json --board-ui
```

## 成功标志

命令输出 JSON 中应出现：

```json
{
  "board_ui": {
    "ok": true,
    "response": {
      "type": "command_result",
      "ok": true
    }
  }
}
```

`trace` 中应出现：

```text
board_ui.assistant_output -> sent
```

如果桌面服务没有启动，会出现：

```text
board_ui.assistant_output -> failed
```

这通常表示 `desktop.py` 没有运行、端口不是 `8765`，或板卡网络/进程未连接。

## 视觉联调

对面触控包已经包含 `src/vision_bridge.py`。它会运行视觉发布包，读取视觉 JSON：

- `return_code=1` -> `distance_too_close=1`
- `drink_return_code=1` -> `needs_water=1`

然后写入：

```text
saves/vision_status.json
```

触控桌面读取该文件后显示护眼或喝水提醒。

## 仍需注意

`XingbaoApp.speak()` 已支持 `on_speech_request` 回调，但对面 `desktop.py` 默认创建游戏时还没有把这个回调绑定到中枢 socket。因此“游戏主动说话 -> 中枢 TTS”这条链路具备代码入口，但现场仍需确认反向通道绑定方式。
