from core.color_block_events import color_block_result_event
from core.color_block_game import ColorBlockGame


def test_color_block_result_event_keeps_game_message_and_state() -> None:
    game = ColorBlockGame()
    result = game.child_play("red", "star_lane")

    event = color_block_result_event(result, game=game, command_text="play red")

    assert event["type"] == "xingbao_expression_request"
    assert event["source"] == "color_block_game"
    assert event["payload"]["intent"] == "game_feedback"
    assert event["payload"]["text"] == result.message
    assert event["payload"]["tts"] is True
    assert event["payload"]["game_id"] == "color_block_game"
    assert event["payload"]["game_state"]["turn"] == "xingbao"
    assert event["payload"]["action"]["screen_expression"] == "smile"
