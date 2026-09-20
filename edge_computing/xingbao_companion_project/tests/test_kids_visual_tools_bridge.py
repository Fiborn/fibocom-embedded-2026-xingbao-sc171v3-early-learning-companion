from core.kids_visual_tools_bridge import (
    build_visual_tools_ui_command,
    get_visual_tool_registry,
    resolve_visual_tool,
    visual_tool_target,
)


def test_visual_tool_registry_loads_migrated_toolbox() -> None:
    tools = get_visual_tool_registry()

    assert len(tools) == 85
    assert tools[17]["title"] == "儿童画板"
    assert tools[17]["slug"] == "draw"


def test_resolve_visual_tool_accepts_number_title_slug_and_target() -> None:
    assert resolve_visual_tool(18)["slug"] == "draw"
    assert resolve_visual_tool("儿童画板")["slug"] == "draw"
    assert resolve_visual_tool("draw")["title"] == "儿童画板"
    assert resolve_visual_tool("kids_visual_tools:draw")["no"] == 18
    assert resolve_visual_tool("kids_visual_tools") is None


def test_visual_tool_target_uses_prefixed_slug() -> None:
    assert visual_tool_target() == "kids_visual_tools"
    assert visual_tool_target("draw") == "kids_visual_tools:draw"


def test_build_visual_tools_ui_command_for_home_and_direct_tool() -> None:
    home = build_visual_tools_ui_command()
    direct = build_visual_tools_ui_command("draw")

    assert home["name"] == "open_visual_tools"
    assert home["params"]["command"] == [
        "python3",
        "web/kids_visual_tools/kids_visual_tools.py",
    ]
    assert direct["name"] == "launch_visual_tool"
    assert direct["params"]["tool_slug"] == "draw"
    assert direct["params"]["tool_title"] == "儿童画板"
    assert direct["params"]["command"] == [
        "python3",
        "web/kids_visual_tools/kids_visual_tools.py",
        "--tool",
        "draw",
    ]
