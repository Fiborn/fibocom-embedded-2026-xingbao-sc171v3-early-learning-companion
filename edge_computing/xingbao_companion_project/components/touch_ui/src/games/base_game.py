from dataclasses import dataclass
import random

from ..difficulty import score_multiplier_for_difficulty


@dataclass
class ChoiceResult:
    selected: str
    target: str
    correct: bool
    completed_round: bool = False
    finished: bool = False
    ignored: bool = False
    message: str = ""

    def to_payload(self):
        return {
            "selected": self.selected,
            "target": self.target,
            "correct": self.correct,
            "completed_round": self.completed_round,
            "finished": self.finished,
            "ignored": self.ignored,
        }


class BaseGame:
    game_id = "base"
    title = ""
    description = ""
    rounds = 0

    def start(self):
        raise NotImplementedError

    def update(self, dt):
        return None

    def handle_choice(self, choice):
        raise NotImplementedError

    def is_finished(self):
        raise NotImplementedError

    def get_summary(self):
        raise NotImplementedError


class MultipleChoiceGame(BaseGame):
    all_items = ()
    success_messages = ()
    error_messages = ()
    parent_tip = ""

    def __init__(self, rounds=5, seed=None, option_count=4):
        self.rounds = int(rounds)
        self.option_count = max(2, int(option_count))
        self.random = random.Random(seed)
        self.start()

    def start(self):
        self.current_index = 0
        self.completed_rounds = 0
        self.success_count = 0
        self.error_count = 0
        self.hint_count = 0
        self.attempt_count = 0
        item_ids = [item["id"] for item in self.all_items]
        self.targets = []
        while len(self.targets) < self.rounds:
            batch = list(item_ids)
            self.random.shuffle(batch)
            self.targets.extend(batch)
        self.targets = self.targets[:self.rounds]
        self.options = []
        self._prepare_options()

    @property
    def current_round_number(self):
        return min(self.completed_rounds + 1, self.rounds)

    @property
    def target_id(self):
        if self.is_finished():
            return self.targets[-1]
        return self.targets[self.current_index]

    def _prepare_options(self):
        if self.is_finished():
            self.options = []
            return
        target = next(item for item in self.all_items if item["id"] == self.target_id)
        others = [item for item in self.all_items if item["id"] != self.target_id]
        self.random.shuffle(others)
        self.options = [target] + others[:self.option_count - 1]
        self.random.shuffle(self.options)

    def handle_choice(self, choice):
        if self.is_finished() or choice not in {item["id"] for item in self.options}:
            return ChoiceResult(str(choice), self.target_id, False, ignored=True, finished=self.is_finished())

        target = self.target_id
        self.attempt_count += 1
        correct = choice == target
        if correct:
            self.success_count += 1
            self.completed_rounds += 1
            self.current_index = min(self.current_index + 1, self.rounds)
            message = self.random.choice(self.success_messages)
            self._prepare_options()
        else:
            self.error_count += 1
            message = self.random.choice(self.error_messages)

        return ChoiceResult(
            selected=choice,
            target=target,
            correct=correct,
            completed_round=correct,
            finished=self.is_finished(),
            message=message,
        )

    def request_hint(self):
        self.hint_count += 1
        return {"target": self.target_id, "round": self.current_round_number, "hint_count": self.hint_count}

    def is_finished(self):
        return self.completed_rounds >= self.rounds

    def get_summary(self):
        difficulty = max(1, min(3, int(getattr(self, "difficulty", 3))))
        multiplier = score_multiplier_for_difficulty(difficulty)
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
            "difficulty": difficulty,
            "score_multiplier": multiplier,
            "score_points": round(self.success_count * 10 * multiplier),
            "encouragement": "你和星宝完成了{}！".format(self.title),
            "parent_tip": self.parent_tip,
        }
