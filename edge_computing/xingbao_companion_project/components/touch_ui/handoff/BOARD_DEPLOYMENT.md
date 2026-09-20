# SC171V3板卡搬运与启动

以下步骤默认板卡运行Linux，并已有可用显示桌面或SDL显示环境。如果板卡是Android系统，不能直接照此运行，需要先准备Python和pygame运行环境，或改为Android应用方案。

## 1.本地需要复制什么

最稳妥的方法不是手工挑文件，而是在项目根目录执行：

```powershell
python tools\make_board_package.py
```

生成：

```text
dist/xingbao_touch_game_board.zip
dist/xingbao_touch_game_board/
```

如果要把本地画作、回忆和积分一起带到板卡：

```powershell
python tools\make_board_package.py --include-saves
```

板卡运行必需内容：

```text
desktop.py
main.py
requirements.txt
src/
config/
assets/
board_start.sh
```

联调时建议一并复制：

```text
examples/
handoff/
```

不需要复制：

```text
__pycache__/
logs/
screenshots/
audit/
tests/
dist/
```

`saves/`有两种处理方式：

- 想从空白状态演示：不复制本地`saves/`，板卡首次运行会自动创建。
- 想把本地画作和回忆带过去：复制整个`saves/`，其中必须包含`artworks/`、`memory_shots/`、`xingbao_memory.json`和`desktop_settings.json`。

## 2.复制到板卡

假设板卡IP为`192.168.1.50`、用户名为`root`：

```powershell
scp .\dist\xingbao_touch_game_board.zip root@192.168.1.50:/opt/
```

板卡执行：

```bash
cd /opt
unzip -o xingbao_touch_game_board.zip
cd xingbao_touch_game_board
chmod +x board_start.sh
```

如果板卡没有`scp`或`unzip`，也可以把`dist/xingbao_touch_game_board/`整个文件夹复制到U盘，再粘贴到板卡`/opt/`或用户主目录。

## 3.安装依赖

先检查：

```bash
python3 --version
python3 -c "import pygame;print(pygame.version.ver)"
```

Ubuntu/Debian类系统：

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev libsdl2-mixer-dev fonts-noto-cjk
python3 -m pip install -r requirements.txt
```

## 4.全屏启动

```bash
python3 desktop.py --fullscreen --low-effects
```

确认中文、触控、声音和图片正常后，正式启动同样使用全屏：

```bash
./board_start.sh
```

脚本实际执行：

```bash
python3 desktop.py --fullscreen --low-effects
```

如果提示找不到显示：

```bash
export DISPLAY=:0
./board_start.sh
```

## 5.联调文件位置

```text
saves/vision_status.json       视觉侧写入两个状态值
saves/xingbao_memory.json      回忆本索引
saves/artworks/                孩子的画
saves/memory_shots/            游戏和专心过程截图
saves/latest_save.json         游戏成长记录
saves/desktop_settings.json    桌面积分与设置
logs/                          运行日志
```

## 6.上板前验收命令

```bash
python3 -m py_compile desktop.py main.py src/app.py src/game_api.py
python3 main.py --soak-test --rounds 20 --log-dir logs/board_smoke
python3 examples/vision_writer_example.py
```

最后一条会持续写视觉测试值，确认文件产生后按`Ctrl+C`结束。
