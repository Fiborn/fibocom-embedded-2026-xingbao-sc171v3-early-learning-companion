import random

from core.action_safety import ActionSanitizer
from core.color_block_game import ColorBlockGame


def test_child_red_block_scores_and_uses_safe_lane_action() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    result = game.child_play("red", "star_lane")

    assert result.ok is True
    assert game.scores["child"]["star_lane"] == 4
    assert game.hands["child"]["red"] == 0
    assert game.snapshot()["play_records"][-1]["color_id"] == "red"
    assert game.snapshot()["play_records"][-1]["points_gained"] == 4
    assert result.action.arm_action == "point_left"
    assert result.action.screen_expression == "smile"


def test_inspire_adds_bonus_to_next_play() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    game.child_play("yellow", "star_lane")
    game.xingbao_take_turn()
    game.child_play("blue", "guard_lane")

    assert game.scores["child"]["star_lane"] == 2
    assert game.scores["child"]["guard_lane"] == 5


def test_repair_adds_points_to_weaker_lane() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    game.child_play("red", "star_lane")
    game.xingbao_take_turn()
    game.child_play("green", "star_lane")

    assert game.scores["child"]["star_lane"] == 6
    assert game.scores["child"]["guard_lane"] == 2


def test_child_recent_color_pair_triggers_combo_bonus() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    game.child_play("yellow", "star_lane")
    game.xingbao_take_turn()
    result = game.child_play("red", "guard_lane")

    assert result.ok is True
    assert "勇气灵感" in result.message
    assert game.scores["child"]["star_lane"] == 2
    assert game.scores["child"]["guard_lane"] == 8
    assert game.snapshot()["round_combo_count"] == 1
    assert game.snapshot()["play_records"][-1]["points_gained"] == 8


def test_blue_guard_creates_one_safe_echo_when_xingbao_gets_ahead() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    game.child_play("blue", "star_lane")
    result = game.xingbao_take_turn()

    assert result.ok is True
    assert "守护" in result.message
    assert game.scores["child"]["star_lane"] == 4
    assert game.stable_lanes["child"] is None


def test_easy_xingbao_passes_earlier_when_ahead() -> None:
    game = ColorBlockGame(rng=random.Random(1), difficulty="easy")
    game.turn = "xingbao"
    game.scores["xingbao"]["star_lane"] = 3

    result = game.xingbao_take_turn()

    assert result.ok is True
    assert result.message.startswith("星宝停手")
    assert game.passed["xingbao"] is True


def test_round_ends_when_both_players_pass_and_next_round_starts() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    game.child_play("red", "star_lane")
    game.xingbao_take_turn()
    child_pass = game.child_pass()
    assert child_pass.round_over is False
    xingbao_play = game.xingbao_take_turn()
    assert xingbao_play.round_over is False
    xingbao_pass = game.xingbao_take_turn()

    assert xingbao_pass.round_over is True
    assert game.round_winners == ["xingbao"]
    assert game.current_round == 2
    assert game.turn == "child"


def test_xingbao_passes_when_child_has_passed_and_xingbao_is_ahead() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    game.child_play("yellow", "star_lane")
    game.xingbao_take_turn()
    game.child_pass()
    result = game.xingbao_take_turn()

    assert result.ok is True
    assert result.round_over is True
    assert game.round_winners == ["xingbao"]


def test_invalid_input_is_sanitized_to_shake_head() -> None:
    game = ColorBlockGame(rng=random.Random(1))

    result = game.child_play("servo angle 120", "star_lane")

    assert result.ok is False
    assert result.action == ActionSanitizer().sanitize(
        {"screen_expression": "sad", "arm_action": "shake_head"}
    )
