from .base_game import MultipleChoiceGame
from ..difficulty import option_count_for_difficulty


NUMBER_ITEMS = [{"id": str(value), "label": str(value)} for value in range(4, 16)]


class CountingGame(MultipleChoiceGame):
    game_id = "counting"
    title = "数数星球"
    description = "数一数有几颗星星"
    all_items = NUMBER_ITEMS
    success_messages = ("数对啦！", "星宝为你鼓掌！", "你真厉害！")
    error_messages = ("没关系，再数一数。", "星宝陪你慢慢数。", "再看一看哦。")
    parent_tip = "可以用积木或水果继续练习数量对应。"

    def __init__(self, rounds=5, seed=None, difficulty=1):
        self.difficulty = max(1, min(3, int(difficulty)))
        self.all_items = NUMBER_ITEMS
        super().__init__(rounds=rounds, seed=seed,
                         option_count=option_count_for_difficulty(self.difficulty))

    @property
    def object_count(self):
        return int(self.target_id)

    def _prepare_options(self):
        super()._prepare_options()
        option_count = option_count_for_difficulty(self.difficulty)
        target = next(item for item in self.all_items if item["id"] == self.target_id)
        others = [item for item in self.all_items if item["id"] != self.target_id]
        self.random.shuffle(others)
        self.options = [target] + others[:option_count - 1]
        self.random.shuffle(self.options)
