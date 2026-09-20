from core.output_adapters import OutputTrace, ToolLaunchAdapter


def test_tool_launch_adapter_records_planned_ready_tool() -> None:
    trace = OutputTrace()

    ToolLaunchAdapter().record(
        trace,
        target="color_block_game",
        request_status="ready",
        launch_enabled=False,
        launched=False,
        message="ready",
    )

    assert trace.as_list() == [
        {
            "type": "tool.open",
            "status": "planned",
            "payload": {
                "target": "color_block_game",
                "request_status": "ready",
                "launch_enabled": False,
                "launched": False,
                "message": "ready",
            },
        }
    ]
