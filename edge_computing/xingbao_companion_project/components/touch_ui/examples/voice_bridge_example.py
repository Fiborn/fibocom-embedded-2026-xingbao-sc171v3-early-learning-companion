"""语音同学可直接复制：把识别结果映射为固定intent后交给游戏。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game_api import GameCommandAdapter


PHRASE_TO_INTENT = {
    "怎么玩": "get_rule",
    "规则是什么": "get_rule",
    "要做什么": "get_goal",
    "现在要做什么": "get_goal",
    "应该点哪个": "get_goal",
    "我不会": "get_hint",
    "提示一下": "get_hint",
    "给点线索": "get_hint",
    "我有几颗星": "get_stars",
    "现在有几颗星": "get_stars",
    "拿到几颗星": "get_stars",
    "我有多少分": "get_score",
    "现在多少分": "get_score",
    "进度怎么样": "get_progress",
    "玩到哪里了": "get_progress",
    "还有几题": "get_remaining",
    "还剩多少题": "get_remaining",
    "现在第几题": "get_round",
    "现在第几关": "get_round",
    "现在什么游戏": "get_current_game",
    "我现在怎么样": "get_status",
    "现在几级": "get_level",
    "还有多少能量": "get_energy",
    "答对几个": "get_correct",
    "错了几个": "get_errors",
    "试了几次": "get_attempts",
    "再说一次": "repeat_prompt",
    "重新来": "restart_round",
    "下一题": "next_round",
    "暂停": "pause_game",
    "不玩了": "exit_game",
}


def handle_child_speech(app, game_id, child_text, intent=None):
    """必须在UI主线程调用；返回内容中的message可直接交给TTS。"""
    resolved_intent = intent or PHRASE_TO_INTENT.get(child_text)
    if not resolved_intent:
        return {
            "type": "game_response",
            "ok": False,
            "game_id": game_id,
            "intent": "",
            "message": "星宝还没听懂，可以再说一次吗？",
            "state": {},
            "error": {"code": "unknown_intent", "detail": "语音侧未匹配固定intent"},
        }
    command = {
        "type": "game_command",
        "game_id": game_id,
        "intent": resolved_intent,
        "user_text": child_text,
        "context": {"source": "voice", "child_age_group": "preschool"},
    }
    return GameCommandAdapter(app).handle_command(command)


def speak_response(tts_speak, response):
    """tts_speak示例：你们现有的离线TTS函数。"""
    if response.get("message"):
        tts_speak(response["message"])
    return response.get("feedback", {})
