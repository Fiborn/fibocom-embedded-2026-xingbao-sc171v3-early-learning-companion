"""Tool registry for computer-side Xingbao integration rehearsals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.kids_visual_tools_bridge import VISUAL_TOOLS_TARGET, resolve_visual_tool


ToolLauncher = Callable[[], None]


@dataclass(frozen=True)
class ToolDefinition:
    """A child-facing tool or activity that Xingbao can request."""

    id: str
    display_name: str
    description: str
    keywords: tuple[str, ...] = field(default_factory=tuple)
    launch_mode: str = "manual"
    available: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "keywords": list(self.keywords),
            "launch_mode": self.launch_mode,
            "available": self.available,
        }


@dataclass(frozen=True)
class ToolLaunchRequest:
    """A launch decision produced by the registry."""

    target: str
    display_name: str = ""
    available: bool = False
    launch_mode: str = "manual"
    status: str = "not_found"
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "display_name": self.display_name,
            "available": self.available,
            "launch_mode": self.launch_mode,
            "status": self.status,
            "message": self.message,
        }


class ToolRegistry:
    """Looks up tools without directly opening windows or touching hardware."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = {tool.id: tool for tool in (tools or default_tools())}

    def get(self, target: str) -> ToolDefinition | None:
        clean_target = (target or "").strip()
        visual_tool = _visual_tool_definition(clean_target)
        if visual_tool is not None:
            return visual_tool
        return self._tools.get(clean_target)

    def list_tools(self) -> list[dict[str, object]]:
        return [tool.as_dict() for tool in self._tools.values()]

    def build_launch_request(self, target: str) -> ToolLaunchRequest:
        tool = self.get(target)
        if tool is None:
            return ToolLaunchRequest(
                target=target,
                status="not_found",
                message="这个工具还没有登记，星宝先回到主界面。",
            )
        if not tool.available:
            return ToolLaunchRequest(
                target=tool.id,
                display_name=tool.display_name,
                available=False,
                launch_mode=tool.launch_mode,
                status="unavailable",
                message=f"{tool.display_name} 现在还没有准备好。",
            )
        return ToolLaunchRequest(
            target=tool.id,
            display_name=tool.display_name,
            available=True,
            launch_mode=tool.launch_mode,
            status="ready",
            message=f"准备打开 {tool.display_name}。",
        )


def default_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            id="mini_game_hub",
            display_name="触控小游戏中心",
            description=(
                "对接板卡主界面 desktop.py 的触控小游戏中心；"
                "中枢通过 assistant_output/ui_command 打开游戏中心或指定小游戏。"
            ),
            keywords=("\u6e38\u620f", "\u5c0f\u6e38\u620f", "\u95ef\u5173", "\u4e00\u8d77\u73a9"),
            launch_mode="board_ui",
            available=True,
        ),
        ToolDefinition(
            id="color_block_game",
            display_name="色块牌阵小游戏",
            description="电脑端 Tkinter 色块游戏窗口，后续可接触摸屏和桌面实物玩法。",
            keywords=("游戏", "色块", "方块", "牌阵"),
            launch_mode="tkinter_window",
            available=True,
        ),
        ToolDefinition(
            id=VISUAL_TOOLS_TARGET,
            display_name="白宝箱儿童可视化小工具箱",
            description=(
                "迁移自白宝箱的 85 个儿童可视化小工具；"
                "可通过板卡主界面高层命令打开首页或直达指定工具。"
            ),
            keywords=("白宝箱", "工具箱", "小工具", "画板", "认知卡", "打卡", "转盘"),
            launch_mode="board_ui",
            available=True,
        ),
        ToolDefinition(
            id="story_time",
            display_name="故事时间",
            description="故事互动入口；当前先由主对话/TTS 承接，不单独打开窗口。",
            keywords=("故事", "绘本"),
            launch_mode="main_conversation",
            available=True,
        ),
        ToolDefinition(
            id="drawing_board",
            display_name="画画板",
            description="触摸画板预留入口；等待后续桌面 UI 模块接入。",
            keywords=("画画", "涂鸦", "画板"),
            launch_mode="planned",
            available=False,
        ),
    ]


def _visual_tool_definition(target: str) -> ToolDefinition | None:
    if target == VISUAL_TOOLS_TARGET:
        return ToolDefinition(
            id=VISUAL_TOOLS_TARGET,
            display_name="白宝箱儿童可视化小工具箱",
            description="迁移后的儿童可视化小工具首页。",
            keywords=("白宝箱", "工具箱", "小工具"),
            launch_mode="board_ui",
            available=True,
        )
    if not target.startswith(f"{VISUAL_TOOLS_TARGET}:"):
        return None
    try:
        tool = resolve_visual_tool(target)
    except ValueError:
        return None
    if tool is None:
        return None
    return ToolDefinition(
        id=f"{VISUAL_TOOLS_TARGET}:{tool['slug']}",
        display_name=f"白宝箱：{tool['title']}",
        description=str(tool.get("purpose") or "白宝箱儿童可视化小工具。"),
        keywords=(str(tool["title"]), str(tool["slug"])),
        launch_mode="board_ui",
        available=True,
    )
