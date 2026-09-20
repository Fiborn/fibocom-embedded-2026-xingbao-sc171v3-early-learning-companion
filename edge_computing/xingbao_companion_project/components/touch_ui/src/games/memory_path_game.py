import random

from .base_game import BaseGame, ChoiceResult
from ..difficulty import clamp_age_level
from ..difficulty import score_multiplier_for_difficulty


MEMORY_FLASH_DURATION = 0.8
MEMORY_FLASH_GAP = 0.4
MEMORY_BEFORE_INPUT_DELAY = 0.5
DEMO_MEMORY_FLASH_DURATION = 1.0
DEMO_MEMORY_FLASH_GAP = 0.5
DEMO_MEMORY_BEFORE_INPUT_DELAY = 0.5


def generate_memory_sequence(length, positions, rng=None):
    positions = list(positions)
    length = max(0, int(length))
    if not positions:
        return []
    if len(positions) == 1:
        return [positions[0]] * length

    rng = rng or random
    sequence = []
    for _ in range(length):
        unused_choices = [
            position for position in positions
            if position not in sequence and (not sequence or position != sequence[-1])
        ]
        choices = unused_choices or [
            position for position in positions
            if not sequence or position != sequence[-1]
        ]
        sequence.append(rng.choice(choices))
    return sequence


class MemoryPathGame(BaseGame):
    game_id = "memory"
    title = "记忆小路"
    description = "按顺序点一遍"
    rounds = 4

    def __init__(self, seed=None, sequence_lengths=None, demo_timing=False, timing=None,
                 difficulty=1):
        self.random = random.Random(seed)
        self.difficulty = max(1, min(3, int(difficulty)))
        defaults = {1: [2, 2, 2, 2], 2: [3, 3, 3, 3],
                    3: [4, 4, 4, 4]}
        self.sequence_lengths = list(sequence_lengths or defaults[self.difficulty])
        self.rounds = len(self.sequence_lengths)
        timing = timing or {}
        self.flash_duration = timing.get("memory_flash", DEMO_MEMORY_FLASH_DURATION) if demo_timing else MEMORY_FLASH_DURATION
        self.flash_gap = timing.get("memory_gap", DEMO_MEMORY_FLASH_GAP) if demo_timing else MEMORY_FLASH_GAP
        self.before_input_delay = timing.get("memory_before_input", DEMO_MEMORY_BEFORE_INPUT_DELAY) if demo_timing else MEMORY_BEFORE_INPUT_DELAY
        self.start()

    def start(self):
        self.completed_rounds = 0
        self.success_count = 0
        self.error_count = 0
        self.hint_count = 0
        self.attempt_count = 0
        self.round_error_count = 0
        self.input_index = 0
        self.current_sequence = self._new_sequence()
        self._start_showing()

    @property
    def current_round_number(self):
        return min(self.completed_rounds + 1, self.rounds)

    @property
    def target_id(self):
        return self.current_sequence[self.input_index] if self.phase == "input" else "sequence"

    def _new_sequence(self):
        if self.completed_rounds >= self.rounds:
            return []
        length = self.sequence_lengths[self.completed_rounds]
        return generate_memory_sequence(length, ["0", "1", "2", "3"], self.random)

    def _start_showing(self):
        self.phase = "showing"
        self.playback_phase = "flash"
        self._show_index = 0
        self.highlighted = self.current_sequence[0] if self.current_sequence else None
        self._show_timer = self.flash_duration
        self.input_index = 0

    def update(self, dt):
        if self.phase != "showing" or self.is_finished():
            return
        remaining = max(0.0, float(dt))
        while self.phase == "showing" and remaining >= self._show_timer:
            remaining -= self._show_timer
            self._advance_playback()
        if self.phase == "showing":
            self._show_timer -= remaining

    def _advance_playback(self):
        if self.playback_phase == "flash":
            self.playback_phase = "gap"
            self.highlighted = None
            self._show_timer = self.flash_gap
            return
        if self.playback_phase == "gap":
            self._show_index += 1
            if self._show_index < len(self.current_sequence):
                self.playback_phase = "flash"
                self.highlighted = self.current_sequence[self._show_index]
                self._show_timer = self.flash_duration
            else:
                self.playback_phase = "before_input"
                self.highlighted = None
                self._show_timer = self.before_input_delay
            return
        self.phase = "input"
        self.input_index = 0
        self.highlighted = None
        self._show_timer = 0.0

    def handle_choice(self, choice):
        choice = str(choice)
        if self.phase != "input" or self.is_finished():
            return ChoiceResult(
                choice,
                self.target_id,
                False,
                ignored=True,
                finished=self.is_finished(),
                message="先看完星星亮起哦。",
            )

        target = self.current_sequence[self.input_index]
        self.attempt_count += 1
        if choice != target:
            self.error_count += 1
            self.round_error_count += 1
            if self.round_error_count > 2:
                self.hint_count += 1
                self.completed_rounds += 1
                completed = True
                message = "没关系，这一轮星宝来帮忙。"
                if self.is_finished():
                    self.phase = "finished"
                    self.current_sequence = []
                else:
                    self.round_error_count = 0
                    self.current_sequence = self._new_sequence()
                    self._start_showing()
            else:
                completed = False
                message = "差一点点，我们再看一遍。"
                self._start_showing()
            return ChoiceResult(choice, target, False, completed_round=completed, finished=self.is_finished(), message=message)

        self.input_index += 1
        if self.input_index < len(self.current_sequence):
            return ChoiceResult(choice, target, True, message="继续按顺序点哦。")

        self.success_count += 1
        self.completed_rounds += 1
        if self.is_finished():
            self.phase = "finished"
            self.current_sequence = []
        else:
            self.round_error_count = 0
            self.current_sequence = self._new_sequence()
            self._start_showing()
        return ChoiceResult(
            choice,
            target,
            True,
            completed_round=True,
            finished=self.is_finished(),
            message="顺序记住啦，太棒了！",
        )

    def request_hint(self):
        self.hint_count += 1
        self._start_showing()
        return {"round": self.current_round_number, "hint_count": self.hint_count}

    def is_finished(self):
        return self.completed_rounds >= self.rounds

    def get_summary(self):
        multiplier = score_multiplier_for_difficulty(self.difficulty)
        return {
            "game_id": self.game_id,
            "game_name": self.title,
            "completed_rounds": self.completed_rounds,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "wrong_count": self.error_count,
            "hint_count": self.hint_count,
            "attempt_count": self.attempt_count,
            "stars": self.success_count,
            "difficulty": self.difficulty,
            "score_multiplier": multiplier,
            "score_points": round(self.success_count * 10 * multiplier),
            "encouragement": "你和星宝一起点亮了记忆小路！",
            "parent_tip": "可以用两到四个动作，和孩子玩一玩顺序模仿。",
        }
