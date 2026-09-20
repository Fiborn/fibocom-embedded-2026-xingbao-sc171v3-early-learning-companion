"""Feedback suggestions for Xingbao voice/expression side.

The game only proposes high-level whitelist names.  Hardware-specific movement,
LED driving, and voice rendering stay outside the pygame game process.
"""

from .action_schema import sanitize_feedback


INTENT_FEEDBACK = {
    "get_rule": {"screen_expression": "thinking", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "get_goal": {"screen_expression": "thinking", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "get_hint": {"screen_expression": "curious", "arm_action": "stay_still", "led_mode": "yellow_blink"},
    "get_score": {"screen_expression": "smile", "arm_action": "stay_still", "led_mode": "warm_breath"},
    "get_progress": {"screen_expression": "thinking", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "repeat_prompt": {"screen_expression": "thinking", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "restart_round": {"screen_expression": "smile", "arm_action": "wave_hand", "led_mode": "warm_breath"},
    "next_round": {"screen_expression": "thinking", "arm_action": "stay_still", "led_mode": "yellow_blink"},
    "pause_game": {"screen_expression": "sleepy", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "exit_game": {"screen_expression": "smile", "arm_action": "wave_hand", "led_mode": "warm_breath"},
}

EVENT_FEEDBACK = {
    "game_started": {"screen_expression": "smile", "arm_action": "wave_hand", "led_mode": "warm_breath"},
    "round_started": {"screen_expression": "thinking", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "answer_correct": {"screen_expression": "smile", "arm_action": "nod", "led_mode": "warm_breath"},
    "answer_wrong": {"screen_expression": "sad", "arm_action": "stay_still", "led_mode": "yellow_blink"},
    "hint_used": {"screen_expression": "curious", "arm_action": "stay_still", "led_mode": "yellow_blink"},
    "round_completed": {"screen_expression": "smile", "arm_action": "nod", "led_mode": "warm_breath"},
    "game_completed": {"screen_expression": "smile", "arm_action": "small_dance", "led_mode": "rainbow"},
    "idle_timeout": {"screen_expression": "curious", "arm_action": "stay_still", "led_mode": "yellow_blink"},
    "game_paused": {"screen_expression": "sleepy", "arm_action": "stay_still", "led_mode": "blue_breath"},
    "game_exited": {"screen_expression": "smile", "arm_action": "wave_hand", "led_mode": "warm_breath"},
}


def feedback_for_intent(intent):
    return sanitize_feedback(INTENT_FEEDBACK.get(str(intent), {}))


def feedback_for_event(event):
    return sanitize_feedback(EVENT_FEEDBACK.get(str(event), {}))
