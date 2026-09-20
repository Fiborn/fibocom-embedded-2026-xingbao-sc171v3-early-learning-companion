from .base_game import MultipleChoiceGame
from ..difficulty import option_count_for_difficulty


_WORDS = [
    ("apple", "苹果"), ("banana", "香蕉"), ("orange", "橙子"), ("pear", "梨"),
    ("grape", "葡萄"), ("watermelon", "西瓜"), ("strawberry", "草莓"), ("peach", "桃子"),
    ("milk", "牛奶"), ("water", "水"), ("bread", "面包"), ("rice", "米饭"),
    ("egg", "鸡蛋"), ("cake", "蛋糕"), ("candy", "糖果"), ("fish", "鱼"),
    ("cat", "猫"), ("dog", "狗"), ("bird", "鸟"), ("duck", "鸭子"),
    ("rabbit", "兔子"), ("panda", "熊猫"), ("tiger", "老虎"), ("lion", "狮子"),
    ("monkey", "猴子"), ("elephant", "大象"), ("horse", "马"), ("cow", "奶牛"),
    ("pig", "猪"), ("sheep", "绵羊"), ("bear", "熊"), ("frog", "青蛙"),
    ("red", "红色"), ("blue", "蓝色"), ("yellow", "黄色"), ("green", "绿色"),
    ("white", "白色"), ("black", "黑色"), ("pink", "粉色"), ("purple", "紫色"),
    ("one", "一"), ("two", "二"), ("three", "三"), ("four", "四"),
    ("five", "五"), ("six", "六"), ("seven", "七"), ("eight", "八"),
    ("nine", "九"), ("ten", "十"), ("big", "大的"), ("small", "小的"),
    ("long", "长的"), ("short", "短的"), ("happy", "开心的"), ("sad", "难过的"),
    ("hot", "热的"), ("cold", "冷的"), ("fast", "快的"), ("slow", "慢的"),
    ("father", "爸爸"), ("mother", "妈妈"), ("brother", "哥哥弟弟"), ("sister", "姐姐妹妹"),
    ("baby", "宝宝"), ("family", "家庭"), ("teacher", "老师"), ("friend", "朋友"),
    ("head", "头"), ("face", "脸"), ("eye", "眼睛"), ("ear", "耳朵"),
    ("nose", "鼻子"), ("mouth", "嘴巴"), ("hand", "手"), ("foot", "脚"),
    ("arm", "手臂"), ("leg", "腿"), ("hair", "头发"), ("tooth", "牙齿"),
    ("sun", "太阳"), ("moon", "月亮"), ("star", "星星"), ("sky", "天空"),
    ("cloud", "云"), ("rain", "雨"), ("snow", "雪"), ("wind", "风"),
    ("tree", "树"), ("flower", "花"), ("grass", "草"), ("river", "河流"),
    ("book", "书"), ("pen", "笔"), ("bag", "书包"), ("chair", "椅子"),
    ("table", "桌子"), ("bed", "床"), ("door", "门"), ("window", "窗户"),
    ("ball", "球"), ("toy", "玩具"), ("car", "汽车"), ("bus", "公交车"),
    ("run", "跑"), ("walk", "走"), ("jump", "跳"), ("sit", "坐"),
    ("stand", "站"), ("eat", "吃"), ("drink", "喝"), ("sleep", "睡觉"),
    ("read", "阅读"), ("write", "写"), ("sing", "唱歌"), ("dance", "跳舞"),
    ("open", "打开"), ("close", "关闭"), ("look", "看"), ("listen", "听"),
]

VOCABULARY = [
    {"id": english, "en": english, "zh": chinese, "label": english}
    for english, chinese in _WORDS
]


class EnglishGame(MultipleChoiceGame):
    game_id = "english"
    title = "英语小练习"
    description = "中英词汇双向选择"
    all_items = VOCABULARY
    success_messages = ("翻译正确！", "这个单词记住啦！", "英语小达人真棒！")
    error_messages = ("再看一看两个词的意思。", "没关系，换一个答案试试。", "星宝陪你再想一想。")
    parent_tip = "可以每天选择少量词汇，通过图片和实物继续复习。"

    def __init__(self, rounds=5, seed=None, difficulty=1):
        self.difficulty = max(1, min(3, int(difficulty)))
        self.direction = "zh_to_en"
        super().__init__(rounds=rounds, seed=seed,
                         option_count=option_count_for_difficulty(self.difficulty))

    def _prepare_options(self):
        if self.is_finished():
            self.options = []
            return
        self.direction = self.random.choice(("zh_to_en", "en_to_zh"))
        target = next(item for item in self.all_items if item["id"] == self.target_id)
        others = [item for item in self.all_items if item["id"] != self.target_id]
        self.random.shuffle(others)
        source = [target] + others[:self.option_count - 1]
        label_key = "en" if self.direction == "zh_to_en" else "zh"
        self.options = [dict(item, label=item[label_key]) for item in source]
        self.random.shuffle(self.options)

    @property
    def question(self):
        target = next(item for item in self.all_items if item["id"] == self.target_id)
        if self.direction == "zh_to_en":
            return "“{}”的英文是什么？".format(target["zh"])
        return "“{}”的中文是什么？".format(target["en"])
