"""Structured command API between Xingbao voice side and touch games."""

from __future__ import annotations

from .feedback_policy import feedback_for_event, feedback_for_intent
from .states import AppState


GAME_ID_TO_INTERNAL = {
    "color_game": "color",
    "shape_game": "shape",
    "memory_game": "memory",
    "counting_game": "counting",
    "english_game": "english",
    "skill_game": "skill",
    "color": "color",
    "shape": "shape",
    "memory": "memory",
    "counting": "counting",
    "english": "english",
    "skill": "skill",
}

INTERNAL_TO_GAME_ID = {
    "color": "color_game",
    "shape": "shape_game",
    "memory": "memory_game",
    "counting": "counting_game",
    "english": "english_game",
    "skill": "skill_game",
}

SUPPORTED_INTENTS = {
    "get_rule",
    "get_goal",
    "get_hint",
    "get_score",
    "get_stars",
    "get_progress",
    "get_remaining",
    "get_round",
    "get_current_game",
    "get_status",
    "get_level",
    "get_energy",
    "get_correct",
    "get_errors",
    "get_attempts",
    "repeat_prompt",
    "restart_round",
    "next_round",
    "pause_game",
    "exit_game",
}

SUPPORTED_EVENTS = {
    "game_started",
    "round_started",
    "answer_correct",
    "answer_wrong",
    "hint_used",
    "round_completed",
    "game_completed",
    "idle_timeout",
    "game_paused",
    "game_exited",
}

RULES = {
    "color": "根据提示找到正确颜色能量。",
    "shape": "根据提示找到正确图形信号。",
    "memory": "先看星星亮起的顺序，再按顺序点一遍。",
    "counting": "数清楚物体数量，再点击对应数字。",
    "english": "根据题目完成中译英或英译中选择。",
    "skill": "观察方向或动作指令，点击对应符号。",
}

QUESTION_CONTEXT_KEYS = {
    "current_goal",
    "round",
    "target_color",
    "available_colors",
    "selected_color",
    "target_shape",
    "available_shapes",
    "selected_shape",
    "phase",
    "sequence_length",
    "input_index",
    "target_position",
    "positions",
    "object_count",
    "available_numbers",
    "direction",
    "available_words",
    "question_type",
    "available_answers",
}


def normalize_game_id(game_id):
    return GAME_ID_TO_INTERNAL.get(str(game_id or ""))


def external_game_id(internal_id):
    return INTERNAL_TO_GAME_ID.get(str(internal_id), str(internal_id))


def build_mini_game_state(game_id, status, current_goal="", round=0, message="",
                          feedback=None, available_actions=None, **extra):
    """Unified state envelope for existing and future mini games."""
    payload = {
        "type": "mini_game_state", "game_id": game_id, "status": status,
        "current_goal": current_goal, "round": int(round or 0), "message": message,
        "feedback": feedback or {}, "available_actions": list(available_actions or []),
    }
    payload.update(extra)
    return payload


def build_mini_game_response(game_id, status, current_goal="", round=0, message="",
                             feedback=None, available_actions=None, **extra):
    """Unified response; event/state producers use the same required fields."""
    payload = build_mini_game_state(game_id, status, current_goal, round, message,
                                    feedback, available_actions, **extra)
    payload["type"] = "game_response"
    return payload


def _item_label(game, item_id):
    for item in getattr(game, "all_items", []):
        if item["id"] == item_id:
            return item.get("label") or item.get("name") or item_id
    return str(item_id)


def _score(game):
    return int(getattr(game, "success_count", 0)) * 10


def _common_state(app, game):
    state = {
        "game_id": external_game_id(game.game_id),
        "name": game.title,
        "rule": RULES.get(game.game_id, ""),
        "score": int(getattr(app, "current_score", _score(game))),
        "stars": int(getattr(game, "success_count", 0)),
        "total_stars": int(getattr(app.records, "star_count", 0)),
        "level": getattr(app.records, "level", 1),
        "level_title": getattr(app.records, "level_title", ""),
        "energy": getattr(app.records, "energy", 0),
        "energy_max": getattr(app.records, "energy_max", 100),
        "max_level": 100,
        "round": game.current_round_number,
        "remaining_rounds": max(0, game.rounds - getattr(game, "completed_rounds", 0)),
        "total_rounds": getattr(game, "rounds", 0),
        "success_count": int(getattr(game, "success_count", 0)),
        "error_count": int(getattr(game, "error_count", 0)),
        "wrong_count": int(getattr(game, "wrong_count", getattr(game, "error_count", 0))),
        "attempt_count": int(getattr(game, "attempt_count", 0)),
        "last_result": None,
        "hint_count": getattr(game, "hint_count", 0),
        "paused": bool(getattr(app, "voice_paused", False)),
        "supported_intents": sorted(SUPPORTED_INTENTS),
    }
    support = getattr(app, "first_mistake_support", None)
    if support is not None:
        public_state = support.public_state()
        if public_state:
            state["companion_support"] = public_state
    return state


