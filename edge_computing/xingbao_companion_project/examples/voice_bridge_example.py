"""Voice-side example: map child speech to fixed game intents."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game_api import GameCommandAdapter


PHRASE_TO_INTENT = {
    "怎么玩": "get_rule",
    "要做什么": "get_goal",
    "我不会": "get_hint",
    "提示一下": "get_hint",
    "我有多少分": "get_score",
    "还有几题": "get_progress",
    "再说一次": "repeat_prompt",
    "重新来": "restart_round",
    "下一题": "next_round",
    "暂停": "pause_game",
    "不玩了": "exit_game",
}


def handle_child_speech(
    app: Any,
    game_id: str,
    child_text: str,
    intent: str | None = None,
) -> dict[str, Any]:
    """Call this on the UI/game main thread after ASR intent recognition."""
    resolved_intent = intent or PHRASE_TO_INTENT.get(child_text)
    if not resolved_intent:
        return {
            "type": "game_response",
            "ok": False,
            "game_id": game_id,
            "intent": "",
            "message": "星宝还没听懂，可以再说一次吗？",
            "state": {},
            "feedback": {"screen_expression": "thinking", "led_mode": "blue_breath"},
            "error": {"code": "unknown_intent", "detail": "语音侧未匹配固定 intent"},
        }

    command = {
        "type": "game_command",
        "game_id": game_id,
        "intent": resolved_intent,
        "user_text": child_text,
        "context": {"source": "voice", "child_age_group": "preschool"},
    }
    return GameCommandAdapter(app).handle_command(command)


def speak_response(
    tts_speak: Callable[[str], None],
    response: dict[str, Any],
) -> dict[str, Any]:
    """Send response.message to the current TTS function and return feedback."""
    if response.get("message"):
        tts_speak(str(response["message"]))
    feedback = response.get("feedback", {})
    return feedback if isinstance(feedback, dict) else {}
