from .base_game import MultipleChoiceGame
from ..difficulty import option_count_for_difficulty


AVAILABLE_COLORS = [
    {"id": "red", "name": "红色", "label": "红色", "en": "RED ENERGY", "asset": "energy_red", "rgb": (226, 99, 96)},
    {"id": "yellow", "name": "黄色", "label": "黄色", "en": "YELLOW ENERGY", "asset": "energy_yellow", "rgb": (246, 202, 92)},
    {"id": "blue", "name": "蓝色", "label": "蓝色", "en": "BLUE ENERGY", "asset": "energy_blue", "rgb": (103, 166, 220)},
    {"id": "green", "name": "绿色", "label": "绿色", "en": "GREEN ENERGY", "asset": "energy_green", "rgb": (104, 186, 135)},
    {"id": "purple", "name": "紫色", "label": "紫色", "en": "PURPLE ENERGY", "asset": "energy_purple", "rgb": (165, 134, 199)},
    {"id": "orange", "name": "橙色", "label": "橙色", "en": "ORANGE ENERGY", "asset": "energy_orange", "rgb": (238, 157, 92)},
]


class ColorGame(MultipleChoiceGame):
    game_id = "color"
    title = "找颜色"
    description = "认识红黄蓝绿"
    all_items = AVAILABLE_COLORS
    success_messages = (
        "太棒啦，你找对了！",
        "星宝给你点赞！",
        "颜色小侦探成功啦！",
    )
    error_messages = (
        "没关系，我们再看看。",
        "再试一次，你可以的。",
        "星宝陪你慢慢找。",
    )
    parent_tip = "可以在生活中继续找一找不同颜色的小物品。"

    def __init__(self, rounds=5, seed=None, difficulty=1):
        self.difficulty = max(1, min(3, int(difficulty)))
        self.all_items = AVAILABLE_COLORS
        super().__init__(rounds=rounds, seed=seed,
                         option_count=option_count_for_difficulty(self.difficulty))

    @property
    def available_colors(self):
        return self.options

    def select_color(self, selected):
        return self.handle_choice(selected)

    def summary(self):
        return self.get_summary()
