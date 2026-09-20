from core.color_block_voice import parse_color_block_voice_command


def test_parse_complete_play_command() -> None:
    command = parse_color_block_voice_command("红色放星光线")

    assert command.intent == "play"
    assert command.color_id == "red"
    assert command.lane_id == "star_lane"


def test_parse_pass_command() -> None:
    command = parse_color_block_voice_command("这一回合我停手")

    assert command.intent == "pass"


def test_parse_partial_command_needs_lane() -> None:
    command = parse_color_block_voice_command("蓝色")

    assert command.intent == "unknown"
    assert command.color_id == "blue"
    assert "星光线" in command.message
