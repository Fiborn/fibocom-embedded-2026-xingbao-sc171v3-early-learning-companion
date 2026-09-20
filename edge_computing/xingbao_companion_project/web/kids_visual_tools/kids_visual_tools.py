# -*- coding: utf-8 -*-
"""85 个儿童可视化小工具，纯 Python/Tkinter 实现。"""
from __future__ import annotations

import argparse
import math
import random
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

BG = "#f6f7fb"
PANEL = "#ffffff"
INK = "#263238"
MUTED = "#64748b"
BORDER = "#dbe4ee"
GOOD = "#42b883"
BAD = "#ef476f"
NAMES = ["小雨", "乐乐", "豆豆", "安安", "米米", "天天", "可可", "朵朵", "舟舟", "贝贝", "然然", "宁宁"]
ROOT_DIR = Path(__file__).resolve().parent
ASSET_DIR = ROOT_DIR / "assets" / "illustrations"


@dataclass(frozen=True)
class Tool:
    no: int
    title: str
    purpose: str
    kind: str
    slug: str
    color: str


TOOLS = [
    Tool(1, '起床/睡觉提醒', '培养作息习惯', 'sunmoon', 'routine', '#f6c85f'),
    Tool(2, '喝水打卡', '记录今天喝了几杯水', 'water', 'water', '#00a8e8'),
    Tool(3, '午睡白噪音', '播放雨声、风声、海浪声', 'player:noise', 'noise', '#5dade2'),
    Tool(4, '儿童呼吸放松', '情绪激动时跟着呼吸', 'breath', 'breath', '#6bcf7f'),
    Tool(5, '今日心情选择', '孩子选择开心、生气、难过等', 'mood', 'mood', '#ffb703'),
    Tool(6, '情绪安抚卡', '告诉孩子我可以深呼吸、抱抱玩偶', 'cards:calm', 'calm', '#90be6d'),
    Tool(7, '颜色认知卡', '学习红黄蓝绿等颜色', 'cards:colors', 'colors', '#e76f51'),
    Tool(8, '形状认知卡', '学习圆形、三角形、方形', 'cards:shapes', 'shapes', '#43aa8b'),
    Tool(9, '数字认知卡', '学习1到10', 'cards:numbers', 'numbers', '#577590'),
    Tool(10, '字母/拼音卡', '认识简单字母或拼音', 'cards:letters', 'letters', '#8e7cc3'),
    Tool(11, '动物认知卡', '看动物、听叫声', 'cards:animals', 'animals', '#bc6c25'),
    Tool(12, '水果蔬菜认知', '认识常见食物', 'cards:foods', 'foods', '#80b918'),
    Tool(13, '交通工具认知', '认识汽车、飞机、火车', 'cards:transport', 'transport', '#277da1'),
    Tool(14, '职业认知卡', '医生、老师、消防员等', 'cards:careers', 'careers', '#c77dff'),
    Tool(15, '儿歌播放器', '播放常用儿歌', 'player:songs', 'songs', '#ffafcc'),
    Tool(16, '故事播放器', '播放睡前故事、绘本音频', 'player:stories', 'stories', '#b56576'),
    Tool(17, '绘本翻页器', '简单电子绘本阅读', 'storybook', 'storybook', '#00b4d8'),
    Tool(18, '儿童画板', '涂鸦、画画', 'drawing', 'draw', '#f94144'),
    Tool(19, '涂色板', '给简单图案上色', 'coloring', 'coloring', '#f8961e'),
    Tool(20, '贴纸拼图板', '拖动贴纸装饰画面', 'stickers', 'stickers', '#43aa8b'),
    Tool(21, '简单拼图', '2到6块拼图', 'game:puzzle', 'puzzle', '#577590'),
    Tool(22, '找不同', '两张图找简单差异', 'game:spot', 'spot', '#f3722c'),
    Tool(23, '配对游戏', '动物和影子、水果和颜色配对', 'game:match', 'matching', '#90be6d'),
    Tool(24, '记忆翻牌', '翻两张相同卡片', 'game:memory', 'memory', '#277da1'),
    Tool(25, '排序小游戏', '大小、高矮、多少排序', 'game:sort', 'sorting', '#9b5de5'),
    Tool(26, '数数小游戏', '点数小动物数量', 'game:count', 'counting', '#00bbf9'),
    Tool(27, '分类小游戏', '把动物、水果、玩具分类', 'game:classify', 'classify', '#00f5d4'),
    Tool(28, '儿童抽签器', '抽今天的小任务、小奖励', 'game:lottery', 'lottery', '#f15bb5'),
    Tool(29, '小奖励转盘', '奖励贴纸、讲故事、抱抱等', 'game:wheel', 'wheel', '#fee440'),
    Tool(30, '班级点名器', '幼儿园老师点名用', 'attendance', 'attendance', '#00c2a8'),
    Tool(31, '今日值日生', '随机选择小帮手', 'helper', 'helper', '#f48c06'),
    Tool(32, '排队分组器', '把孩子分成红队、蓝队等', 'groups', 'groups', '#3a86ff'),
    Tool(33, '安全提示卡', '不碰插座、不乱跑、过马路等', 'cards:safety', 'safety', '#ef476f'),
    Tool(34, '成长小星星', '完成任务获得星星', 'stars', 'stars', '#ffbe0b'),
    Tool(35, '出门准备提醒', '鞋子、水杯、帽子逐项准备', 'cards:safety', 'go_out_ready', '#38bdf8'),
    Tool(36, '拥抱提醒器', '随机提醒一个温柔互动', 'game:lottery', 'hug_picker', '#fb7185'),
    Tool(37, '家务小帮手', '抽取擦桌子、摆碗筷等小任务', 'game:lottery', 'chore_picker', '#f59e0b'),
    Tool(38, '睡前流程卡', '刷牙、换睡衣、听故事', 'cards:calm', 'bedtime_cards', '#6366f1'),
    Tool(39, '早晨流程卡', '起床、穿衣、吃早餐', 'cards:safety', 'morning_cards', '#facc15'),
    Tool(40, '幼儿规则卡', '排队、轻声、轮流玩', 'cards:safety', 'class_rules', '#0ea5e9'),
    Tool(41, '餐桌礼仪卡', '坐好、小口吃、谢谢帮忙', 'cards:calm', 'table_manners', '#f97316'),
    Tool(42, '分享轮流卡', '提醒孩子等待和轮流', 'cards:calm', 'sharing_cards', '#84cc16'),
    Tool(43, '礼貌用语卡', '谢谢、请、对不起、没关系', 'cards:letters', 'polite_words', '#f472b6'),
    Tool(44, '天气认知卡', '晴天、雨天、刮风、下雪', 'cards:colors', 'weather_cards', '#38bdf8'),
    Tool(45, '季节认知卡', '春夏秋冬的简单认识', 'cards:colors', 'season_cards', '#22c55e'),
    Tool(46, '身体部位卡', '认识眼睛、耳朵、手和脚', 'cards:animals', 'body_cards', '#fb923c'),
    Tool(47, '家庭成员卡', '爸爸妈妈、爷爷奶奶等称呼', 'cards:letters', 'family_cards', '#f9a8d4'),
    Tool(48, '房间物品卡', '床、桌子、椅子、灯', 'cards:shapes', 'room_cards', '#94a3b8'),
    Tool(49, '衣物认知卡', '帽子、鞋子、袜子、外套', 'cards:colors', 'clothes_cards', '#60a5fa'),
    Tool(50, '玩具认知卡', '积木、皮球、小车、玩偶', 'cards:shapes', 'toy_cards', '#fbbf24'),
    Tool(51, '乐器认知卡', '鼓、琴、铃铛、喇叭', 'cards:animals', 'music_cards', '#c084fc'),
    Tool(52, '空间方位卡', '上、下、里、外', 'cards:shapes', 'position_cards', '#2dd4bf'),
    Tool(53, '反义词卡', '大和小、高和矮、多和少', 'cards:letters', 'opposite_cards', '#fb7185'),
    Tool(54, '表情模仿卡', '模仿开心、惊讶、困困', 'mood', 'face_mimic', '#facc15'),
    Tool(55, '勇敢尝试卡', '鼓励孩子试一小口、走一步', 'cards:calm', 'brave_cards', '#4ade80'),
    Tool(56, '谢谢打卡', '记录今天说谢谢的次数', 'stars', 'thanks_stars', '#fde047'),
    Tool(57, '阅读星星墙', '读完一本书点亮一颗星', 'stars', 'reading_stars', '#fbbf24'),
    Tool(58, '刷牙星星墙', '坚持刷牙收集星星', 'stars', 'tooth_stars', '#7dd3fc'),
    Tool(59, '早睡星星墙', '按时睡觉获得星星', 'stars', 'sleep_stars', '#a78bfa'),
    Tool(60, '如厕星星墙', '主动如厕获得星星', 'stars', 'toilet_stars', '#c4b5fd'),
    Tool(61, '吃菜打卡', '鼓励尝试蔬菜和水果', 'stars', 'veggie_stars', '#86efac'),
    Tool(62, '牛奶打卡', '记录今天喝奶情况', 'water', 'milk_tracker', '#93c5fd'),
    Tool(63, '户外活动打卡', '记录跑跳、散步、晒太阳', 'stars', 'outdoor_stars', '#22c55e'),
    Tool(64, '课堂奖励转盘', '抽取班级小奖励', 'game:wheel', 'class_reward_wheel', '#fde047'),
    Tool(65, '亲子游戏转盘', '抽一个亲子小游戏', 'game:wheel', 'family_game_wheel', '#fb7185'),
    Tool(66, '故事主题转盘', '抽今晚故事主题', 'game:wheel', 'story_wheel', '#c084fc'),
    Tool(67, '运动动作转盘', '抽跳跃、拍手、转圈等动作', 'game:wheel', 'movement_wheel', '#34d399'),
    Tool(68, '颜色寻宝游戏', '找一找房间里的指定颜色', 'game:lottery', 'color_hunt', '#f97316'),
    Tool(69, '形状寻宝游戏', '找圆形、方形、三角形物品', 'game:lottery', 'shape_hunt', '#2dd4bf'),
    Tool(70, '声音猜猜看', '抽取生活声音做模仿', 'game:lottery', 'sound_guess', '#38bdf8'),
    Tool(71, '动物动作模仿', '抽一个动物动作来模仿', 'game:lottery', 'animal_action', '#a3e635'),
    Tool(72, '小小观察员', '抽一个观察任务', 'game:lottery', 'little_observer', '#60a5fa'),
    Tool(73, '颜色涂鸦板', '专注颜色自由涂鸦', 'drawing', 'color_doodle', '#ef4444'),
    Tool(74, '形状画板', '画圆形、方形和三角形', 'drawing', 'shape_drawing', '#0ea5e9'),
    Tool(75, '线条练习板', '练习直线、曲线和波浪线', 'drawing', 'line_practice', '#64748b'),
    Tool(76, '名字涂鸦板', '练习画自己的名字', 'drawing', 'name_doodle', '#f472b6'),
    Tool(77, '节日涂色板', '给节日图案填颜色', 'coloring', 'festival_coloring', '#fb923c'),
    Tool(78, '动物涂色板', '给动物线稿上色', 'coloring', 'animal_coloring', '#84cc16'),
    Tool(79, '交通涂色板', '给小车和房子上色', 'coloring', 'transport_coloring', '#38bdf8'),
    Tool(80, '贴纸贺卡板', '用贴纸做一张小贺卡', 'stickers', 'sticker_card', '#f472b6'),
    Tool(81, '贴纸天气板', '用贴纸装饰天气场景', 'stickers', 'weather_stickers', '#60a5fa'),
    Tool(82, '贴纸农场板', '用贴纸布置小农场', 'stickers', 'farm_stickers', '#22c55e'),
    Tool(83, '班级分队器', '快速分成多个活动小队', 'groups', 'team_groups', '#3b82f6'),
    Tool(84, '小主持人抽取', '随机抽取今天的小主持人', 'helper', 'host_picker', '#f97316'),
    Tool(85, '今日小明星', '随机抽取并展示今日小明星', 'helper', 'star_child_picker', '#facc15'),
]


