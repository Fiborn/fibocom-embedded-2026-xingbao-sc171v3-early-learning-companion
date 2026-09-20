# 白宝箱儿童可视化小工具接入说明

## 迁移内容

白宝箱程序已迁移到主项目：

```text
web/kids_visual_tools/
config/kids_visual_tools_registry.json
core/kids_visual_tools_bridge.py
```

其中 `web/kids_visual_tools/kids_visual_tools.py` 是原 Tkinter 主程序，`assets/illustrations/` 保留 85 个工具所需图片素材。星宝中枢不直接依赖 Tkinter 来做意图判断，而是读取 `config/kids_visual_tools_registry.json`。

## 本地/板卡启动

打开白宝箱首页：

```bash
python3 main.py --kids-visual-tools
```

直达某个工具，支持序号、中文名或 slug：

```bash
python3 main.py --kids-visual-tool draw
python3 main.py --kids-visual-tool 18
python3 main.py --kids-visual-tool 儿童画板
```

板卡上也可以使用封装脚本：

```bash
sh deploy/board_start_visual_tools.sh
sh deploy/board_start_visual_tools.sh draw
```

## 主界面跳转协议

中枢通过 `assistant_output.payload.ui_command` 发送高层跳转指令，不发送底层硬件控制。

打开白宝箱首页：

```json
{
  "name": "open_visual_tools",
  "params": {
    "app_id": "kids_visual_tools",
    "working_dir": "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion",
    "python": "python3",
    "script": "web/kids_visual_tools/kids_visual_tools.py",
    "args": [],
    "command": ["python3", "web/kids_visual_tools/kids_visual_tools.py"]
  }
}
```

直达儿童画板：

```json
{
  "name": "launch_visual_tool",
  "params": {
    "app_id": "kids_visual_tools",
    "tool_no": 18,
    "tool_slug": "draw",
    "tool_title": "儿童画板",
    "working_dir": "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion",
    "python": "python3",
    "script": "web/kids_visual_tools/kids_visual_tools.py",
    "args": ["--tool", "draw"],
    "command": ["python3", "web/kids_visual_tools/kids_visual_tools.py", "--tool", "draw"]
  }
}
```

主界面侧只需要在收到上述命令时，以 `working_dir` 为工作目录执行 `command`，或按自身窗口管理方式切换到外部应用。

## 语音触发示例

```bash
python3 main.py --coordinate-text "星宝打开白宝箱" --board-ui
python3 main.py --coordinate-text "星宝打开画板" --board-ui
python3 main.py --coordinate-text "星宝我要画画" --board-ui
```

前者会发送 `open_visual_tools`，后两者会发送 `launch_visual_tool/draw`。

## 上板运行时

非 demo 中枢启动脚本：

```bash
sh deploy/board_start_runtime.sh
```

依赖安装脚本已加入 `python3-tk`：

```bash
sh deploy/board_install_deps.sh
```

如果板卡系统没有 `python3-tk`，白宝箱 Tkinter 窗口会无法打开，但语音中枢、主界面协议和其它非 Tk 功能仍可继续验证。