def _with_ui_context(app, state):
    ui_state = getattr(getattr(app, "state", None), "value", "UNKNOWN")
    game = getattr(app, "game", None)
    question_id = None
    question_prompt = ""
    if ui_state == AppState.GAME_FEEDBACK.value:
        question_id = getattr(app, "feedback_question_id", None)
        question_prompt = getattr(app, "feedback_question_prompt", "")
        feedback_state = getattr(app, "feedback_question_state", {})
        if isinstance(feedback_state, dict):
            for key in QUESTION_CONTEXT_KEYS:
                if key in feedback_state:
                    state[key] = feedback_state[key]
        if question_prompt:
            state["current_goal"] = question_prompt
    elif game is not None and not game.is_finished():
        question_id = app.current_question_id()
        question_prompt = app._game_prompt()
    speech = dict(getattr(app, "speech_state", {}) or {})
    state.update({
        "ui_state": ui_state,
        "page_state": str(ui_state).lower(),
        "question_id": question_id,
        "question_prompt": question_prompt,
        "speech": {
            "utterance_id": speech.get("utterance_id"),
            "role": speech.get("role", "idle"),
            "status": speech.get("status", "idle"),
            "page_state": speech.get("page_state"),
            "question_id": speech.get("question_id"),
            "error": speech.get("error"),
        },
    })
    return state


def get_game_state(app):
    game = getattr(app, "game", None)
    if game is None:
        return _with_ui_context(app, {
            "game_id": None,
            "name": "无进行中的游戏",
            "rule": "",
            "current_goal": "请先选择一个小游戏。",
            "score": 0,
            "stars": 0,
            "total_stars": int(getattr(app.records, "star_count", 0)),
            "level": getattr(app.records, "level", 1),
            "level_title": getattr(app.records, "level_title", ""),
            "energy": getattr(app.records, "energy", 0),
            "energy_max": getattr(app.records, "energy_max", 100),
            "max_level": 100,
            "round": 0,
            "remaining_rounds": 0,
            "total_rounds": 0,
            "success_count": 0,
            "error_count": 0,
            "wrong_count": 0,
            "attempt_count": 0,
            "last_result": None,
            "hint_count": 0,
            "paused": False,
            "supported_intents": sorted(SUPPORTED_INTENTS),
        })
    state = _common_state(app, game)
    if game.game_id == "color":
        label = _item_label(game, game.target_id)
        state.update({
            "current_goal": "找到{}能量".format(label),
            "target_color": game.target_id,
            "available_colors": [item["id"] for item in game.options],
            "selected_color": None,
        })
    elif game.game_id == "shape":
        label = _item_label(game, game.target_id)
        state.update({
            "current_goal": "找到{}".format(label),
            "target_shape": game.target_id,
            "available_shapes": [item["id"] for item in game.options],
            "selected_shape": None,
        })
    elif game.game_id == "memory":
        sequence = list(getattr(game, "current_sequence", []))
        state.update({
            "current_goal": (
                "看星星亮起的顺序" if game.phase == "showing"
                else "按刚才的顺序点击星点"
            ),
            "phase": game.phase,
            "sequence_length": len(sequence),
            "input_index": getattr(game, "input_index", 0),
            "target_position": game.target_id,
            "positions": ["0", "1", "2", "3"],
        })
    elif game.game_id == "counting":
        state.update({
            "current_goal": "数一数并选择正确数字",
            "object_count": game.object_count,
            "available_numbers": [item["id"] for item in game.options],
        })
    elif game.game_id == "english":
        state.update({
            "current_goal": game.question,
            "direction": game.direction,
            "available_words": [item["label"] for item in game.options],
        })
    elif game.game_id == "skill":
        state.update({
            "current_goal": game.instruction,
            "question_type": game.question_type,
            "available_answers": [item["id"] for item in game.options],
        })
    return _with_ui_context(app, state)


def _response(command, ok, message, state, feedback=None, error=None):
    payload = {
        "type": "game_response",
        "ok": bool(ok),
        "game_id": str(command.get("game_id") or state.get("game_id") or ""),
        "intent": str(command.get("intent") or ""),
        "message": str(message),
        "state": state,
    }
    if feedback is not None:
        payload["feedback"] = feedback
    if error is not None:
        payload["error"] = error
    return payload


