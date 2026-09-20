from .base_game import MultipleChoiceGame
from ..difficulty import option_count_for_difficulty


AVAILABLE_SHAPES = [
    {"id": "circle", "label": "圆形"},
    {"id": "triangle", "label": "三角形"},
    {"id": "square", "label": "正方形"},
    {"id": "star", "label": "星形"},
    {"id": "heart", "label": "爱心"},
    {"id": "rectangle", "label": "长方形"},
    {"id": "ellipse", "label": "椭圆形"},
]


class ShapeGame(MultipleChoiceGame):
    game_id = "shape"
    title = "认形状"
    description = "找出目标图形"
    all_items = AVAILABLE_SHAPES
    success_messages = ("找到了，就是它！", "你的小眼睛真亮！", "星宝也看到这个图形啦！")
    error_messages = ("这个不是哦，再看一看。", "没关系，我们换个角度看看。", "星宝陪你再找一次。")
    parent_tip = "可以和孩子一起找一找生活中的各种图形。"

    def __init__(self, rounds=5, seed=None, difficulty=1):
        self.difficulty = max(1, min(3, int(difficulty)))
        self.all_items = AVAILABLE_SHAPES
        super().__init__(rounds=rounds, seed=seed,
                         option_count=option_count_for_difficulty(self.difficulty))
        # A consistent first concept reduces cognitive load for every child and
        # makes the reviewed hint ("three corners") universally available.
        if self.targets and self.targets[0] != "triangle":
            try:
                triangle_index = self.targets.index("triangle")
            except ValueError:
                self.targets[0] = "triangle"
            else:
                self.targets[0], self.targets[triangle_index] = (
                    self.targets[triangle_index],
                    self.targets[0],
                )
            self._prepare_options()
