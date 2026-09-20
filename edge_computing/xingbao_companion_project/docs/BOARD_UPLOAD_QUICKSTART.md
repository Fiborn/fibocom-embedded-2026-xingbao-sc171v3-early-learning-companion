# 星宝板卡部署最短流程

本文档用于把本地中枢代码上传到板卡，同时保留对方已经部署好的主界面和触控小游戏。

## 已确认目录

- 主界面和小游戏：`/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge`
- 中枢代码部署目录：`/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion`
- 当前板卡 IP：`10.21.236.12`。运行主界面和中枢时必须使用同一块板卡；如果现场网络重新分配地址，应先更新本文档再上传。

中枢会连接主界面提供的 `127.0.0.1:8765` 本地通信服务。主界面和中枢必须在同一块板卡上运行。

## 1. 电脑端上传中枢

在本机 PowerShell 里进入项目目录：

```powershell
cd D:\Projects\xingbao_companion
python tools\make_central_board_package.py
powershell -ExecutionPolicy Bypass -File deploy\upload_central_to_board.ps1 -BoardHost 10.21.236.12
```

主界面联调包有更新时执行：

```powershell
cd D:\Projects\xingbao_companion\work\incoming\xingbao_touch_game_latest\xingbao_touch_game
python tools\make_board_package.py
cd D:\Projects\xingbao_companion
powershell -ExecutionPolicy Bypass -File deploy\upload_touch_bridge_to_board.ps1 -BoardHost 10.21.236.12
```

主界面采用版本目录发布，固定入口仍是 `xingbao_touch_game_bridge`；`saves` 和 `logs` 独立保留，更新代码不会清掉孩子的游戏记录。

如果提示输入密码，输入板卡密码。

这一步只会把中枢部署到 `/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion`，不会覆盖原始主界面目录。完整联动 demo 请启动旁路桥接版 `/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge`。

## 2. 板卡端启动主界面

在板卡终端 1 执行：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge
./board_start.sh
```

`board_start.sh` 会把从 SSH 启动的 Pygame 明确接到物理屏的 XWayland `DISPLAY=:0`，并固定使用带 Pygame 的 Miniforge Python。不要再直接运行 `python3 desktop.py`，否则可能出现后台进入游戏但物理屏仍停留在桌面的情况。

启动后主界面会打开本地 `127.0.0.1:8765` 通信服务，供中枢发送表情、屏幕文字和打开游戏命令；游戏产生的提示语会异步发送到中枢 `127.0.0.1:8766`。

## 3. 板卡端安装中枢依赖

第一次部署或依赖变化后，在板卡终端 2 执行：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
sh deploy/board_install_deps.sh
```

如果板卡已经装好依赖，这一步可以跳过。

## 4. 板卡端启动中枢 demo

在板卡终端 2 执行：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
export DASHSCOPE_API_KEY="这里填真实key"
sh deploy/board_start_demo.sh
```

板卡也支持把 Key 一次性保存到 `~/.config/xingbao/runtime.env`（权限必须为 `600`），之后 `board_start_demo.sh` 会自动加载，不需要每次执行 `export`。Key 不进入项目代码和部署包。

当前板卡已实测录音设备 `0 USB PnP Sound Device` 有有效输入，启动脚本默认使用设备 `0`。如果以后 USB 枚举顺序变化，可先执行 `python3 main.py --list-devices`，再通过 `XINGBAO_INPUT_DEVICE` 覆盖：

```bash
XINGBAO_INPUT_DEVICE=新的设备编号 sh deploy/board_start_demo.sh --max-chat-turns 50
```

当前板卡的 PulseAudio 默认输出是空设备。正式脚本使用 `--board-audio-output`，将唤醒提示音和 TTS 的 WAV 统一交给 `lahaina` 声卡的 `aplay` 后端，不能改回默认输出。

启动后预期闭环：

- 平时静默，听到唤醒词后进入对话。
- 孩子说“我要玩游戏”，中枢会让主界面打开小游戏中心。
- 孩子说“我要玩颜色游戏/形状游戏/数数游戏”等，中枢会请求主界面进入对应小游戏。
- 大模型输出表情和屏幕文字时，中枢会发给主界面展示。
- 游戏开局、答题反馈、提示和结束语会通过 `speech_request` 交给中枢 TTS 播放。
- 硬件动作和灯效当前只做高层字段保留与白名单校验，不直接控制底层硬件。

## 5. 快速检查

只检查中枢依赖和 API key：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
/usr/bin/python3 tools/board_health_check.py --skip-ui
```

检查中枢和主界面通信：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
/usr/bin/python3 tools/board_health_check.py
```

中枢启动后，另开终端检查游戏反向语音通道（默认不真正播放）：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
/usr/bin/python3 tools/game_speech_smoke.py
```

如果第二条失败，先确认主界面终端已经运行 `desktop.py`。

## 6. 常见问题

- `DASHSCOPE_API_KEY missing`：说明板卡终端没有设置通义千问 API key。
- `board_ui_bridge failed`：说明主界面没启动，或者主界面的 `127.0.0.1:8765` 服务没起来。
- `import sounddevice failed`：需要重新执行 `sh deploy/board_install_deps.sh`，或让板卡安装 `portaudio19-dev`。
- 唤醒词不可用但文字/单轮语音可用：通常是 `requirements-wake-word.txt` 里的唤醒依赖没有装完整。
