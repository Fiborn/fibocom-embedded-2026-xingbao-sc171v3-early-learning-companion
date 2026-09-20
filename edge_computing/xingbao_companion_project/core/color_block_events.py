"""Bridge color block game results into Xingbao coordination events."""

from __future__ import annotations

from typing import Any

from core.color_block_game import ColorBlockGame, MoveResult
from core.color_block_voice import ColorBlockVoiceCommand


def color_block_result_event(
    result: MoveResult,
    *,
    game: ColorBlockGame,
    source: str = "color_block_game",
    command_text: str = "",
) -> dict[str, Any]:
    """Convert a game result into a Xingbao expression request event."""
    action = result.action.as_dict()
    return {
        "type": "xingbao_expression_request",
        "source": source,
        "priority": 2 if result.game_over or result.round_over else 1,
        "payload": {
            "intent": _intent_for_result(result),
            "text": result.message,
            "screen_text": _screen_text(result),
            "emotion": _emotion_for_action(action, result),
            "tts": True,
            "interrupt_policy": "queue",
            "game_id": "color_block_game",
            "command_text": command_text,
            "game_state": game.snapshot(),
            "action": action,
            "round_over": result.round_over,
            "game_over": result.game_over,
            "ok": result.ok,
        },
    }


def color_block_command_event(
    command: ColorBlockVoiceCommand,
    *,
    source: str = "color_block_game",
    command_text: str = "",
) -> dict[str, Any]:
    """Convert a parsed non-move command into a Xingbao expression request."""
    return {
        "type": "xingbao_expression_request",
        "source": source,
        "priority": 1,
        "payload": {
            "intent": f"color_block_{command.intent}",
            "text": command.message,
            "screen_text": command.message[:24],
            "emotion": "thinking" if command.intent == "hint" else "curious",
            "tts": True,
            "interrupt_policy": "queue",
            "game_id": "color_block_game",
            "command_text": command_text,
            "ok": command.intent != "unknown",
        },
    }


def _intent_for_result(result: MoveResult) -> str:
    if not result.ok:
        return "game_retry"
    if result.game_over:
        return "game_finished"
    if result.round_over:
        return "round_finished"
    return "game_feedback"


def _emotion_for_action(action: dict[str, str], result: MoveResult) -> str:
    if not result.ok:
        return "thinking"
    expression = action.get("screen_expression", "")
    if expression in {"smile", "happy"}:
        return "happy"
    if expression in {"sad", "curious", "thinking"}:
        return expression
    return "smile"


def _screen_text(result: MoveResult) -> str:
    if result.game_over:
        return "游戏完成"
    if result.round_over:
        return "回合完成"
    if not result.ok:
        return "再试一次"
    return result.message[:24]
