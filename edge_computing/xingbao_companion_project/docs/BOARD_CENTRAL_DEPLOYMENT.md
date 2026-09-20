# 中枢上板部署说明

## 当前部署策略

同学已经把触控主界面和小游戏部署到板卡，所以不要覆盖它的目录。

推荐板卡目录：

```text
/opt/xingbao_touch_game     # 同学已部署的主界面/小游戏，继续保留
/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion  # 我们的语音中枢，单独部署
```

两个项目通过本机端口通信：

```text
中枢 /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
-> 127.0.0.1:8765
-> 触控主界面 /opt/xingbao_touch_game/desktop.py
```

## 不覆盖的内容

不要覆盖触控游戏目录里的：

```text
saves/
logs/
assets/
screenshots/
```

尤其是 `saves/`，里面可能有游戏记录、画作、视觉状态、桌面设置。

## 已生成的中枢部署包

本地文件：

```text
dist/xingbao_companion_central.zip
```

该包包含中枢代码和 `--board-ui` 对接能力，不包含：

```text
.env
.venv
work/
logs/
本地压缩包
```

重新生成：

```powershell
python tools\make_central_board_package.py
```

如需生成正式上板运行包：

```powershell
python tools\make_board_release_package.py
```

该包会包含迁移后的白宝箱儿童可视化小工具：

```text
web/kids_visual_tools/
config/kids_visual_tools_registry.json
```

## 上传

把 `BOARD_IP` 换成板卡 IP：

```powershell
scp dist\xingbao_companion_central.zip fibo@BOARD_IP:/tmp/xingbao_companion_central.zip
ssh fibo@BOARD_IP "rm -rf /tmp/xingbao_companion_unpack && mkdir -p /tmp/xingbao_companion_unpack /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion && unzip -o /tmp/xingbao_companion_central.zip -d /tmp/xingbao_companion_unpack >/dev/null && cp -a /tmp/xingbao_companion_unpack/xingbao_companion/. /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion/"
```

也可以用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\upload_central_to_board.ps1 -BoardHost BOARD_IP
```

## 启动顺序

### 1. 安装中枢依赖

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
sh deploy/board_install_deps.sh
```

### 2. 启动触控桌面

终端 1：

```bash
cd /opt/xingbao_touch_game
python3 desktop.py --fullscreen --low-effects --no-vision
```

### 3. 中枢自检

终端 2：

```bash
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
export DASHSCOPE_API_KEY="你的key"
python3 tools/board_health_check.py
```

### 4. 先跑一条最小链路

```bash
python3 main.py --coordinate-text "星宝我要玩游戏啦" --board-ui
```

这条能打开游戏中心后，再启动完整语音：

```bash
python3 main.py --wake-chat --realtime-tts --board-ui --show-voice-events
```

非 demo 运行脚本：

```bash
sh deploy/board_start_runtime.sh
```

## 当前已经接入的语音触发

实时语音入口已经支持 `--board-ui`：

- `--voice-once`
- `--wake-loop`
- `--wake-chat`

孩子说：

```text
星宝我要玩游戏啦
```

中枢会发送 `open_game_center` 给触控主界面。

孩子说：

```text
星宝我要玩找颜色
```

中枢会发送 `start_game/color_game` 给触控主界面。

孩子说：

```text
星宝打开白宝箱
星宝打开画板
星宝我要画画
```

中枢会发送 `open_visual_tools` 或 `launch_visual_tool` 给触控主界面。详见：

```text
docs/KIDS_VISUAL_TOOLS_BOARD_INTEGRATION.md
```

## 暂不处理

硬件动作和灯效暂时不需要真实执行。当前只发送高层状态：

```text
arm_action
led_mode
```

等硬件组完成驱动后再接真实执行层。