CARD_DATA = {
    "calm": [("深呼吸", "慢慢吸气，再慢慢呼气", "#caffbf"), ("抱抱玩偶", "找喜欢的玩偶抱一抱", "#ffd6a5"), ("说出来", "告诉大人：我现在不舒服", "#bde0fe"), ("喝口水", "小口喝水，让身体放松", "#9bf6ff")],
    "colors": [("红色", "苹果、草莓", "#ef4444"), ("黄色", "香蕉、太阳", "#facc15"), ("蓝色", "天空、海水", "#3b82f6"), ("绿色", "树叶、青菜", "#22c55e"), ("紫色", "葡萄、茄子", "#a855f7")],
    "shapes": [("圆形", "像皮球", "#ffadad"), ("三角形", "像屋顶", "#ffd166"), ("方形", "像积木", "#90be6d"), ("长方形", "像小门", "#74c0fc"), ("星形", "像星星", "#f9c74f")],
    "letters": [("A", "a  苹果", "#ffafcc"), ("B", "b  宝宝", "#bde0fe"), ("M", "m  妈妈", "#caffbf"), ("P", "p  皮球", "#ffd6a5")],
    "animals": [("小猫", "喵喵", "#f4a261"), ("小狗", "汪汪", "#e9c46a"), ("小鸟", "啾啾", "#2a9d8f"), ("小鱼", "吐泡泡", "#48cae4")],
    "foods": [("苹果", "红红甜甜", "#ef4444"), ("香蕉", "弯弯黄黄", "#facc15"), ("胡萝卜", "脆脆的", "#f97316"), ("西兰花", "绿绿的", "#22c55e")],
    "transport": [("汽车", "在路上开", "#3b82f6"), ("飞机", "在天上飞", "#8ecae6"), ("火车", "沿铁轨走", "#06d6a0"), ("轮船", "在水上行", "#118ab2")],
    "careers": [("医生", "帮助大家健康", "#80ed99"), ("老师", "陪孩子学习", "#ffd166"), ("消防员", "保护安全", "#ef476f"), ("厨师", "做出饭菜", "#f4a261")],
    "safety": [("不碰插座", "看到插座请找大人", "#ef476f"), ("过马路看灯", "红灯停，绿灯行", "#22c55e"), ("不乱跑", "牵好大人的手", "#3b82f6"), ("热水小心", "烫的东西不伸手", "#f97316")],
}



CATEGORY_LABELS = {
    "routine": "生活流程",
    "emotion": "情绪安抚",
    "cognition": "认知学习",
    "audio": "音频故事",
    "create": "创作画板",
    "game": "互动游戏",
    "classroom": "班级管理",
    "reward": "成长奖励",
}

CATEGORY_COLORS = {
    "routine": "#0ea5e9",
    "emotion": "#84cc16",
    "cognition": "#8b5cf6",
    "audio": "#ec4899",
    "create": "#ef4444",
    "game": "#14b8a6",
    "classroom": "#3b82f6",
    "reward": "#eab308",
}

CATEGORY_ORDER = ["全部", "生活流程", "情绪安抚", "认知学习", "音频故事", "创作画板", "互动游戏", "班级管理", "成长奖励"]

CARD_OVERRIDE = {
    "go_out_ready": [("鞋子", "鞋尖朝前，坐稳慢慢穿", "#bfdbfe"), ("水杯", "带好自己的水杯", "#a7f3d0"), ("帽子", "太阳大时戴帽子", "#fde68a"), ("牵手", "出门牵好大人的手", "#fecaca")],
    "morning_cards": [("起床", "睁开眼，伸伸懒腰", "#fde68a"), ("穿衣", "自己试着穿一件", "#bfdbfe"), ("早餐", "坐好慢慢吃", "#fed7aa"), ("出门", "带好水杯和书包", "#bbf7d0")],
    "class_rules": [("排队", "站在线上，不推不挤", "#bfdbfe"), ("轻声", "室内说话轻一点", "#ddd6fe"), ("轮流", "等一等，大家都有机会", "#bbf7d0"), ("收纳", "玩完放回原位", "#fed7aa")],
    "table_manners": [("坐好", "小脚放下，小手扶碗", "#fed7aa"), ("小口吃", "慢慢嚼，不着急", "#fde68a"), ("谢谢", "别人帮忙要说谢谢", "#bbf7d0"), ("擦嘴", "吃完擦擦小嘴", "#bfdbfe")],
    "sharing_cards": [("等待", "轮到我之前先看一看", "#ddd6fe"), ("交换", "我可以问：能换一下吗", "#bfdbfe"), ("轮流", "你一次，我一次", "#bbf7d0"), ("说谢谢", "别人分享后说谢谢", "#fde68a")],
    "polite_words": [("谢谢", "别人帮忙时说谢谢", "#fde68a"), ("请", "想要东西先说请", "#bfdbfe"), ("对不起", "碰到别人先道歉", "#fecaca"), ("没关系", "别人道歉时可以这样说", "#bbf7d0")],
    "weather_cards": [("晴天", "太阳出来，适合晒晒", "#fde68a"), ("雨天", "带雨伞，慢慢走", "#bfdbfe"), ("刮风", "衣服拉好，不追帽子", "#ddd6fe"), ("下雪", "地上滑，小步走", "#e0f2fe")],
    "season_cards": [("春天", "花开了，天气暖", "#bbf7d0"), ("夏天", "很热，要喝水", "#fde68a"), ("秋天", "树叶变黄了", "#fed7aa"), ("冬天", "很冷，穿外套", "#bfdbfe")],
    "body_cards": [("眼睛", "看一看，休息一下", "#bfdbfe"), ("耳朵", "听声音，轻轻说", "#fde68a"), ("小手", "洗干净，再吃饭", "#bbf7d0"), ("小脚", "慢慢走，不乱跑", "#fed7aa")],
    "family_cards": [("爸爸", "家人会保护我", "#bfdbfe"), ("妈妈", "我可以说出需要", "#fbcfe8"), ("爷爷奶奶", "见面问好", "#fde68a"), ("外公外婆", "轻轻拥抱", "#bbf7d0")],
    "room_cards": [("床", "睡觉休息的地方", "#ddd6fe"), ("桌子", "画画和吃饭会用到", "#fed7aa"), ("椅子", "坐稳不摇晃", "#bfdbfe"), ("小灯", "太暗时开灯", "#fde68a")],
    "clothes_cards": [("帽子", "保护小脑袋", "#fde68a"), ("鞋子", "保护小脚", "#bfdbfe"), ("袜子", "穿好再穿鞋", "#ddd6fe"), ("外套", "冷的时候穿", "#bbf7d0")],
    "toy_cards": [("积木", "搭高高，也要收好", "#fde68a"), ("皮球", "在安全地方玩", "#bfdbfe"), ("小车", "轻轻推，不撞人", "#fed7aa"), ("玩偶", "可以抱抱它", "#fbcfe8")],
    "music_cards": [("小鼓", "咚咚咚，轻一点", "#fed7aa"), ("小琴", "叮叮咚咚", "#bfdbfe"), ("铃铛", "摇一摇听声音", "#fde68a"), ("喇叭", "不要贴近耳朵", "#fecaca")],
    "position_cards": [("上面", "小鸟在树上", "#bfdbfe"), ("下面", "鞋子在桌下", "#ddd6fe"), ("里面", "玩具在盒子里", "#bbf7d0"), ("外面", "球在篮子外", "#fed7aa")],
    "opposite_cards": [("大和小", "大球，小球", "#fde68a"), ("高和矮", "高楼，小凳", "#bfdbfe"), ("多和少", "多一点，少一点", "#bbf7d0"), ("快和慢", "跑得快，走得慢", "#fed7aa")],
    "brave_cards": [("试一小口", "只要尝一点点", "#bbf7d0"), ("再走一步", "慢慢来，我可以", "#bfdbfe"), ("举手说", "我可以告诉老师", "#fde68a"), ("请帮忙", "不会时可以求助", "#fbcfe8")],
    "bedtime_cards": [("刷牙", "牙齿干净再睡觉", "#bfdbfe"), ("换睡衣", "让身体舒服", "#ddd6fe"), ("听故事", "选一本安静故事", "#fde68a"), ("说晚安", "轻轻闭眼休息", "#bbf7d0")],
}

LOTTERY_ITEMS = {
    "hug_picker": ["抱抱爸爸", "抱抱妈妈", "和玩偶抱一抱", "说一句我爱你", "牵手走十步", "给家人一个微笑"],
    "chore_picker": ["摆好一个碗", "擦一小块桌子", "收三块积木", "把书放回去", "帮忙拿纸巾", "整理自己的鞋"],
    "color_hunt": ["找红色物品", "找黄色物品", "找蓝色物品", "找绿色物品", "找白色物品", "找黑色物品"],
    "shape_hunt": ["找圆形物品", "找方形物品", "找三角形图案", "找长方形物品", "找像星星的东西", "找弯弯的线"],
    "sound_guess": ["模仿下雨声", "模仿敲门声", "模仿风声", "模仿小车声", "模仿脚步声", "模仿刷牙声"],
    "animal_action": ["像小猫伸懒腰", "像小狗摇尾巴", "像小鸟拍拍手臂", "像小鱼摆一摆", "像小兔跳三下", "像小熊慢慢走"],
    "little_observer": ["找一个软软的东西", "找一个圆圆的东西", "找一个会响的东西", "找一件蓝色物品", "数一数有几本书", "看一看窗外天气"],
}

WHEEL_REWARDS = {
    "class_reward_wheel": ["贴纸", "带队", "选儿歌", "小助手", "故事时间", "掌声"],
    "family_game_wheel": ["躲猫猫", "搭高塔", "画一张画", "讲故事", "模仿秀", "抱抱挑战"],
    "story_wheel": ["月亮", "森林", "小车", "海边", "动物", "彩虹"],
    "movement_wheel": ["跳三下", "拍手五下", "转一圈", "踮脚走", "伸伸手", "深呼吸"],
}

TIMER_STEPS = {
    "pomodoro": ["准备", "专注", "收尾", "休息"],
    "countdown": ["看看任务", "开始做", "快完成", "结束"],
    "handwash": ["打湿小手", "搓泡泡", "冲干净", "擦干"],
    "toothbrush": ["上排牙", "下排牙", "里面牙", "漱口"],
    "toilet": ["听提醒", "去厕所", "洗小手", "回来"],
    "meal": ["坐端正", "小口吃", "慢慢嚼", "擦擦嘴"],
    "dress_countdown": ["找衣服", "穿上衣", "穿裤子", "穿鞋袜"],
    "bag_countdown": ["放绘本", "放水杯", "拉拉链", "背书包"],
    "move_rest": ["喝口水", "拍拍腿", "深呼吸", "再活动"],
    "blocks_timer": ["放大块", "放小块", "收盒子", "看地面"],
    "draw_break": ["放下笔", "眨眨眼", "转手腕", "再继续"],
    "eye_rest": ["看远处", "眨眨眼", "揉肩膀", "喝口水"],
    "reading_clock": ["选绘本", "翻一页", "说一说", "放回去"],
    "quiet_clock": ["坐下来", "轻轻听", "慢呼吸", "结束"],
    "calm_corner": ["坐一坐", "抱玩偶", "深呼吸", "说感受"],
}

DRAWING_PROMPTS = {
    "draw": "自由画一画：可以先画大轮廓，再加颜色。",
    "color_doodle": "颜色涂鸦：试试把一种颜色画得深一点、浅一点。",
    "shape_drawing": "形状画板：沿着浅色图形描一描，再自己画一个。",
    "line_practice": "线条练习：顺着浅线走，练直线、弯线和波浪线。",
    "name_doodle": "名字涂鸦：在浅字旁边画自己的名字或符号。",
}

