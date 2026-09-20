import random

from .base_game import BaseGame, ChoiceResult
from ..difficulty import option_count_for_difficulty, score_multiplier_for_difficulty


class SkillGame(BaseGame):
    game_id = "skill"
    title = "神秘小挑战"
    description = "趣味算术双倍积分"
    success_messages = ("算对啦！", "挑战成功！", "你的计算真准确！")
    error_messages = ("再算一遍试试看。", "别着急，检查一下运算符号。", "差一点，再试一次。")
    parent_tip = "可以鼓励孩子先口算，再从选项中寻找答案。"

    def __init__(self, rounds=5, seed=None, difficulty=1):
        self.rounds = int(rounds)
        self.difficulty = max(1, min(3, int(difficulty)))
        self.option_count = option_count_for_difficulty(self.difficulty)
        self.random = random.Random(seed)
        self.start()

    def start(self):
        self.current_index = 0
        self.completed_rounds = 0
        self.success_count = 0
        self.error_count = 0
        self.hint_count = 0
        self.attempt_count = 0
        required = ["add_sub", "multiply", "divide"]
        self.question_types = []
        while len(self.question_types) < self.rounds:
            batch = list(required)
            self.random.shuffle(batch)
            self.question_types.extend(batch)
        self.question_types = self.question_types[:self.rounds]
        self.options = []
        self.question = ""
        self.question_type = ""
        self.term_count = 0
        self.answer = 0
        self._prepare_round()

    @property
    def current_round_number(self):
        return min(self.completed_rounds + 1, self.rounds)

    @property
    def target_id(self):
        return str(self.answer)

    @property
    def instruction(self):
        return "算一算：{}＝？".format(self.question)

    def _prepare_round(self):
        if self.is_finished():
            self.options = []
            return
        self.question_type = self.question_types[self.current_index]
        if self.question_type == "add_sub":
            self.question, self.answer, self.term_count = self._generate_add_sub()
        elif self.question_type == "multiply":
            left = self.random.randint(2, 9)
            right = self.random.randint(2, 9)
            self.question = "{}×{}".format(left, right)
            self.answer = left * right
            self.term_count = 2
        else:
            answer = self.random.randint(2, 9)
            divisor = self.random.randint(2, 9)
            self.question = "{}÷{}".format(answer * divisor, divisor)
            self.answer = answer
            self.term_count = 2
        self.options = self._generate_options(self.answer)

    def _generate_add_sub(self):
        for _ in range(500):
            term_count = self.random.randint(3, 5)
            operators = ["+", "-"] + [
                self.random.choice(("+", "-")) for _ in range(term_count - 3)
            ]
            self.random.shuffle(operators)
            values = [self.random.randint(15, 30)]
            result = values[0]
            valid = True
            for operator in operators:
                if operator == "+":
                    value = self.random.randint(2, 12)
                    result += value
                else:
                    upper = min(12, result - 1)
                    if upper < 2:
                        valid = False
                        break
                    value = self.random.randint(2, upper)
                    result -= value
                values.append(value)
            if valid and 10 <= result <= 50:
                expression = str(values[0])
                for operator, value in zip(operators, values[1:]):
                    expression += "{}{}".format(operator, value)
                return expression, result, term_count
        return "20+8-5", 23, 3

    def _generate_options(self, answer):
        candidates = {int(answer)}
        offsets = list(range(-12, 13))
        offsets.remove(0)
        self.random.shuffle(offsets)
        for offset in offsets:
            candidate = int(answer) + offset
            if candidate >= 0:
                candidates.add(candidate)
            if len(candidates) >= self.option_count:
                break
        values = list(candidates)
        self.random.shuffle(values)
        return [{"id": str(value), "label": str(value)} for value in values]

    def handle_choice(self, choice):
        choice = str(choice)
        if self.is_finished() or choice not in {item["id"] for item in self.options}:
            return ChoiceResult(choice, self.target_id, False, ignored=True,
                                finished=self.is_finished())
        target = self.target_id
        self.attempt_count += 1
        correct = choice == target
        if correct:
            self.success_count += 1
            self.completed_rounds += 1
            self.current_index = min(self.current_index + 1, self.rounds)
            message = self.random.choice(self.success_messages)
            self._prepare_round()
        else:
            self.error_count += 1
            message = self.random.choice(self.error_messages)
        return ChoiceResult(choice, target, correct, completed_round=correct,
                            finished=self.is_finished(), message=message)

    def request_hint(self):
        self.hint_count += 1
        return {"target": self.target_id, "round": self.current_round_number,
                "hint_count": self.hint_count}

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
            "point_multiplier": 2,
            "score_points": round(self.success_count * 20 * multiplier),
            "encouragement": "你完成了神秘小挑战，获得双倍积分！",
            "parent_tip": self.parent_tip,
        }