def build_game_event(app, event, message=None, state=None, game_id=None, feedback=None):
    state = dict(state or get_game_state(app))
    event = str(event or "")
    payload = {
        "type": "game_event",
        "game_id": str(game_id or state.get("game_id") or ""),
        "event": event,
        "message": str(message if message is not None else ""),
        "state": state,
        "feedback": feedback or feedback_for_event(event),
    }
    if event not in SUPPORTED_EVENTS:
        payload["warning"] = {"code": "unknown_event", "detail": "事件不在建议白名单内。"}
    return payload


def _error(command, code, message, state=None, detail=None):
    return _response(
        command,
        False,
        message,
        state or {},
        feedback=feedback_for_intent(command.get("intent")),
        error={"code": code, "detail": detail or message},
    )


def _ensure_current_game(app, command):
    raw_game_id = str(command.get("game_id") or "")
    game = getattr(app, "game", None)
    if raw_game_id in {"", "current_game", "current"} and game is not None:
        internal = getattr(game, "game_id", None)
    else:
        internal = normalize_game_id(command.get("game_id"))
    if internal is None:
        return None, _error(command, "missing_data", "未知游戏ID。", get_game_state(app))
    if game is None or getattr(game, "game_id", None) != internal:
        return None, _error(command, "not_available", "当前没有打开这个游戏。", get_game_state(app))
    return game, None


class GameCommandAdapter:
    def __init__(self, app):
        self.app = app

    def handle_command(self, command: dict) -> dict:
        return handle_command(self.app, command)

    def build_event(self, event, message=None, state=None, game_id=None, feedback=None) -> dict:
        return build_game_event(self.app, event, message=message, state=state,
                                game_id=game_id, feedback=feedback)


def handle_command(app, command: dict) -> dict:
    command = dict(command or {})
    intent = str(command.get("intent") or "")
    if command.get("type") != "game_command":
        return _error(command, "missing_data", "命令类型必须是game_command。", get_game_state(app))
    if intent not in SUPPORTED_INTENTS:
        return _error(command, "unknown_intent", "这个语音意图当前游戏不支持。", get_game_state(app))

    game, error = _ensure_current_game(app, command)
    if error:
        return error

    if intent == "restart_round":
        app.start_game(game.game_id)
        state = get_game_state(app)
        return _response(command, True, "本轮已经重新开始。", state, feedback_for_intent(intent))

    if intent == "next_round":
        state = get_game_state(app)
        return _error(command, "not_available", "请先完成当前这一轮，再进入下一轮。", state)

    if intent == "pause_game":
        app.voice_paused = True
        state = get_game_state(app)
        state["paused"] = True
        return _response(command, True, "游戏已暂停。", state, feedback_for_intent(intent))

    if intent == "exit_game":
        state = get_game_state(app)
        state["exited"] = True
        app.go_home()
        return _response(command, True, "游戏已退出。", state, feedback_for_intent(intent))

    if intent == "get_hint":
        app.request_hint()
        state = get_game_state(app)
        return _response(command, True, "提示：{}".format(state["current_goal"]), state, feedback_for_intent(intent))

    state = get_game_state(app)
    messages = {
        "get_rule": state.get("rule", ""),
        "get_goal": state.get("current_goal", ""),
        "repeat_prompt": state.get("current_goal", ""),
        "get_stars": "你现在有{}颗星。".format(state.get("stars", 0)),
        "get_score": "你现在有{}分。".format(state.get("score", 0)),
        "get_progress": "现在是第{}轮，还剩{}轮。".format(
            state.get("round", 0), state.get("remaining_rounds", 0)
        ),
        "get_remaining": "现在还剩{}轮。".format(state.get("remaining_rounds", 0)),
        "get_round": "现在是第{}轮，一共有{}轮。".format(
            state.get("round", 0), state.get("total_rounds", 0)
        ),
        "get_current_game": "我们正在玩{}。".format(state.get("name", "当前小游戏")),
        "get_status": "正在玩{}，第{}轮，还剩{}轮，已经有{}颗星。".format(
            state.get("name", "当前小游戏"),
            state.get("round", 0),
            state.get("remaining_rounds", 0),
            state.get("stars", 0),
        ),
        "get_level": "星宝现在是{}级，{}。".format(
            state.get("level", 1), state.get("level_title", "")
        ).strip("，。") + "。",
        "get_energy": "星宝现在有{}点能量，满能量是{}点。".format(
            state.get("energy", 0), state.get("energy_max", 100)
        ),
        "get_correct": "你现在答对了{}次。".format(state.get("success_count", 0)),
        "get_errors": "你现在答错了{}次。".format(
            state.get("wrong_count", state.get("error_count", 0))
        ),
        "get_attempts": "你已经尝试了{}次。".format(state.get("attempt_count", 0)),
    }
    return _response(command, True, messages.get(intent, ""), state, feedback_for_intent(intent))