STICKER_NAMES = {
    "sticker_card": ["爱心", "星星", "气球", "花朵"],
    "weather_stickers": ["太阳", "云朵", "雨滴", "彩虹"],
    "farm_stickers": ["小花", "星星", "小鸡", "苹果"],
}
def norm(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def resolve_tool(value: Any) -> Tool:
    key = norm(value)
    for tool in TOOLS:
        if key in {str(tool.no), norm(tool.title), norm(tool.slug), norm(tool.kind.split(":")[-1])}:
            return tool
    raise ValueError(f"找不到工具：{value}")


def get_tool_registry() -> list[dict[str, Any]]:
    return [tool.__dict__.copy() for tool in TOOLS]


def validate_registry() -> None:
    if [tool.no for tool in TOOLS] != list(range(1, len(TOOLS) + 1)):
        raise ValueError(f"工具序号必须是 1 到 {len(TOOLS)}")
    if len({tool.slug for tool in TOOLS}) != len(TOOLS):
        raise ValueError("工具 slug 不能重复")



def category_key(tool: Tool) -> str:
    kind = tool.kind
    if kind.startswith("timer:"):
        return "time"
    if kind in {"sunmoon", "water"}:
        return "routine"
    if kind in {"breath", "mood"} or tool.slug in {"calm", "bedtime_cards", "brave_cards", "sharing_cards"}:
        return "emotion"
    if kind.startswith("cards:"):
        return "cognition"
    if kind.startswith("player:") or kind == "storybook":
        return "audio"
    if kind in {"drawing", "coloring", "stickers"}:
        return "create"
    if kind.startswith("game:"):
        return "game"
    if kind in {"attendance", "helper", "groups"}:
        return "classroom"
    if kind == "stars":
        return "reward"
    return "routine"


def category_label(tool: Tool) -> str:
    return CATEGORY_LABELS[category_key(tool)]


def category_color(tool: Tool) -> str:
    return CATEGORY_COLORS[category_key(tool)]


def tool_hint(tool: Tool) -> str:
    kind = tool.kind
    if kind.startswith("timer:"):
        return "设定时间后点击开始，适合和孩子一起看进度、做收尾。"
    if kind.startswith("cards:"):
        return "用上一张/下一张切换内容，点击翻卡或发音按钮给孩子即时反馈。"
    if kind.startswith("player:"):
        return "选择上一首或下一首，播放时会显示进度，可作为安静陪伴界面。"
    if kind == "breath":
        return "跟随圆球慢慢吸气和呼气，适合情绪激动时短暂停顿。"
    if kind == "mood":
        return "点击一个大表情，让孩子先说出现在的感受。"
    if kind == "drawing":
        return "选择颜色和笔刷大小，在画布上直接涂鸦。"
    if kind == "coloring":
        return "先选择颜色，再点击线稿区域完成填色。"
    if kind == "stickers":
        return "选择贴纸后点在背景上，已有贴纸可以拖动摆放。"
    if kind.startswith("game:"):
        return "按照画面提示点击或选择，完成后会显示即时结果。"
    if kind in {"attendance", "groups", "helper"}:
        return "适合老师或家长快速组织孩子，数据只保存在本次运行中。"
    if kind == "stars":
        return "每完成一次小任务点亮一颗星，清空后可重新开始。"
    return "点击按钮开始使用。"


def get_card_items(tool: Tool, fallback_kind: str) -> list[tuple[str, str, str]]:
    if tool.slug in CARD_OVERRIDE:
        return CARD_OVERRIDE[tool.slug]
    if fallback_kind == "numbers":
        return [(str(i), f"{i} 个小圆点", "#e0f2fe") for i in range(1, 11)]
    return CARD_DATA.get(fallback_kind, CARD_DATA["calm"])


def get_lottery_items(tool: Tool) -> list[str]:
    return LOTTERY_ITEMS.get(tool.slug, ["收好3个玩具", "给家人一个抱抱", "讲一个小故事", "贴一颗星星", "选一本绘本", "喝一杯水"])


def get_wheel_rewards(tool: Tool) -> list[str]:
    return WHEEL_REWARDS.get(tool.slug, ["贴纸", "讲故事", "抱抱", "画画", "听儿歌", "亲子游戏"])


def illustration_key(tool: Tool) -> str:
    kind = tool.kind
    slug = tool.slug
    specific = f"tool_{slug}"
    if (ASSET_DIR / f"{specific}_thumb.png").exists() and (ASSET_DIR / f"{specific}_panel.png").exists():
        return specific
    if slug in {"colors", "shapes", "numbers", "letters", "weather_cards", "season_cards", "position_cards", "opposite_cards"}:
        return "topic_learning_cards"
    if slug in {"animals", "foods", "transport", "careers", "body_cards", "family_cards", "room_cards", "clothes_cards", "toy_cards", "music_cards"}:
        return "topic_world_cards"
    if slug in {"calm", "safety", "go_out_ready", "bedtime_cards", "morning_cards", "class_rules", "table_manners", "sharing_cards", "polite_words", "brave_cards"}:
        return "topic_safety_cards"
    if kind.startswith("game:"):
        return f"game_{slug}"
    if kind.startswith("player:") or kind == "storybook":
        return "topic_audio_story"
    if kind in {"breath", "mood"}:
        return "topic_emotion_breath"
    if kind in {"attendance", "helper", "groups"}:
        return "topic_classroom_tools"
    if kind == "stars":
        return "topic_star_rewards"
    if kind in {"timer:handwash", "timer:tooth"} or slug in {"handwash", "toothbrush"}:
        return "topic_hygiene"
    if kind == "water" or kind == "timer:meal" or slug in {"veggie_stars", "milk_tracker"}:
        return "topic_food_water"
    if kind.startswith("timer:"):
        return "topic_focus_timer"
    if kind == "drawing":
        return "topic_drawing"
    if kind == "coloring":
        return "topic_coloring"
    if kind == "stickers":
        return "topic_stickers"

    return f"category_{category_key(tool)}"


def tool_asset_name(tool: Tool) -> str:
    return f"{illustration_key(tool)}_thumb.png"


def card_asset_name(tool: Tool, index: int) -> str:
    return f"{illustration_key(tool)}_panel.png"


def get_star_tasks(tool: Tool) -> list[str]:
    mapping = {
        "reading_stars": ["读一页", "读一本", "讲给大人", "选绘本", "整理书"],
        "tooth_stars": ["早上刷牙", "晚上刷牙", "刷满时间", "漱口", "收牙刷"],
        "sleep_stars": ["按时上床", "换睡衣", "说晚安", "关小灯", "安静躺好"],
        "toilet_stars": ["主动说", "自己去", "洗小手", "冲干净", "整理衣服"],
        "veggie_stars": ["尝蔬菜", "吃水果", "小口嚼", "喝汤", "谢谢厨师"],
        "thanks_stars": ["说谢谢", "说请", "说对不起", "说没关系", "主动帮忙"],
        "outdoor_stars": ["跑一跑", "跳一跳", "散步", "晒太阳", "喝水休息"],
    }
    return mapping.get(tool.slug, ["整理玩具", "好好刷牙", "认真阅读", "主动喝水", "温柔说话"])
def get_timer_seconds(tool: Tool, timer_kind: str) -> int:
    overrides = {
        "dress_countdown": 300,
        "bag_countdown": 240,
        "blocks_timer": 300,
        "eye_rest": 1200,
        "reading_clock": 900,
        "quiet_clock": 180,
        "calm_corner": 120,
        "move_rest": 300,
        "draw_break": 1200,
    }
    if tool.slug in overrides:
        return overrides[tool.slug]
    return TimerPage.DUR[timer_kind]


def get_timer_steps(tool: Tool, timer_kind: str) -> list[str]:
    return TIMER_STEPS.get(tool.slug, TIMER_STEPS.get(tool.slug.replace("_", ""), TIMER_STEPS.get(timer_kind, TIMER_STEPS["countdown"])))


def drawing_prompt(tool: Tool) -> str:
    return DRAWING_PROMPTS.get(tool.slug, DRAWING_PROMPTS["draw"])


def sticker_names(tool: Tool) -> list[str]:
    return STICKER_NAMES.get(tool.slug, ["花朵", "星星", "气球", "云朵"])


def pick_font(root: tk.Tk) -> str:
    fonts = set(tkfont.families(root))
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial"):
        if name in fonts:
            return name
    return "TkDefaultFont"


def beep() -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def clear(w: tk.Widget) -> None:
    for child in w.winfo_children():
        child.destroy()


def star(cx: float, cy: float, r1: float, r2: float) -> list[float]:
    pts: list[float] = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = r1 if i % 2 == 0 else r2
        pts += [cx + math.cos(a) * r, cy + math.sin(a) * r]
    return pts


def readable_text(bg: str) -> str:
    try:
        value = bg.lstrip("#")
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        return "#111827" if (r * 299 + g * 587 + b * 114) / 1000 > 170 else "white"
    except Exception:
        return "white"


def btn(parent: tk.Widget, text: str, command: Any, color: str, width: int = 10) -> tk.Button:
    fg = readable_text(color)
    button = tk.Button(parent, text=text, command=command, bg=color, fg=fg, activebackground=color, activeforeground=fg, relief="flat", bd=0, padx=12, pady=8, width=width, cursor="hand2")
    button.bind("<Enter>", lambda _e: button.configure(relief="groove"))
    button.bind("<Leave>", lambda _e: button.configure(relief="flat"))
    return button


class Scroll(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class App:
    def __init__(self, root: tk.Tk) -> None:
        validate_registry()
        self.root = root
        self.font = pick_font(root)
        for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            try:
                tkfont.nametofont(font_name).configure(family=self.font, size=10)
            except tk.TclError:
                pass
        self.setup_style()
        self.root.title("儿童可视化小工具箱")
        self.root.geometry("1060x760")
        self.root.minsize(1060, 680)
        self.image_cache: dict[str, tk.PhotoImage] = {}
        self.assets_ready = self.ensure_assets()
        self.state = {"water": {}, "attendance": {name: False for name in NAMES}, "stars": {}}
        self.page: tk.Widget | None = None
        self.wrap = tk.Frame(root, bg=BG)
        self.wrap.pack(fill="both", expand=True)
        self.dashboard()

    def setup_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TProgressbar", troughcolor="#eef2f7", background="#38bdf8", bordercolor="#eef2f7", lightcolor="#38bdf8", darkcolor="#38bdf8")
        style.configure("Vertical.TScrollbar", background="#cbd5e1", troughcolor=BG, bordercolor=BG, arrowcolor=INK)
        style.configure("Horizontal.TProgressbar", thickness=12)

    def ensure_assets(self) -> bool:
        required = {tool_asset_name(tool) for tool in TOOLS}
        required.update({card_asset_name(tool, 0) for tool in TOOLS})
        missing = [name for name in sorted(required) if not (ASSET_DIR / name).exists()]
        if missing:
            print(f"图片库缺少 {len(missing)} 个文件，请检查 {ASSET_DIR}")
            return False
        return True

    def asset_image(self, filename: str) -> tk.PhotoImage | None:
        path = ASSET_DIR / filename
        if not path.exists():
            return None
        key = str(path)
        if key not in self.image_cache:
            try:
                self.image_cache[key] = tk.PhotoImage(file=key)
            except tk.TclError:
                return None
        return self.image_cache[key]

    def tool_image(self, tool: Tool) -> tk.PhotoImage | None:
        return self.asset_image(tool_asset_name(tool))

    def card_image(self, tool: Tool, index: int) -> tk.PhotoImage | None:
        return None

    def set_page(self, page: tk.Widget) -> None:
        if self.page:
            self.page.destroy()
        self.page = page
        page.pack(fill="both", expand=True)
        redraw = getattr(page, "queue_redraw", None)
        if callable(redraw):
            def safe_redraw(p: tk.Widget = page, r: Any = redraw) -> None:
                try:
                    if p.winfo_exists():
                        r()
                except tk.TclError:
                    pass
            self.root.after_idle(safe_redraw)
            self.root.after(80, safe_redraw)

    def dashboard(self) -> None:
        page = tk.Frame(self.wrap, bg=BG)
        self.set_page(page)
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x", padx=28, pady=(22, 10))
        tk.Label(top, text="儿童可视化小工具箱", bg=BG, fg=INK, font=(self.font, 27, "bold")).pack(anchor="w")
        tk.Label(top, text="85 个本地运行的小工具，覆盖生活、认知、创作、游戏和班级管理。", bg=BG, fg=MUTED, font=(self.font, 11)).pack(anchor="w", pady=(4, 0))

        stat_row = tk.Frame(page, bg=BG)
        stat_row.pack(fill="x", padx=28, pady=(6, 10))
        for text, color in [(f"{len(TOOLS)} 个工具", "#0ea5e9"), ("9 类场景", "#8b5cf6"), ("支持快速调用", "#22c55e")]:
            tk.Label(stat_row, text=text, bg="#ffffff", fg=color, padx=12, pady=6, font=(self.font, 10, "bold"), highlightbackground=BORDER, highlightthickness=1).pack(side="left", padx=(0, 8))

        search_row = tk.Frame(page, bg=BG)
        search_row.pack(fill="x", padx=28, pady=(0, 10))
        tk.Label(search_row, text="搜索", bg=BG, fg=INK, font=(self.font, 11, "bold")).pack(side="left")
        var = tk.StringVar()
        entry = tk.Entry(search_row, textvariable=var, relief="flat", font=(self.font, 12), bg="#ffffff", fg=INK, insertbackground=INK)
        entry.pack(side="left", fill="x", expand=True, padx=(10, 0), ipady=9)

        filter_row = tk.Frame(page, bg=BG)
        filter_row.pack(fill="x", padx=28, pady=(0, 12))
        active_category = tk.StringVar(value="全部")
        filter_buttons: dict[str, tk.Button] = {}

        sc = Scroll(page)
        sc.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        def refresh(*_a: Any) -> None:
            clear(sc.inner)
            q = norm(var.get())
            selected = active_category.get()
            items = []
            for tool in TOOLS:
                if selected != "全部" and category_label(tool) != selected:
                    continue
                if q and q not in norm(tool.title) and q not in norm(tool.slug) and q not in str(tool.no) and q not in norm(tool.purpose):
                    continue
                items.append(tool)
            for name, button in filter_buttons.items():
                is_active = name == selected
                button.configure(bg="#111827" if is_active else "#ffffff", fg="white" if is_active else INK)
            if not items:
                tk.Label(sc.inner, text="没有匹配的小工具", bg=BG, fg=MUTED, font=(self.font, 16, "bold")).pack(pady=40)
                return
            for i, tool in enumerate(items):
                card = self.card(sc.inner, tool)
                card.grid(row=i // 4, column=i % 4, padx=8, pady=8, sticky="nsew")
            for col in range(4):
                sc.inner.grid_columnconfigure(col, weight=1, minsize=220)

        for name in CATEGORY_ORDER:
            button = tk.Button(filter_row, text=name, command=lambda n=name: (active_category.set(n), refresh()), bg="#ffffff", fg=INK, relief="flat", bd=0, padx=10, pady=6, cursor="hand2", highlightbackground=BORDER, highlightthickness=1)
            button.pack(side="left", padx=(0, 6), pady=2)
            filter_buttons[name] = button

        var.trace_add("write", refresh)
        refresh()

    def card(self, parent: tk.Widget, tool: Tool) -> tk.Frame:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
        tk.Frame(card, bg=tool.color, width=7).pack(side="left", fill="y")
        body = tk.Frame(card, bg=PANEL)
        body.pack(side="left", fill="both", expand=True, padx=13, pady=12)

        click_widgets: list[tk.Widget] = [card, body]
        meta = tk.Frame(body, bg=PANEL)
        meta.pack(fill="x")
        num_label = tk.Label(meta, text=f"{tool.no:03d}", bg=PANEL, fg=tool.color, font=(self.font, 10, "bold"))
        num_label.pack(side="left")
        cat_label = tk.Label(meta, text=category_label(tool), bg="#f8fafc", fg=category_color(tool), font=(self.font, 9, "bold"), padx=6, pady=2, highlightbackground=BORDER, highlightthickness=1)
        cat_label.pack(side="right")
        click_widgets.extend([meta, num_label, cat_label])

        photo = self.tool_image(tool)
        if photo:
            img = tk.Label(body, image=photo, bg=PANEL, bd=0)
            img.pack(fill="x", pady=(9, 7))
            click_widgets.append(img)

        title_label = tk.Label(body, text=tool.title, bg=PANEL, fg=INK, font=(self.font, 14, "bold"), wraplength=178, justify="left")
        title_label.pack(anchor="w", pady=(2, 3))
        purpose_label = tk.Label(body, text=tool.purpose, bg=PANEL, fg=MUTED, font=(self.font, 10), wraplength=184, justify="left")
        purpose_label.pack(anchor="w")
        hint_label = tk.Label(body, text=tool_hint(tool), bg=PANEL, fg="#94a3b8", font=(self.font, 9), wraplength=184, justify="left")
        hint_label.pack(anchor="w", pady=(8, 0))
        open_btn = btn(body, "打开", lambda: self.open(tool), tool.color, 7)
        open_btn.pack(anchor="e", pady=(10, 0))
        click_widgets.extend([title_label, purpose_label, hint_label])

        def enter(_event: tk.Event) -> None:
            card.configure(highlightbackground=tool.color)

        def leave(_event: tk.Event) -> None:
            card.configure(highlightbackground=BORDER)

        for widget in click_widgets:
            widget.bind("<Button-1>", lambda _e, t=tool: self.open(t))
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
        return card

    def open(self, value: Any) -> None:
        tool = value if isinstance(value, Tool) else resolve_tool(value)
        if tool.kind.startswith("timer:"):
            page = TimerPage(self.wrap, self, tool)
        elif tool.kind.startswith("cards:"):
            page = CardsPage(self.wrap, self, tool)
        elif tool.kind.startswith("player:"):
            page = PlayerPage(self.wrap, self, tool)
        elif tool.kind.startswith("game:"):
            page = GamePage(self.wrap, self, tool)
        else:
            cls = {
                "sunmoon": SunMoonPage,
                "water": WaterPage,
                "breath": BreathPage,
                "mood": MoodPage,
                "storybook": StoryPage,
                "drawing": DrawingPage,
                "coloring": ColoringPage,
                "stickers": StickersPage,
                "attendance": AttendancePage,
                "helper": HelperPage,
                "groups": GroupsPage,
                "stars": StarsPage,
            }[tool.kind]
            page = cls(self.wrap, self, tool)
        self.set_page(page)


class BasePage(tk.Frame):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.tool = tool
        self.after_ids: list[str] = []
        self._redraw_after_id: str | None = None
        self._destroyed = False
        self.bind("<Configure>", self._on_configure)
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=28, pady=(20, 14))
        btn(head, "返回", app.dashboard, "#475569", 8).pack(side="left")
        box = tk.Frame(head, bg=BG)
        box.pack(side="left", fill="x", expand=True, padx=16)
        meta = tk.Frame(box, bg=BG)
        meta.pack(anchor="w")
        tk.Label(meta, text=f"{tool.no:03d}", bg=tool.color, fg=readable_text(tool.color), font=(app.font, 10, "bold"), padx=8, pady=3).pack(side="left")
        tk.Label(meta, text=category_label(tool), bg="#ffffff", fg=category_color(tool), font=(app.font, 10, "bold"), padx=8, pady=3, highlightbackground=BORDER, highlightthickness=1).pack(side="left", padx=8)
        tk.Label(box, text=tool.title, bg=BG, fg=INK, font=(app.font, 23, "bold")).pack(anchor="w", pady=(5, 0))
        tk.Label(box, text=tool.purpose, bg=BG, fg=MUTED, font=(app.font, 11)).pack(anchor="w")
        tk.Label(box, text=tool_hint(tool), bg=BG, fg="#475569", font=(app.font, 10), wraplength=700, justify="left").pack(anchor="w", pady=(4, 0))
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=28, pady=(0, 24))

    def later(self, ms: int, func: Any) -> None:
        self.after_ids.append(self.after(ms, func))

    def draw_canvas_art(self, canvas: tk.Canvas, x: float, y: float, panel: bool = True, label: str | None = None) -> None:
        return

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self:
            self.queue_redraw()

    def queue_redraw(self) -> None:
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        draw = getattr(self, "draw", None)
        if not callable(draw):
            return
        if self._redraw_after_id:
            try:
                self.after_cancel(self._redraw_after_id)
            except tk.TclError:
                pass
        try:
            self._redraw_after_id = self.after(35, self._run_redraw)
        except tk.TclError:
            self._redraw_after_id = None

    def _run_redraw(self) -> None:
        self._redraw_after_id = None
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        draw = getattr(self, "draw", None)
        if callable(draw):
            draw()

    def destroy(self) -> None:
        self._destroyed = True
        if self._redraw_after_id:
            try:
                self.after_cancel(self._redraw_after_id)
            except tk.TclError:
                pass
        for aid in self.after_ids:
            try:
                self.after_cancel(aid)
            except tk.TclError:
                pass
        super().destroy()


class TimerPage(BasePage):
    DUR = {"pomodoro": 600, "hourglass": 180, "handwash": 20, "tooth": 120, "toilet": 1800, "meal": 1200}

    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.kind = tool.kind.split(":")[1]
        self.total = get_timer_seconds(tool, self.kind)
        self.left = self.total
        self.running = False
        self.canvas = tk.Canvas(self.body, height=390, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=16)
        self.label = tk.Label(row, text="", bg=BG, fg=INK, font=(app.font, 36, "bold"), width=8)
        self.label.grid(row=0, column=0, columnspan=5, pady=(0, 12))
        self.start = btn(row, "开始", self.toggle, tool.color, 8)
        self.start.grid(row=1, column=0, padx=6)
        btn(row, "重置", self.reset, "#64748b", 8).grid(row=1, column=1, padx=6)
        btn(row, "-1 分", lambda: self.adjust(-60), "#94a3b8", 8).grid(row=1, column=2, padx=6)
        btn(row, "+1 分", lambda: self.adjust(60), "#94a3b8", 8).grid(row=1, column=3, padx=6)
        btn(row, "提示音", beep, "#22c55e", 8).grid(row=1, column=4, padx=6)
        self.draw()

    def toggle(self) -> None:
        self.running = not self.running
        self.start.config(text="暂停" if self.running else "继续")
        if self.running:
            self.tick()

    def tick(self) -> None:
        if not self.running:
            return
        if self.left <= 0:
            self.running = False
            self.start.config(text="开始")
            beep()
            self.draw(True)
            return
        self.left -= 1
        self.draw()
        self.later(1000, self.tick)

    def reset(self) -> None:
        self.running = False
        self.left = self.total
        self.start.config(text="开始")
        self.draw()

    def adjust(self, sec: int) -> None:
        self.total = max(10, self.total + sec)
        self.left = max(0, min(self.total, self.left + sec))
        self.draw()

    def draw_hourglass_particles(self, c: tk.Canvas, cx: float, cy: float, p: float) -> None:
        top_y, neck_y, bottom_y = 58, cy, 286
        sand_cols = ["#f6c453", "#f4b942", "#ffd166", "#e8a93a", "#ffe29a"]
        frame = "#475569"
        glass = "#e0f2fe"
        c.create_polygon(cx - 98, top_y - 5, cx + 98, top_y - 5, cx + 29, neck_y, cx + 98, bottom_y + 5, cx - 98, bottom_y + 5, cx - 29, neck_y, fill="#f8fbff", outline=frame, width=5)
        c.create_polygon(cx - 82, top_y + 11, cx + 82, top_y + 11, cx + 18, neck_y - 2, fill="#ffffff", outline=glass, width=2)
        c.create_polygon(cx - 18, neck_y + 2, cx + 82, bottom_y - 11, cx - 82, bottom_y - 11, fill="#ffffff", outline=glass, width=2)
        c.create_line(cx - 70, top_y + 16, cx - 18, neck_y - 10, fill="#ffffff", width=5)
        c.create_line(cx + 18, neck_y + 10, cx + 70, bottom_y - 18, fill="#ffffff", width=5)

        def half_width(y: float, upper: bool) -> float:
            if upper:
                return 82 - 64 * ((y - top_y - 11) / max(1, neck_y - top_y - 13))
            return 18 + 64 * ((y - neck_y - 2) / max(1, bottom_y - neck_y - 13))

        top_surface = top_y + 15 + (neck_y - top_y - 28) * min(1.0, p)
        for i in range(145):
            y = top_surface + ((i * 37) % max(1, int(neck_y - top_surface - 4)))
            hw = max(5, half_width(y, True) - 6)
            x = cx + (((i * 53) % int(hw * 2)) - hw)
            r = 1.5 + (i % 3) * 0.55
            c.create_oval(x - r, y - r, x + r, y + r, fill=sand_cols[i % len(sand_cols)], outline="")
        if p < 0.98:
            drift = (time.time() * 85) % 18
            for i in range(13):
                y = neck_y - 10 + i * 10 + drift
                if neck_y - 5 <= y <= bottom_y - 35:
                    r = 1.5 + (i % 2)
                    x = cx + math.sin((time.time() * 3) + i) * 2.2
                    c.create_oval(x - r, y - r, x + r, y + r, fill=sand_cols[(i + 2) % len(sand_cols)], outline="")

        pile_h = 7 + 86 * min(1.0, p)
        base = 24 + 112 * min(1.0, p)
        pile_top = bottom_y - 12 - pile_h
        c.create_arc(cx - base / 2, pile_top - 18, cx + base / 2, pile_top + 28, start=0, extent=180, outline="#d99a2b", width=3, style="arc")
        for i in range(185):
            yy = pile_top + ((i * 29) % max(1, int(bottom_y - pile_top - 12)))
            layer = (yy - pile_top) / max(1, bottom_y - pile_top)
            hw = (base / 2) * layer + 8
            xx = cx + (((i * 47) % int(hw * 2)) - hw)
            rr = 1.5 + (i % 4) * 0.45
            c.create_oval(xx - rr, yy - rr, xx + rr, yy + rr, fill=sand_cols[(i + 1) % len(sand_cols)], outline="")
        c.create_rectangle(cx - 110, top_y - 18, cx + 110, top_y - 7, fill=frame, outline="")
        c.create_rectangle(cx - 110, bottom_y + 7, cx + 110, bottom_y + 18, fill=frame, outline="")
        c.create_line(cx - 94, top_y - 7, cx - 94, bottom_y + 7, fill="#64748b", width=4)
        c.create_line(cx + 94, top_y - 7, cx + 94, bottom_y + 7, fill="#64748b", width=4)

    def draw(self, done: bool = False) -> None:
        m, s = divmod(max(0, self.left), 60)
        self.label.config(text=f"{m:02d}:{s:02d}")
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 860)
        cx, cy = w / 2, 170
        p = 1 - self.left / self.total if self.total else 0
        c.create_rectangle(0, 0, w, 390, fill="#fbfdff", outline="")
        c.create_text(28, 28, text=self.tool.title, anchor="w", fill=INK, font=(self.app.font, 16, "bold"))
        c.create_text(28, 56, text=f"进度 {int(p * 100):d}%", anchor="w", fill=MUTED, font=(self.app.font, 11, "bold"))
        if self.kind == "hourglass":
            self.draw_hourglass_particles(c, cx, cy, p)
        elif self.kind == "handwash":
            c.create_rectangle(cx - 145, 205, cx + 145, 270, fill="#bdeeff", outline="#74c0fc", width=3)
            c.create_oval(cx - 100, 135, cx - 30, 230, fill="#ffe3c1", outline="#d99a63", width=3)
            c.create_oval(cx + 30, 135, cx + 100, 230, fill="#ffe3c1", outline="#d99a63", width=3)
            for i in range(20):
                x = cx - 190 + (i * 47 + int(time.time() * 30)) % 380
                y = 75 + (i * 29) % 135
                r = 8 + i % 5
                c.create_oval(x - r, y - r, x + r, y + r, outline="#8bd3ff", width=2)
        elif self.kind == "tooth":
            c.create_oval(cx - 85, 70, cx + 85, 270, fill="white", outline="#9bd0ff", width=5)
            for i in range(max(0, 8 - int(p * 9))):
                x, y = cx - 52 + (i % 4) * 35, 125 + (i // 4) * 65
                c.create_oval(x - 8, y - 6, x + 8, y + 6, fill="#b08968", outline="")
            c.create_line(cx - 145, 265, cx + 145, 95, fill="#ff6b6b", width=14, capstyle="round")
        elif self.kind == "toilet":
            c.create_oval(cx - 95, 100, cx + 95, 230, fill="#edf6ff", outline="#94a3b8", width=4)
            c.create_rectangle(cx + 60, 70, cx + 175, 130, fill="#edf6ff", outline="#94a3b8", width=4)
            c.create_rectangle(cx - 118, 315, cx + 118, 332, fill="#dbeafe", outline="")
            c.create_rectangle(cx - 118, 315, cx - 118 + 236 * p, 332, fill=self.tool.color, outline="")
        elif self.kind == "meal":
            c.create_oval(cx - 120, 60, cx + 120, 300, fill="#f8fafc", outline="#cbd5e1", width=5)
            c.create_arc(cx - 105, 75, cx + 105, 285, start=90, extent=-360 * p, fill="#f6bd60", outline="")
            c.create_oval(cx - 70, 110, cx + 70, 250, fill="#fff7ed", outline="#e2e8f0", width=3)
        else:
            r = 112
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#e6edf5", width=22)
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * p, outline=self.tool.color, style="arc", width=22)
            c.create_oval(cx - 58, cy - 52, cx + 58, cy + 52, fill="#ffe8b5", outline="#f1c27d", width=3)
            c.create_arc(cx - 26, cy - 7, cx + 26, cy + 35, start=200, extent=140, outline=INK, width=3, style="arc")
        steps = get_timer_steps(self.tool, self.kind)
        active = min(len(steps) - 1, int(p * len(steps))) if steps else 0
        chip_w = min(152, max(96, (w - 116) / max(1, len(steps))))
        start_x = (w - chip_w * len(steps)) / 2
        for i, step in enumerate(steps):
            x = start_x + i * chip_w
            fill = self.tool.color if i <= active else "#eef2f7"
            fg = readable_text(fill) if i <= active else MUTED
            c.create_rectangle(x + 5, 312, x + chip_w - 5, 346, fill=fill, outline="")
            c.create_text(x + chip_w / 2, 329, text=step, fill=fg, font=(self.app.font, 11, "bold"))
        if done:
            c.create_text(cx, 370, text="时间到，做得很好", fill=GOOD, font=(self.app.font, 18, "bold"))


class SunMoonPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.mode = "wake"
        self.canvas = tk.Canvas(self.body, height=410, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=14)
        btn(row, "起床卡片", lambda: self.set_mode("wake"), "#f59e0b", 12).pack(side="left", padx=8)
        btn(row, "睡觉卡片", lambda: self.set_mode("sleep"), "#6366f1", 12).pack(side="left", padx=8)
        btn(row, "轻提示音", beep, "#22c55e", 12).pack(side="left", padx=8)
        self.draw()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.draw()

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        w, cx = max(c.winfo_width(), 860), max(c.winfo_width(), 860) / 2
        if self.mode == "wake":
            c.create_rectangle(0, 0, w, 410, fill="#fff7d6", outline="")
            c.create_oval(cx - 92, 75, cx + 92, 259, fill="#ffd166", outline="#f59e0b", width=5)
            text = "早上好，慢慢起床"
        else:
            c.create_rectangle(0, 0, w, 410, fill="#e8eeff", outline="")
            c.create_oval(cx - 95, 75, cx + 95, 265, fill="#dde7ff", outline="#6471d9", width=5)
            c.create_oval(cx - 35, 55, cx + 125, 245, fill="#e8eeff", outline="")
            text = "晚安，准备睡觉"
        self.draw_canvas_art(c, w - 130, 82, panel=False)
        c.create_text(cx, 335, text=text, fill=INK, font=(self.app.font, 26, "bold"))


class WaterPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.canvas = tk.Canvas(self.body, height=410, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Button-1>", self.click)
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=14)
        btn(row, "加一杯", self.add, tool.color, 10).pack(side="left", padx=8)
        btn(row, "清空", self.reset, "#64748b", 10).pack(side="left", padx=8)
        self.draw()

    def boxes(self) -> list[tuple[int, int, int, int]]:
        return [(78 + i * 88, 214, 140 + i * 88, 337) for i in range(8)]

    def cups(self) -> list[bool]:
        water_state = self.app.state["water"]
        if self.tool.slug not in water_state:
            water_state[self.tool.slug] = [False] * 8
        return water_state[self.tool.slug]

    def click(self, e: tk.Event) -> None:
        cups = self.cups()
        for i, (x1, y1, x2, y2) in enumerate(self.boxes()):
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                cups[i] = not cups[i]
                self.draw()

    def add(self) -> None:
        cups = self.cups()
        for i, v in enumerate(cups):
            if not v:
                cups[i] = True
                break
        self.draw()

    def reset(self) -> None:
        self.app.state["water"][self.tool.slug] = [False] * 8
        self.draw()

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        cups = self.cups()
        w = max(c.winfo_width(), 860)
        c.create_rectangle(0, 0, w, 410, fill="#effaff", outline="")
        c.create_text(310, 78, text=f"今天喝水：{sum(cups)} / 8 杯", fill=INK, font=(self.app.font, 26, "bold"))
        self.draw_canvas_art(c, w - 170, 100, panel=False)
        for i, (x1, y1, x2, y2) in enumerate(self.boxes()):
            h = 98 if cups[i] else 18
            c.create_polygon(x1, y1, x2, y1, x2 - 8, y2, x1 + 8, y2, fill="white", outline="#82cfff", width=3)
            c.create_polygon(x1 + 8, y2 - h, x2 - 8, y2 - h, x2 - 12, y2 - 5, x1 + 12, y2 - 5, fill="#4cc9f0", outline="")
            c.create_text((x1 + x2) / 2, y2 + 28, text=str(i + 1), fill=MUTED, font=(self.app.font, 12, "bold"))


class PlayerPage(BasePage):
    LISTS = {"noise": ["小雨声", "轻风声", "海浪声"], "songs": ["两只老虎", "小星星", "找朋友", "拍手歌"], "stories": ["月亮晚安", "小熊找朋友", "云朵上的房子"]}

    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.kind = tool.kind.split(":")[1]
        self.items = self.LISTS[self.kind]
        self.index = 0
        self.playing = False
        self.progress = 0
        self.canvas = tk.Canvas(self.body, height=390, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        self.bar = ttk.Progressbar(self.body, maximum=60)
        self.bar.pack(fill="x", padx=90, pady=(18, 8))
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=8)
        btn(row, "上一首", self.prev, "#64748b", 10).pack(side="left", padx=7)
        self.play = btn(row, "播放", self.toggle, tool.color, 10)
        self.play.pack(side="left", padx=7)
        btn(row, "下一首", self.next, "#64748b", 10).pack(side="left", padx=7)
        self.draw()

    def toggle(self) -> None:
        self.playing = not self.playing
        self.play.config(text="暂停" if self.playing else "播放")
        if self.playing:
            beep()
            self.tick()
        self.draw()

    def prev(self) -> None:
        self.index = (self.index - 1) % len(self.items)
        self.progress = 0
        self.draw()

    def next(self) -> None:
        self.index = (self.index + 1) % len(self.items)
        self.progress = 0
        self.draw()

    def tick(self) -> None:
        if not self.playing:
            return
        self.progress += 1
        if self.progress >= 60:
            self.next()
        self.draw()
        self.later(1000, self.tick)

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        self.bar["value"] = self.progress
        w, cx = max(c.winfo_width(), 860), max(c.winfo_width(), 860) / 2
        c.create_rectangle(0, 0, w, 390, fill="#f8fbff", outline="")
        name = self.items[self.index]
        c.create_text(cx, 62, text=name, fill=INK, font=(self.app.font, 28, "bold"))
        if self.kind == "noise":
            for i in range(4):
                y = 150 + i * 34
                c.create_arc(cx - 250, y - 25, cx + 250, y + 25, start=0, extent=180, outline="#48cae4", width=5, style="arc")
        elif self.kind == "songs":
            c.create_oval(cx - 110, 120, cx + 110, 300, fill="#fff0f3", outline="#ffafcc", width=5)
            for i, col in enumerate(["#ff4d6d", "#ffd166", "#06d6a0", "#118ab2"]):
                x = cx - 70 + i * 48
                c.create_line(x, 175, x, 260, fill=col, width=8, capstyle="round")
                c.create_oval(x - 18, 240, x + 10, 268, fill=col, outline="")
        else:
            c.create_rectangle(cx - 130, 125, cx + 130, 300, fill="#fff7ed", outline="#b56576", width=5)
            c.create_line(cx, 125, cx, 300, fill="#e2b4a6", width=3)
        c.create_text(cx, 350, text="播放中" if self.playing else "已暂停", fill=MUTED, font=(self.app.font, 14))


class BreathPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.running = True
        self.start = time.time()
        self.canvas = tk.Canvas(self.body, height=450, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=12)
        self.b = btn(row, "暂停", self.toggle, tool.color, 10)
        self.b.pack()
        self.anim()

    def toggle(self) -> None:
        self.running = not self.running
        self.b.config(text="暂停" if self.running else "继续")
        if self.running:
            self.start = time.time()
            self.anim()

    def anim(self) -> None:
        c = self.canvas
        c.delete("all")
        w, cx, cy = max(c.winfo_width(), 860), max(c.winfo_width(), 860) / 2, 215
        t = (time.time() - self.start) % 8
        inhale = t < 4
        phase = t / 4 if inhale else (t - 4) / 4
        r = 78 + 76 * (phase if inhale else 1 - phase)
        c.create_rectangle(0, 0, w, 450, fill="#f0fff4", outline="")
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#8ce99a", outline="#37b24d", width=5)
        c.create_text(cx, cy, text="吸气" if inhale else "呼气", fill=INK, font=(self.app.font, 30, "bold"))
        if self.running:
            self.later(80, self.anim)


