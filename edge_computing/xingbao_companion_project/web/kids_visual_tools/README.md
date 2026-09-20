# 儿童可视化小工具箱

这是一个纯 Python/Tkinter 桌面程序，包含 85 个儿童场景小工具：

- 生活与认知：作息、喝水、心情、颜色、形状、数字、动物、食物、交通、职业、安全等
- 游戏创作：画板、涂色、贴纸、拼图、找不同、配对、翻牌、排序、数数、分类等
- 班级工具：点名、值日生、分组、星星奖励
- 界面优化：分类筛选、工具提示、专属卡片内容、独立打卡状态、自动重绘
- 卡通图片库：`assets/illustrations/` 内置 85 个当前工具独立入口图标、24 个通用卡通插画主题，并为 20 个小游戏额外配备独立插画，并提供首页缩略图与页面面板图

## 运行

如果系统已经安装 Python：

```powershell
python kids_visual_tools.py
```

如果使用便携版 Python，且系统无法自动找到 Tcl/Tk 数据目录，可以手动指定：

```powershell
$env:TCL_LIBRARY="C:\PortablePython\tcl\tcl8.6"
$env:TK_LIBRARY="C:\PortablePython\tcl\tk8.6"
& "C:\PortablePython\python.exe" kids_visual_tools.py
```

## 快速打开某个工具

支持序号、中文名和 slug：

```powershell
python kids_visual_tools.py --tool 18
python kids_visual_tools.py --tool 儿童画板
python kids_visual_tools.py --tool draw
```

列出所有工具：

```powershell
python kids_visual_tools.py --list
```

注册表自检：

```powershell
python kids_visual_tools.py --self-test
```

## 程序接口

```python
from kids_visual_tools import get_tool_registry, launch_tool

print(get_tool_registry())
launch_tool(18)
launch_tool("儿童画板")
launch_tool("draw")
```

主程序文件：`kids_visual_tools.py`。

图片库目录：`assets/illustrations/`。其中 `tool_<slug>_thumb.png` 是当前工具的首页入口图标；进入工具内部后不再显示这些图标。
