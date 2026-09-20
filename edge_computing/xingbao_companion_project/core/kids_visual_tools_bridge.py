"""Bridge for the migrated kids visual tools toolbox."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VISUAL_TOOLS_DIR = PROJECT_ROOT / "web" / "kids_visual_tools"
VISUAL_TOOLS_SCRIPT = VISUAL_TOOLS_DIR / "kids_visual_tools.py"
VISUAL_TOOLS_REGISTRY_PATH = PROJECT_ROOT / "config" / "kids_visual_tools_registry.json"
BOARD_COMPANION_DIR = "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion"
VISUAL_TOOLS_TARGET = "kids_visual_tools"


def get_visual_tool_registry() -> list[dict[str, Any]]:
    """Return the lightweight registry without importing Tkinter."""
    data = json.loads(VISUAL_TOOLS_REGISTRY_PATH.read_text(encoding="utf-8-sig"))
    tools = data.get("tools")
    if not isinstance(tools, list):
        raise ValueError("kids visual tools registry is missing tools")
    return [dict(tool) for tool in tools if isinstance(tool, dict)]


def resolve_visual_tool(value: Any) -> dict[str, Any] | None:
    """Resolve a tool by number, title, slug, kind suffix, or prefixed target."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw == VISUAL_TOOLS_TARGET:
        return None
    if raw.startswith(f"{VISUAL_TOOLS_TARGET}:"):
        raw = raw.split(":", 1)[1]
    key = _norm(raw)
    for tool in get_visual_tool_registry():
        candidates = {
            _norm(tool.get("no", "")),
            _norm(tool.get("title", "")),
            _norm(tool.get("slug", "")),
            _norm(str(tool.get("kind", "")).split(":")[-1]),
        }
        if key in candidates:
            return tool
    raise ValueError(f"找不到白宝箱工具：{value}")


def visual_tool_target(value: Any | None = None) -> str:
    """Return the tool-registry target id used by Xingbao coordination."""
    tool = resolve_visual_tool(value)
    if tool is None:
        return VISUAL_TOOLS_TARGET
    return f"{VISUAL_TOOLS_TARGET}:{tool['slug']}"


def build_visual_tools_ui_command(
    value: Any | None = None,
    *,
    board_workdir: str = BOARD_COMPANION_DIR,
    python_bin: str = "python3",
) -> dict[str, Any]:
    """Build the high-level board UI command for toolbox navigation."""
    tool = resolve_visual_tool(value)
    args: list[str] = []
    params: dict[str, Any] = {
        "app_id": VISUAL_TOOLS_TARGET,
        "working_dir": board_workdir,
        "python": python_bin,
        "script": "web/kids_visual_tools/kids_visual_tools.py",
    }
    if tool is not None:
        args = ["--tool", str(tool["slug"])]
        params.update(
            {
                "tool_no": int(tool["no"]),
                "tool_slug": str(tool["slug"]),
                "tool_title": str(tool["title"]),
                "category": str(tool.get("category") or ""),
            }
        )
    params["args"] = args
    params["command"] = [python_bin, params["script"], *args]
    return {
        "name": "launch_visual_tool" if tool is not None else "open_visual_tools",
        "params": params,
    }


def launch_visual_tools(
    value: Any | None = None,
    *,
    python_bin: str | None = None,
    wait: bool = True,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Launch the migrated toolbox locally or on the board runtime."""
    if not VISUAL_TOOLS_SCRIPT.exists():
        raise FileNotFoundError(str(VISUAL_TOOLS_SCRIPT))
    tool = resolve_visual_tool(value)
    command = [python_bin or sys.executable, str(VISUAL_TOOLS_SCRIPT)]
    if tool is not None:
        command.extend(["--tool", str(tool["slug"])])
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    if wait:
        completed = subprocess.run(command, cwd=str(PROJECT_ROOT), env=env, check=False)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "command": command,
        }
    process = subprocess.Popen(command, cwd=str(PROJECT_ROOT), env=env)
    return {"ok": True, "pid": process.pid, "command": command}


def _norm(value: Any) -> str:
    return re.sub(r"[\s_\-，。！？,.!?\"'（）()]+", "", str(value).casefold())