class MoodPage(BasePage):
    MOODS = [("开心", "#ffd166"), ("平静", "#9bf6ff"), ("生气", "#ff6b6b"), ("难过", "#a0c4ff"), ("害怕", "#cdb4db"), ("兴奋", "#b8f2e6")]

    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.current = self.MOODS[0]
        self.canvas = tk.Canvas(self.body, height=360, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        grid = tk.Frame(self.body, bg=BG)
        grid.pack(pady=16)
        for i, mood in enumerate(self.MOODS):
            btn(grid, mood[0], lambda m=mood: self.set(m), mood[1], 10).grid(row=i // 3, column=i % 3, padx=8, pady=8)
        self.draw()

    def set(self, mood: tuple[str, str]) -> None:
        self.current = mood
        self.draw()

    def draw(self) -> None:
        name, color = self.current
        c = self.canvas
        c.delete("all")
        w, cx, cy = max(c.winfo_width(), 860), max(c.winfo_width(), 860) / 2, 160
        c.create_rectangle(0, 0, w, 360, fill="#fffdf7", outline="")
        c.create_oval(cx - 105, cy - 105, cx + 105, cy + 105, fill=color, outline="#e2e8f0", width=4)
        c.create_oval(cx - 38, cy - 25, cx - 20, cy - 7, fill=INK, outline="")
        c.create_oval(cx + 20, cy - 25, cx + 38, cy - 7, fill=INK, outline="")
        if name in {"开心", "兴奋", "平静"}:
            c.create_arc(cx - 48, cy - 16, cx + 48, cy + 68, start=200, extent=140, outline=INK, width=5, style="arc")
        elif name == "难过":
            c.create_arc(cx - 48, cy + 20, cx + 48, cy + 95, start=20, extent=140, outline=INK, width=5, style="arc")
        else:
            c.create_line(cx - 42, cy + 48, cx + 42, cy + 48, fill=INK, width=5)
        c.create_text(cx, 315, text=f"今天我感觉：{name}", fill=INK, font=(self.app.font, 24, "bold"))


class CardsPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.kind = tool.kind.split(":")[1]
        self.i = 0
        self.flip = False
        self.items = get_card_items(tool, self.kind)
        self.canvas = tk.Canvas(self.body, height=450, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=14)
        btn(row, "上一张", self.prev, "#64748b", 10).pack(side="left", padx=6)
        btn(row, "翻卡/发音", self.action, tool.color, 12).pack(side="left", padx=6)
        btn(row, "下一张", self.next, "#64748b", 10).pack(side="left", padx=6)
        self.draw()

    def prev(self) -> None:
        self.i = (self.i - 1) % len(self.items)
        self.flip = False
        self.draw()

    def next(self) -> None:
        self.i = (self.i + 1) % len(self.items)
        self.flip = False
        self.draw()

    def action(self) -> None:
        self.flip = not self.flip
        beep()
        self.draw()

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        title, text, color = self.items[self.i]
        w, cx, cy = max(c.winfo_width(), 860), max(c.winfo_width(), 860) / 2, 225
        asset = self.app.card_image(self.tool, self.i)
        if asset:
            c.create_rectangle(0, 0, w, 450, fill="#f8fbff", outline="")
            c.create_rectangle(cx - 210, 44, cx + 210, 324, fill="#ffffff", outline="#dbe4ee", width=3)
            c.create_image(cx, 178, image=asset)
            shown = text if self.flip else title
            c.create_text(cx, 356, text=shown, fill=INK, font=(self.app.font, 24 if not self.flip else 18, "bold"), width=560)
            c.create_text(cx, 412, text=f"{self.i + 1} / {len(self.items)} · 点击翻卡看提示", fill=MUTED, font=(self.app.font, 13, "bold"))
            return
        if self.kind == "colors":
            c.create_rectangle(0, 0, w, 450, fill=color, outline="")
            fg = INK if title == "黄色" else "white"
            c.create_text(cx, 185, text=title, fill=fg, font=(self.app.font, 54, "bold"))
            c.create_text(cx, 275, text=text, fill=fg, font=(self.app.font, 22, "bold"))
            return
        c.create_rectangle(0, 0, w, 450, fill="#fbfdff", outline="")
        c.create_rectangle(cx - 230, 62, cx + 230, 375, fill=color, outline="#d1d5db", width=3)
        if self.tool.slug in CARD_OVERRIDE:
            c.create_text(cx, 170, text=title, fill=INK, font=(self.app.font, 38, "bold"), width=380)
            c.create_text(cx, 250, text=text, fill="#475569", font=(self.app.font, 20, "bold"), width=390)
            c.create_line(cx - 135, 310, cx + 135, 310, fill="#ffffff", width=5)
            c.create_text(cx, 345, text="点击翻卡或切换下一张", fill=MUTED, font=(self.app.font, 13, "bold"))
        elif self.kind == "numbers":
            n = int(title)
            c.create_text(cx, 130, text=title, fill=INK, font=(self.app.font, 64, "bold"))
            start = cx - min(n, 5) * 34 + 34
            for k in range(n):
                x, y = start + (k % 5) * 68, 245 + (k // 5) * 60
                c.create_oval(x - 20, y - 20, x + 20, y + 20, fill="white", outline="#64748b", width=3)
        elif self.kind == "shapes":
            self.draw_shape(c, cx, cy, title)
        elif self.kind == "animals":
            c.create_oval(cx - 86, cy - 72, cx + 86, cy + 74, fill="white", outline=INK, width=4)
            c.create_oval(cx - 34, cy - 18, cx - 18, cy - 2, fill=INK, outline="")
            c.create_oval(cx + 18, cy - 18, cx + 34, cy - 2, fill=INK, outline="")
            c.create_text(cx, cy + 45, text=text, fill=INK, font=(self.app.font, 20, "bold"))
        else:
            shown = text if self.flip or self.kind != "letters" else title
            c.create_text(cx, cy - 20, text=shown, fill=INK, font=(self.app.font, 36, "bold"), width=390)
        c.create_text(cx, 405, text=title if self.kind != "letters" else ("背面" if self.flip else "正面"), fill=MUTED, font=(self.app.font, 16, "bold"))

    def draw_shape(self, c: tk.Canvas, cx: float, cy: float, title: str) -> None:
        if title == "圆形":
            c.create_oval(cx - 92, cy - 92, cx + 92, cy + 92, fill="white", outline=INK, width=5)
        elif title == "三角形":
            c.create_polygon(cx, cy - 105, cx - 105, cy + 90, cx + 105, cy + 90, fill="white", outline=INK, width=5)
        elif title == "方形":
            c.create_rectangle(cx - 92, cy - 92, cx + 92, cy + 92, fill="white", outline=INK, width=5)
        elif title == "长方形":
            c.create_rectangle(cx - 135, cy - 70, cx + 135, cy + 70, fill="white", outline=INK, width=5)
        else:
            c.create_polygon(star(cx, cy, 108, 45), fill="white", outline=INK, width=5)
        c.create_text(cx, 125, text=title, fill=INK, font=(self.app.font, 32, "bold"))


class StoryPage(BasePage):
    PAGES = [("小星星", "夜晚来了，小星星一颗一颗亮起来。"), ("小房子", "小朋友回到温暖的小房子里。"), ("说晚安", "月亮轻轻说：晚安，明天见。")]

    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.i = 0
        self.canvas = tk.Canvas(self.body, height=460, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x")
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=14)
        btn(row, "上一页", self.prev, "#64748b", 12).pack(side="left", padx=8)
        btn(row, "下一页", self.next, tool.color, 12).pack(side="left", padx=8)
        self.draw()

    def prev(self) -> None:
        self.i = max(0, self.i - 1)
        self.draw()

    def next(self) -> None:
        self.i = min(len(self.PAGES) - 1, self.i + 1)
        self.draw()

    def draw(self) -> None:
        title, text = self.PAGES[self.i]
        c = self.canvas
        c.delete("all")
        w, cx = max(c.winfo_width(), 860), max(c.winfo_width(), 860) / 2
        c.create_rectangle(0, 0, w, 460, fill="#f8fbff", outline="")
        c.create_rectangle(cx - 300, 45, cx + 300, 398, fill="#fffaf0", outline="#d7c7a9", width=4)
        for x, y in [(cx - 130, 120), (cx + 10, 180), (cx + 150, 120)]:
            c.create_polygon(star(x, y, 22, 9), fill="#ffd166", outline="")
        c.create_text(cx, 310, text=title, fill=INK, font=(self.app.font, 28, "bold"))
        c.create_text(cx, 360, text=text, fill=MUTED, font=(self.app.font, 18), width=520)
        c.create_text(cx, 425, text=f"{self.i + 1} / {len(self.PAGES)}", fill=MUTED, font=(self.app.font, 12, "bold"))


class DrawingPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.color = "#ef4444"
        self.size = tk.IntVar(value=8)
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        for col in ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#111827", "#ffffff"]:
            tk.Button(row, bg=col, width=4, command=lambda c=col: setattr(self, "color", c), relief="solid", bd=1).pack(side="left", padx=4)
        tk.Scale(row, from_=2, to=24, orient="horizontal", variable=self.size, bg=BG, highlightthickness=0, length=180).pack(side="left", padx=18)
        btn(row, "清空", self.clear_canvas, "#64748b", 8).pack(side="right")
        self.canvas = tk.Canvas(self.body, bg="white", height=500, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True)
        self.last: tuple[int, int] | None = None
        self.canvas.bind("<Button-1>", lambda e: setattr(self, "last", (e.x, e.y)))
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: setattr(self, "last", None))
        self.draw_guide()

    def clear_canvas(self) -> None:
        self.canvas.delete("all")
        self.draw_guide()

    def draw_guide(self) -> None:
        c = self.canvas
        asset = self.app.card_image(self.tool, 0)
        if asset:
            c.create_image(835, 122, image=asset, tags=("guide",))
        c.create_rectangle(650, 250, 1020, 318, fill="#ffffff", outline="#dbe4ee", width=2, tags=("guide",))
        c.create_text(835, 284, text=drawing_prompt(self.tool), fill=MUTED, font=(self.app.font, 13, "bold"), width=320, tags=("guide",))
        if self.tool.slug == "shape_drawing":
            c.create_oval(90, 92, 210, 212, outline="#cbd5e1", width=4, tags=("guide",))
            c.create_rectangle(250, 92, 370, 212, outline="#cbd5e1", width=4, tags=("guide",))
            c.create_polygon(470, 92, 405, 212, 535, 212, outline="#cbd5e1", fill="", width=4, tags=("guide",))
        elif self.tool.slug == "line_practice":
            for y in [110, 170, 230, 290]:
                c.create_line(70, y, 560, y + (20 if y % 2 else -20), fill="#cbd5e1", width=4, dash=(14, 10), smooth=True, tags=("guide",))
        elif self.tool.slug == "name_doodle":
            c.create_text(310, 185, text="我的名字", fill="#e2e8f0", font=(self.app.font, 46, "bold"), tags=("guide",))

    def move(self, e: tk.Event) -> None:
        if not self.last:
            self.last = (e.x, e.y)
            return
        x, y = self.last
        self.canvas.create_line(x, y, e.x, e.y, fill=self.color, width=self.size.get(), capstyle="round", smooth=True)
        self.last = (e.x, e.y)


class ColoringPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.color = "#ef4444"
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        for col in ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#ffffff"]:
            tk.Button(row, bg=col, width=5, command=lambda c=col: setattr(self, "color", c), relief="solid", bd=1).pack(side="left", padx=4)
        btn(row, "重画", self.draw_pic, "#64748b", 8).pack(side="right")
        self.canvas = tk.Canvas(self.body, bg="#f8fbff", height=500, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.fill)
        self.draw_pic()

    def draw_pic(self) -> None:
        c = self.canvas
        c.delete("all")
        c.create_rectangle(0, 0, 1100, 500, fill="#e0f2fe", outline="")
        asset = self.app.card_image(self.tool, 0)
        if asset:
            c.create_image(860, 135, image=asset)
            c.create_rectangle(710, 260, 1010, 310, fill="white", outline="#dbe4ee", width=2)
            c.create_text(860, 285, text="选颜色后点击左侧线稿填色", fill=MUTED, font=(self.app.font, 13, "bold"))
        for tag, item in [
            ("sun", c.create_oval(70, 55, 165, 150, fill="white", outline=INK, width=3)),
            ("house", c.create_rectangle(300, 230, 580, 410, fill="white", outline=INK, width=4)),
            ("roof", c.create_polygon(260, 230, 440, 120, 620, 230, fill="white", outline=INK, width=4)),
            ("door", c.create_rectangle(415, 310, 470, 410, fill="white", outline=INK, width=3)),
            ("tree", c.create_rectangle(690, 250, 725, 410, fill="white", outline=INK, width=4)),
            ("leaf", c.create_oval(625, 120, 790, 290, fill="white", outline=INK, width=4)),
            ("grass", c.create_rectangle(0, 410, 1100, 500, fill="white", outline=INK, width=2)),
        ]:
            c.addtag_withtag("region_" + tag, item)

    def fill(self, _e: tk.Event) -> None:
        cur = self.canvas.find_withtag("current")
        if cur:
            tag = next((t for t in self.canvas.gettags(cur[0]) if t.startswith("region_")), None)
            if tag:
                self.canvas.itemconfigure(tag, fill=self.color)


class StickersPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.selected = "星星"
        self.count = 0
        self.drag: tuple[str, int, int] | None = None
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        for name in sticker_names(tool):
            btn(row, name, lambda n=name: setattr(self, "selected", n), tool.color, 8).pack(side="left", padx=4)
        btn(row, "清空", self.reset, "#64748b", 8).pack(side="right")
        self.canvas = tk.Canvas(self.body, bg="#cdeffd", height=500, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True)
        self.reset()
        self.canvas.bind("<Button-1>", self.place)

    def reset(self) -> None:
        self.canvas.delete("all")
        asset = self.app.card_image(self.tool, 0)
        if asset:
            self.canvas.create_image(830, 150, image=asset)
        self.canvas.create_rectangle(0, 370, 1100, 520, fill="#b7e4c7", outline="")
        self.canvas.create_oval(70, 58, 145, 133, fill="#ffd166", outline="")
        self.canvas.create_rectangle(620, 282, 1040, 334, fill="white", outline="#dbe4ee", width=2)
        self.canvas.create_text(830, 308, text="选择贴纸后点在画面上，已有贴纸可以拖动", fill=MUTED, font=(self.app.font, 13, "bold"))

    def place(self, e: tk.Event) -> None:
        cur = self.canvas.find_withtag("current")
        if cur and any(t.startswith("s_") for t in self.canvas.gettags(cur[0])):
            return
        self.count += 1
        tag = f"s_{self.count}"
        x, y = e.x, e.y
        if self.selected == "星星":
            self.canvas.create_polygon(star(x, y, 34, 15), fill="#ffd166", outline="#eab308", width=2, tags=(tag,))
        elif self.selected == "爱心":
            self.canvas.create_oval(x - 36, y - 28, x, y + 10, fill="#fb7185", outline="", tags=(tag,))
            self.canvas.create_oval(x, y - 28, x + 36, y + 10, fill="#fb7185", outline="", tags=(tag,))
            self.canvas.create_polygon(x - 35, y - 5, x + 35, y - 5, x, y + 45, fill="#fb7185", outline="#be123c", width=2, tags=(tag,))
        elif self.selected == "太阳":
            self.canvas.create_oval(x - 32, y - 32, x + 32, y + 32, fill="#ffd166", outline="#f59e0b", width=2, tags=(tag,))
            for a in range(0, 360, 45):
                r = math.radians(a)
                self.canvas.create_line(x + math.cos(r) * 40, y + math.sin(r) * 40, x + math.cos(r) * 54, y + math.sin(r) * 54, fill="#f59e0b", width=3, tags=(tag,))
        elif self.selected == "雨滴":
            self.canvas.create_oval(x - 22, y - 5, x + 22, y + 42, fill="#60a5fa", outline="#2563eb", width=2, tags=(tag,))
            self.canvas.create_polygon(x, y - 44, x - 22, y + 8, x + 22, y + 8, fill="#60a5fa", outline="#2563eb", width=2, tags=(tag,))
        elif self.selected == "彩虹":
            for i, col in enumerate(["#ef4444", "#f97316", "#facc15", "#22c55e", "#3b82f6"]):
                self.canvas.create_arc(x - 70 + i * 9, y - 32 + i * 9, x + 70 - i * 9, y + 108 - i * 9, start=0, extent=180, outline=col, width=8, style="arc", tags=(tag,))
        elif self.selected == "气球":
            self.canvas.create_oval(x - 26, y - 34, x + 26, y + 28, fill="#ff7a90", outline="#be123c", width=2, tags=(tag,))
            self.canvas.create_line(x, y + 28, x - 8, y + 74, fill="#64748b", width=2, tags=(tag,))
        elif self.selected == "云朵":
            for dx, rr in [(-28, 24), (0, 32), (32, 24)]:
                self.canvas.create_oval(x + dx - rr, y - rr, x + dx + rr, y + rr, fill="white", outline="#cbd5e1", width=2, tags=(tag,))
        elif self.selected == "小鸡":
            self.canvas.create_oval(x - 34, y - 28, x + 34, y + 38, fill="#fde68a", outline="#ca8a04", width=2, tags=(tag,))
            self.canvas.create_oval(x - 12, y - 4, x - 5, y + 3, fill=INK, outline="", tags=(tag,))
            self.canvas.create_oval(x + 5, y - 4, x + 12, y + 3, fill=INK, outline="", tags=(tag,))
            self.canvas.create_polygon(x - 5, y + 8, x + 5, y + 8, x, y + 16, fill="#fb923c", outline="", tags=(tag,))
        elif self.selected == "苹果":
            self.canvas.create_oval(x - 34, y - 18, x + 8, y + 36, fill="#ef4444", outline="#991b1b", width=2, tags=(tag,))
            self.canvas.create_oval(x - 4, y - 18, x + 38, y + 36, fill="#f87171", outline="#991b1b", width=2, tags=(tag,))
            self.canvas.create_line(x + 4, y - 20, x + 12, y - 44, fill="#78350f", width=3, tags=(tag,))
        else:
            self.canvas.create_oval(x - 38, y - 38, x + 38, y + 38, fill="#ffafcc", outline="", tags=(tag,))
            self.canvas.create_oval(x - 16, y - 16, x + 16, y + 16, fill="#ffe066", outline="", tags=(tag,))
        self.canvas.tag_bind(tag, "<ButtonPress-1>", lambda ev, t=tag: self.start_drag(ev, t))
        self.canvas.tag_bind(tag, "<B1-Motion>", self.move_drag)
        self.canvas.tag_bind(tag, "<ButtonRelease-1>", lambda _e: setattr(self, "drag", None))

    def start_drag(self, e: tk.Event, tag: str) -> None:
        self.drag = (tag, e.x, e.y)

    def move_drag(self, e: tk.Event) -> None:
        if self.drag:
            tag, x, y = self.drag
            self.canvas.move(tag, e.x - x, e.y - y)
            self.drag = (tag, e.x, e.y)


class GamePage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.kind = tool.kind.split(":")[1]
        self.canvas = tk.Canvas(self.body, height=520, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.click)
        self.status = ""
        self.init_game()
        row = tk.Frame(self.body, bg=BG)
        row.pack(pady=10)
        btn(row, "重新开始", self.restart, tool.color, 12).pack()
        self.draw()

    def init_game(self) -> None:
        k = self.kind
        if k == "puzzle":
            self.pieces = list(range(1, 7)); random.shuffle(self.pieces); self.sel = None
        elif k == "spot":
            self.found = set()
        elif k == "match":
            self.left = ["小猫", "小狗", "小鱼", "小鸟"]; self.right = self.left[:]; random.shuffle(self.right); self.sel = None; self.matches = {}
        elif k == "memory":
            self.cards = ["猫", "狗", "鱼", "车"] * 2; random.shuffle(self.cards); self.opened = set(); self.matched = set(); self.pick = []
        elif k == "sort":
            self.values = [1, 2, 3, 4, 5]; random.shuffle(self.values); self.order = []
        elif k == "count":
            self.target = random.randint(1, 6)
        elif k == "classify":
            self.items = [("小猫", "动物"), ("苹果", "水果"), ("积木", "玩具"), ("小狗", "动物"), ("香蕉", "水果"), ("皮球", "玩具")]; self.sel = None; self.done = set()
        elif k == "lottery":
            self.lottery_items = get_lottery_items(self.tool)
            self.current = "点击抽一张"
        elif k == "wheel":
            self.rewards = get_wheel_rewards(self.tool); self.angle = 0; self.steps = 0; self.result = ""

    def restart(self) -> None:
        self.status = ""
        self.init_game()
        self.draw()

    def click(self, e: tk.Event) -> None:
        getattr(self, "click_" + self.kind, lambda _e: None)(e)

    def draw(self) -> None:
        self.canvas.delete("all")
        getattr(self, "draw_" + self.kind)()

    def click_puzzle(self, e: tk.Event) -> None:
        col, row = (e.x - 260) // 130, (e.y - 70) // 130
        if 0 <= col < 3 and 0 <= row < 2:
            idx = int(row * 3 + col)
            if self.sel is None:
                self.sel = idx
            else:
                self.pieces[self.sel], self.pieces[idx] = self.pieces[idx], self.pieces[self.sel]; self.sel = None
            self.draw()

    def draw_puzzle(self) -> None:
        colors = ["#ffadad", "#ffd6a5", "#fdffb6", "#caffbf", "#9bf6ff", "#bdb2ff"]
        for i, p in enumerate(self.pieces):
            r, col = divmod(i, 3); x, y = 260 + col * 130, 70 + r * 130
            self.canvas.create_rectangle(x, y, x + 126, y + 126, fill=colors[p - 1], outline=BAD if self.sel == i else "white", width=5)
            self.canvas.create_text(x + 63, y + 63, text=str(p), fill=INK, font=(self.app.font, 40, "bold"))
        ok = self.pieces == [1, 2, 3, 4, 5, 6]
        self.canvas.create_text(455, 398, text="完成" if ok else "点击两块交换位置", fill=GOOD if ok else MUTED, font=(self.app.font, 18, "bold"))

    def click_spot(self, e: tk.Event) -> None:
        for i, (x, y, r) in enumerate([(135, 90, 32), (240, 236, 30), (115, 250, 30)]):
            if math.hypot(e.x - x, e.y - y) <= r or math.hypot(e.x - (x + 500), e.y - y) <= r:
                self.found.add(i); self.draw(); return

    def scene(self, off: int, right: bool) -> None:
        c = self.canvas
        c.create_rectangle(off + 30, 40, off + 430, 430, fill="#e0f2fe", outline="#cbd5e1", width=3)
        c.create_oval(off + 102, 58, off + 168, 124, fill="#f97316" if right else "#ffd166", outline="")
        c.create_rectangle(off + 178, 215, off + 320, 345, fill="#fff7ed", outline=INK, width=3)
        c.create_polygon(off + 160, 215, off + 250, 145, off + 340, 215, fill="#ef476f", outline=INK, width=3)
        c.create_rectangle(off + 188, 236, off + 225, 270, fill="white", outline=INK, width=2)
        if not right:
            c.create_rectangle(off + 274, 236, off + 311, 270, fill="white", outline=INK, width=2)
        c.create_oval(off + 90, 240, off + 140, 290, fill="#ffafcc" if right else "#bde0fe", outline=INK, width=2)

    def draw_spot(self) -> None:
        self.scene(0, False); self.scene(500, True)
        for i in self.found:
            x, y, r = [(135, 90, 32), (240, 236, 30), (115, 250, 30)][i]
            for off in (0, 500):
                self.canvas.create_oval(off + x - r, y - r, off + x + r, y + r, outline=GOOD, width=5)
        self.canvas.create_text(480, 475, text=f"找到 {len(self.found)} / 3 处不同", fill=INK, font=(self.app.font, 18, "bold"))

    def click_match(self, e: tk.Event) -> None:
        row = (e.y - 90) // 85
        if not 0 <= row < 4:
            return
        if 90 <= e.x <= 310:
            self.sel = self.left[int(row)]
        elif 650 <= e.x <= 870 and self.sel and self.right[int(row)] == self.sel:
            self.matches[self.sel] = self.sel; self.sel = None
        self.draw()

    def draw_match(self) -> None:
        pos_l = {}; pos_r = {}
        for i, v in enumerate(self.left):
            y = 90 + i * 85; col = "#fde68a" if v == self.sel else ("#dcfce7" if v in self.matches else "#f8fafc")
            self.canvas.create_rectangle(90, y, 310, y + 58, fill=col, outline="#cbd5e1", width=2)
            self.canvas.create_text(200, y + 29, text=v, fill=INK, font=(self.app.font, 17, "bold")); pos_l[v] = (310, y + 29)
        for i, v in enumerate(self.right):
            y = 90 + i * 85
            self.canvas.create_rectangle(650, y, 870, y + 58, fill="#dcfce7" if v in self.matches else "#f1f5f9", outline="#cbd5e1", width=2)
            self.canvas.create_text(760, y + 29, text=f"{v}影子", fill=INK, font=(self.app.font, 17, "bold")); pos_r[v] = (650, y + 29)
        for v in self.matches:
            self.canvas.create_line(*pos_l[v], *pos_r[v], fill=GOOD, width=5)
        self.canvas.create_text(480, 468, text=f"已配对 {len(self.matches)} / 4", fill=MUTED, font=(self.app.font, 16, "bold"))

    def click_memory(self, e: tk.Event) -> None:
        col, row = (e.x - 230) // 125, (e.y - 80) // 145
        if not (0 <= col < 4 and 0 <= row < 2):
            return
        i = int(row * 4 + col)
        if i in self.opened or i in self.matched or len(self.pick) >= 2:
            return
        self.opened.add(i); self.pick.append(i); self.draw()
        if len(self.pick) == 2:
            a, b = self.pick
            if self.cards[a] == self.cards[b]:
                self.matched.update(self.pick); self.pick.clear(); self.draw()
            else:
                self.later(650, self.hide_memory)

    def hide_memory(self) -> None:
        for i in self.pick:
            self.opened.discard(i)
        self.pick.clear(); self.draw()

    def draw_memory(self) -> None:
        for i, v in enumerate(self.cards):
            r, col = divmod(i, 4); x, y = 230 + col * 125, 80 + r * 145; face = i in self.opened or i in self.matched
            self.canvas.create_rectangle(x, y, x + 95, y + 115, fill="#dcfce7" if i in self.matched else ("#fff7ed" if face else "#90cdf4"), outline="#cbd5e1", width=3)
            self.canvas.create_text(x + 48, y + 58, text=v if face else "?", fill=INK, font=(self.app.font, 30, "bold"))
        self.canvas.create_text(480, 430, text=f"配对成功 {len(self.matched) // 2} / 4", fill=MUTED, font=(self.app.font, 16, "bold"))

    def click_sort(self, e: tk.Event) -> None:
        for i, v in enumerate(self.values):
            x, y = 160 + i * 150, 120
            if v not in self.order and x <= e.x <= x + 105 and y <= e.y <= y + 105:
                self.order.append(v); self.draw(); return

    def draw_sort(self) -> None:
        self.canvas.create_text(485, 60, text="从小到大点选卡片", fill=INK, font=(self.app.font, 20, "bold"))
        for i, v in enumerate(self.values):
            x, y, size = 160 + i * 150, 120, 42 + v * 12
            self.canvas.create_rectangle(x, y, x + 105, y + 105, fill="#f8fafc", outline="#cbd5e1", width=2)
            self.canvas.create_oval(x + 52 - size / 2, y + 52 - size / 2, x + 52 + size / 2, y + 52 + size / 2, fill="#e2e8f0" if v in self.order else "#bde0fe", outline="#577590", width=3)
        for i, v in enumerate(self.order):
            self.canvas.create_text(250 + i * 100, 360, text=str(v), fill=INK, font=(self.app.font, 30, "bold"))
        if len(self.order) == 5:
            self.canvas.create_text(485, 455, text="排序正确" if self.order == sorted(self.order) else "再试一次", fill=GOOD if self.order == sorted(self.order) else BAD, font=(self.app.font, 18, "bold"))

    def click_count(self, e: tk.Event) -> None:
        for i in range(1, 7):
            x, y = 260 + (i - 1) * 75, 330
            if x <= e.x <= x + 56 and y <= e.y <= y + 50:
                self.status = "答对了" if i == self.target else "再数一数"; self.draw(); return

    def draw_count(self) -> None:
        self.canvas.create_text(480, 65, text="这里有几只小动物？", fill=INK, font=(self.app.font, 22, "bold"))
        for i in range(self.target):
            x, y = 480 - (self.target - 1) * 55 + i * 110, 210
            self.canvas.create_oval(x - 38, y - 32, x + 38, y + 40, fill="#ffe8b5", outline="#bc6c25", width=3)
        for i in range(1, 7):
            x, y = 260 + (i - 1) * 75, 330
            self.canvas.create_rectangle(x, y, x + 56, y + 50, fill=self.tool.color, outline="")
            self.canvas.create_text(x + 28, y + 25, text=str(i), fill="white", font=(self.app.font, 16, "bold"))
        self.canvas.create_text(480, 430, text=self.status, fill=GOOD if self.status == "答对了" else BAD, font=(self.app.font, 18, "bold"))

    def click_classify(self, e: tk.Event) -> None:
        for i, (_n, _c) in enumerate(self.items):
            x, y = 145 + i * 130, 110
            if i not in self.done and x <= e.x <= x + 92 and y <= e.y <= y + 75:
                self.sel = i; self.draw(); return
        if self.sel is not None:
            for j, basket in enumerate(["动物", "水果", "玩具"]):
                x, y = 175 + j * 230, 330
                if x <= e.x <= x + 170 and y <= e.y <= y + 105:
                    if self.items[self.sel][1] == basket:
                        self.done.add(self.sel); self.sel = None
                    self.draw(); return

    def draw_classify(self) -> None:
        self.canvas.create_text(480, 55, text="先点物品，再点对应篮子", fill=INK, font=(self.app.font, 20, "bold"))
        for i, (name, _cat) in enumerate(self.items):
            if i in self.done:
                continue
            x, y = 145 + i * 130, 110
            self.canvas.create_rectangle(x, y, x + 92, y + 75, fill="#fde68a" if i == self.sel else "#f8fafc", outline="#cbd5e1", width=2)
            self.canvas.create_text(x + 46, y + 38, text=name, fill=INK, font=(self.app.font, 15, "bold"))
        for j, basket in enumerate(["动物", "水果", "玩具"]):
            x, y = 175 + j * 230, 330
            self.canvas.create_rectangle(x, y, x + 170, y + 105, fill=["#dcfce7", "#fff7ed", "#dbeafe"][j], outline="#94a3b8", width=3)
            self.canvas.create_text(x + 85, y + 52, text=basket, fill=INK, font=(self.app.font, 20, "bold"))
        self.canvas.create_text(480, 490, text=f"已分类 {len(self.done)} / {len(self.items)}", fill=MUTED, font=(self.app.font, 16, "bold"))

    def click_lottery(self, _e: tk.Event) -> None:
        self.current = random.choice(self.lottery_items); self.draw()

    def draw_lottery(self) -> None:
        asset = self.app.card_image(self.tool, 0)
        if asset:
            self.canvas.create_image(480, 150, image=asset)
        self.canvas.create_rectangle(260, 292, 700, 405, fill="white", outline=self.tool.color, width=5)
        self.canvas.create_text(480, 348, text=self.current, fill=INK, font=(self.app.font, 27, "bold"), width=360)
        self.canvas.create_text(480, 455, text="点击插画或卡片再抽一次", fill=MUTED, font=(self.app.font, 15, "bold"))

    def click_wheel(self, _e: tk.Event) -> None:
        if self.steps:
            return
        self.steps = random.randint(28, 46); self.spin()

    def spin(self) -> None:
        if self.steps <= 0:
            idx = int(((360 - self.angle + 90) % 360) // 60) % 6; self.result = self.rewards[idx]; self.draw(); return
        self.angle = (self.angle + self.steps * 2.8) % 360; self.steps -= 1; self.draw(); self.later(45, self.spin)

    def draw_wheel(self) -> None:
        asset = self.app.card_image(self.tool, 0)
        if asset:
            self.canvas.create_image(210, 150, image=asset)
        cx, cy, r = 610, 230, 170; cols = ["#ffadad", "#ffd6a5", "#fdffb6", "#caffbf", "#9bf6ff", "#bdb2ff"]
        for i, reward in enumerate(self.rewards):
            start = self.angle + i * 60
            self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=60, fill=cols[i], outline="white", width=3)
            mid = math.radians(start + 30)
            self.canvas.create_text(cx + math.cos(mid) * 105, cy - math.sin(mid) * 105, text=reward, fill=INK, font=(self.app.font, 13, "bold"))
        self.canvas.create_polygon(cx, cy - r - 26, cx - 18, cy - r + 18, cx + 18, cy - r + 18, fill=BAD, outline="")
        self.canvas.create_text(cx, 455, text=(f"今天奖励：{self.result}" if self.result else "点击转盘开始"), fill=GOOD if self.result else MUTED, font=(self.app.font, 20, "bold"))


class AttendancePage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        photo = app.card_image(tool, 0)
        if photo:
            tk.Label(self.body, image=photo, bg=BG, bd=0).pack(pady=(0, 10))
        self.grid = tk.Frame(self.body, bg=BG); self.grid.pack(fill="both", expand=True)
        row = tk.Frame(self.body, bg=BG); row.pack(pady=10)
        btn(row, "全部清空", self.clear_all, "#64748b", 12).pack(side="left", padx=8)
        btn(row, "全部到齐", self.all_present, tool.color, 12).pack(side="left", padx=8)
        self.label = tk.Label(row, bg=BG, fg=MUTED, font=(app.font, 14, "bold")); self.label.pack(side="left", padx=14)
        self.draw()

    def clear_all(self) -> None:
        for n in self.app.state["attendance"]:
            self.app.state["attendance"][n] = False
        self.draw()

    def all_present(self) -> None:
        for n in self.app.state["attendance"]:
            self.app.state["attendance"][n] = True
        self.draw()

    def toggle(self, name: str) -> None:
        self.app.state["attendance"][name] = not self.app.state["attendance"][name]; self.draw()

    def draw(self) -> None:
        clear(self.grid); state = self.app.state["attendance"]
        for i, (name, present) in enumerate(state.items()):
            tk.Button(self.grid, text=f"{name}\n{'已到' if present else '未到'}", command=lambda n=name: self.toggle(n), bg=GOOD if present else "#cbd5e1", fg="white" if present else INK, relief="flat", bd=0, font=(self.app.font, 17, "bold"), width=10, height=4, cursor="hand2").grid(row=i // 4, column=i % 4, padx=10, pady=10, sticky="nsew")
        for col in range(4):
            self.grid.grid_columnconfigure(col, weight=1)
        self.label.config(text=f"已到 {sum(state.values())} / {len(state)}")


class HelperPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        self.highlight = -1; self.result = ""; self.steps = 0
        self.canvas = tk.Canvas(self.body, height=500, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); self.canvas.pack(fill="both", expand=True)
        btn(self.body, "抽取值日生", self.start, tool.color, 14).pack(pady=10)
        self.draw()

    def start(self) -> None:
        self.steps = 24; self.result = ""; self.anim()

    def anim(self) -> None:
        if self.steps <= 0:
            self.result = NAMES[self.highlight]; self.draw(); return
        self.highlight = random.randrange(len(NAMES)); self.steps -= 1; self.draw(); self.later(80, self.anim)

    def draw(self) -> None:
        c = self.canvas; c.delete("all")
        asset = self.app.card_image(self.tool, 0)
        if asset:
            c.create_image(790, 155, image=asset)
        for i, name in enumerate(NAMES):
            r, col = divmod(i, 4); x, y = 95 + col * 142, 72 + r * 100
            c.create_oval(x, y, x + 82, y + 82, fill="#fde68a" if i == self.highlight else "#f8fafc", outline=self.tool.color if i == self.highlight else "#cbd5e1", width=4 if i == self.highlight else 3)
            c.create_text(x + 41, y + 41, text=name, fill=INK, font=(self.app.font, 15, "bold"))
        if self.result:
            c.create_rectangle(620, 338, 930, 418, fill="white", outline=self.tool.color, width=4)
            c.create_text(775, 378, text=f"今日小帮手：{self.result}", fill=GOOD, font=(self.app.font, 23, "bold"))


class GroupsPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        row = tk.Frame(self.body, bg=BG); row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text="名单", bg=BG, fg=INK, font=(app.font, 11, "bold")).pack(side="left")
        self.entry = tk.Entry(row, font=(app.font, 11), relief="flat"); self.entry.insert(0, "、".join(NAMES)); self.entry.pack(side="left", fill="x", expand=True, padx=10, ipady=8)
        btn(row, "随机分组", self.assign, tool.color, 12).pack(side="left")
        self.canvas = tk.Canvas(self.body, height=500, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); self.canvas.pack(fill="both", expand=True)
        self.assign()

    def assign(self) -> None:
        names = [x.strip() for x in self.entry.get().replace(",", "、").replace("，", "、").split("、") if x.strip()]
        random.shuffle(names); self.groups = {"红队": [], "蓝队": [], "绿队": []}
        for i, n in enumerate(names):
            list(self.groups.values())[i % 3].append(n)
        self.draw()

    def draw(self) -> None:
        c = self.canvas; c.delete("all")
        asset = self.app.card_image(self.tool, 0)
        if asset:
            c.create_image(480, 115, image=asset)
        for i, (group, names) in enumerate(self.groups.items()):
            x = 120 + i * 280
            c.create_rectangle(x, 210, x + 220, 470, fill=["#fecaca", "#bfdbfe", "#bbf7d0"][i], outline="#cbd5e1", width=3)
            c.create_text(x + 110, 247, text=group, fill=INK, font=(self.app.font, 22, "bold"))
            for j, name in enumerate(names[:5]):
                c.create_rectangle(x + 45, 292 + j * 34, x + 175, 318 + j * 34, fill="white", outline="")
                c.create_text(x + 110, 305 + j * 34, text=name, fill=INK, font=(self.app.font, 12, "bold"))
            if len(names) > 5:
                c.create_text(x + 110, 465, text=f"还有 {len(names) - 5} 位", fill=MUTED, font=(self.app.font, 11, "bold"))


class StarsPage(BasePage):
    def __init__(self, parent: tk.Widget, app: App, tool: Tool) -> None:
        super().__init__(parent, app, tool)
        row = tk.Frame(self.body, bg=BG); row.pack(fill="x", pady=(0, 10))
        for task in get_star_tasks(tool):
            btn(row, task, self.add, tool.color, 10).pack(side="left", padx=4)
        btn(row, "清空", self.clear, "#64748b", 8).pack(side="right")
        self.canvas = tk.Canvas(self.body, height=500, bg=PANEL, highlightthickness=1, highlightbackground=BORDER); self.canvas.pack(fill="both", expand=True)
        self.draw()

    def star_count(self) -> int:
        return self.app.state["stars"].get(self.tool.slug, 0)

    def add(self) -> None:
        self.app.state["stars"][self.tool.slug] = min(20, self.star_count() + 1); self.draw()

    def clear(self) -> None:
        self.app.state["stars"][self.tool.slug] = 0; self.draw()

    def draw(self) -> None:
        c = self.canvas; c.delete("all"); count = self.star_count()
        asset = self.app.card_image(self.tool, 0)
        if asset:
            c.create_image(760, 145, image=asset)
        c.create_text(355, 55, text=f"成长星星：{count} / 20", fill=INK, font=(self.app.font, 24, "bold"))
        for i in range(20):
            r, col = divmod(i, 5); x, y = 130 + col * 110, 125 + r * 78; filled = i < count
            c.create_polygon(star(x, y, 34, 15), fill="#ffbe0b" if filled else "#e2e8f0", outline="#f59e0b" if filled else "#cbd5e1", width=2)
        if count >= 20:
            c.create_rectangle(610, 332, 925, 412, fill="white", outline=self.tool.color, width=4)
            c.create_text(768, 372, text="星星墙已点亮", fill=GOOD, font=(self.app.font, 23, "bold"))


def launch_tool(tool: Any | None = None) -> None:
    root = tk.Tk()
    app = App(root)
    if tool is not None:
        root.after(50, lambda: app.open(tool))
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="85 个儿童可视化小工具")
    parser.add_argument("--tool", "-t", help="快速打开工具：支持序号、中文名、slug，例如 18 / 儿童画板 / draw")
    parser.add_argument("--list", action="store_true", help="列出所有工具")
    parser.add_argument("--self-test", action="store_true", help="检查工具注册表")
    args = parser.parse_args(argv)
    if args.self_test:
        validate_registry(); print(f"OK: {len(TOOLS)} tools registered."); return 0
    if args.list:
        for t in TOOLS:
            print(f"{t.no:02d}  {t.title}  [{t.slug}]  {t.purpose}")
        return 0
    launch_tool(args.tool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
