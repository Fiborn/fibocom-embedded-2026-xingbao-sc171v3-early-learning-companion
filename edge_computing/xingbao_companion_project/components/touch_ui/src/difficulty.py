"""Shared child-friendly difficulty progression for all game modules."""

AGE_LEVELS = [
    {"id": "level_1", "name": "启蒙", "age": "2-3岁"},
    {"id": "level_2", "name": "成长", "age": "3-4岁"},
    {"id": "level_3", "name": "进阶", "age": "4-5岁"},
    {"id": "level_4", "name": "挑战", "age": "5-6岁"},
]

PLAYER_DIFFICULTIES = [
    {"id": 1, "name": "轻松玩", "subtitle": "2选1", "option_count": 2},
    {"id": 2, "name": "认真想", "subtitle": "4选1", "option_count": 4},
    {"id": 3, "name": "勇敢挑战", "subtitle": "6选1", "option_count": 6},
]

MODULE_IDS = ("color", "shape", "memory", "counting", "english", "skill")


def clamp_age_level(level):
    try:
        return max(1, min(4, int(level)))
    except (TypeError, ValueError):
        return 1


def age_level_for_xingbao_level(level):
    """Unlock one education tier every 10 Xingbao levels."""
    try:
        level = max(1, int(level))
    except (TypeError, ValueError):
        level = 1
    if level >= 31:
        return 4
    if level >= 21:
        return 3
    if level >= 11:
        return 2
    return 1


def age_level_meta(level):
    return dict(AGE_LEVELS[clamp_age_level(level) - 1])


def option_count_for_difficulty(level):
    try:
        index = max(1, min(3, int(level))) - 1
    except (TypeError, ValueError):
        index = 0
    return PLAYER_DIFFICULTIES[index]["option_count"]


def score_multiplier_for_difficulty(level):
    try:
        level = max(1, min(3, int(level)))
    except (TypeError, ValueError):
        level = 1
    return {1: 0.5, 2: 2.0 / 3.0, 3: 1.0}[level]


def default_module_progress():
    return {
        module_id: {"level": 1, "success": 0, "attempts": 0}
        for module_id in MODULE_IDS
    }
