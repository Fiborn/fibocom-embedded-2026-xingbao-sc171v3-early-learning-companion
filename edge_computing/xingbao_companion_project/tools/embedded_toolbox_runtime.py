"""Playable Pygame runtime for the 85-item Xingbao kids toolbox.

The legacy toolbox remains the canonical source for card text, lottery items,
wheel rewards and task names.  This module reuses that data without creating a
Tk window and implements the interaction state directly on the touch desktop.
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
import time
from pathlib import Path
from typing import Any


NAMES = ["小雨", "乐乐", "豆豆", "安安", "米米", "天天", "可可", "朵朵", "舟舟", "贝贝", "然然", "宁宁"]
MOODS = [
    ("开心", (255, 209, 102)), ("平静", (155, 246, 255)),
    ("生气", (255, 107, 107)), ("难过", (160, 196, 255)),
    ("害怕", (205, 180, 219)), ("兴奋", (184, 242, 230)),
]
PLAYER_ITEMS = {
    "noise": ["小雨声", "轻风声", "海浪声"],
    "songs": ["两只老虎", "小星星", "找朋友", "拍手歌"],
    "stories": ["月亮晚安", "小熊找朋友", "云朵上的房子"],
}
STORY_PAGES = [
    ("小星星", "夜晚来了，小星星一颗一颗亮起来。"),
    ("小房子", "小朋友回到温暖的小房子里。"),
    ("说晚安", "月亮轻轻说：晚安，明天见。"),
]
PALETTE = [
    (239, 68, 68), (245, 158, 11), (34, 197, 94),
    (59, 130, 246), (168, 85, 247), (255, 255, 255),
]


class EmbeddedToolboxRuntime:
    """Stateful renderer/controller shared by all embedded toolbox entries."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.states: dict[str, dict[str, Any]] = {}
        self.hitboxes: list[tuple[Any, str, Any]] = []
        self.legacy = self._load_legacy_data()

    def _load_legacy_data(self) -> Any | None:
        path = self.project_root / "web" / "kids_visual_tools" / "kids_visual_tools.py"
        try:
            spec = importlib.util.spec_from_file_location("xingbao_legacy_visual_tools_data", path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        except Exception:
            return None

    def activate(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = str(item.get("slug") or "tool")
        state = self.states.get(slug)
        if state is None:
            state = self._new_state(item)
            self.states[slug] = state
        return state

    def result_summary(self, item: dict[str, Any]) -> str:
        """Return a child-safe summary suitable for the existing memory book."""
        state = self.activate(item)
        kind = str(item.get("kind") or "")
        if kind == "sunmoon":
            return "完成了{}卡片互动".format("起床" if state.get("mode") == "wake" else "睡觉")
        if kind == "water":
            return "今天已经打卡 {} / 8 杯".format(sum(bool(value) for value in state.get("cups", [])))
        if kind.startswith("player:"):
            items = PLAYER_ITEMS.get(kind.split(":", 1)[1], [])
            index = int(state.get("index", 0))
            name = items[index % len(items)] if items else "音频"
            return "听了《{}》".format(name)
        if kind == "breath":
            return "完成了一次呼吸放松练习"
        if kind == "mood":
            index = max(0, min(len(MOODS) - 1, int(state.get("mood", 0))))
            return "记录了今天的心情：{}".format(MOODS[index][0])
        if kind.startswith("cards:"):
            cards = state.get("items") or []
            index = int(state.get("index", 0))
            title = cards[index % len(cards)][0] if cards else "认知卡片"
            return "学习了卡片：{}".format(title)
        if kind == "storybook":
            index = max(0, min(len(STORY_PAGES) - 1, int(state.get("index", 0))))
            return "读到了故事《{}》".format(STORY_PAGES[index][0])
        if kind == "drawing":
            return "完成了一次主题绘画练习"
        if kind == "coloring":
            return "涂色完成了 {} 个区域".format(len(state.get("fills") or {}))
        if kind == "stickers":
            return "在贴纸画里放置了 {} 张贴纸".format(len(state.get("stickers") or []))
        if kind.startswith("game:"):
            game = str(state.get("game") or kind.split(":", 1)[1])
            if game == "puzzle":
                return "拼图{}".format("已经完成" if state.get("pieces") == [1, 2, 3, 4, 5, 6] else "正在挑战中")
            if game == "spot":
                return "找到了 {} / 3 处不同".format(len(state.get("found") or set()))
            if game == "match":
                return "完成配对 {} / 4".format(len(state.get("matches") or set()))
            if game == "memory":
                return "记忆翻牌配对成功 {} / 4".format(len(state.get("matched") or set()) // 2)
            if game == "sort":
                order = state.get("order") or []
                return "排序挑战已选择 {} / 5 个".format(len(order))
            if game == "count":
                return str(state.get("message") or "完成了一次数数挑战")
            if game == "classify":
                return "分类完成 {} / {}".format(len(state.get("done") or set()), len(state.get("items") or []))
            if game == "lottery":
                return "抽到的小任务：{}".format(state.get("current") or "还没有抽签")
            if game == "wheel":
                return "转盘结果：{}".format(state.get("result") or "还没有转动转盘")
        if kind == "attendance":
            attendance = state.get("attendance") or {}
            return "点名记录：{} / {} 人已到".format(sum(bool(value) for value in attendance.values()), len(attendance))
        if kind == "helper":
            return "今天的小助手：{}".format(state.get("result") or "还没有抽取")
        if kind == "groups":
            return "完成了一次随机分组"
        if kind == "stars":
            return "成长星星已经点亮 {} / 20 颗".format(int(state.get("count", 0)))
        return "完成了一次星宝互动"

    def _legacy_tool(self, item: dict[str, Any]) -> Any | None:
        if self.legacy is None:
            return None
        try:
            return self.legacy.resolve_tool(str(item.get("slug") or item.get("no") or ""))
        except Exception:
            return None

    def _new_state(self, item: dict[str, Any]) -> dict[str, Any]:
        kind = str(item.get("kind") or "")
        slug = str(item.get("slug") or "")
        state: dict[str, Any] = {"kind": kind, "slug": slug, "message": ""}
        tool = self._legacy_tool(item)
        if kind == "sunmoon":
            state["mode"] = "wake"
        elif kind == "water":
            state["cups"] = [False] * 8
        elif kind.startswith("player:"):
            state.update(index=0, playing=False, progress=0.0, last_tick=time.monotonic())
        elif kind == "breath":
            state.update(running=True, started=time.monotonic())
        elif kind == "mood":
            state["mood"] = 0
        elif kind.startswith("cards:"):
            fallback = kind.split(":", 1)[1]
            items = self.legacy.get_card_items(tool, fallback) if tool and self.legacy else [("星宝", "一起认识新事物", "#e0f2fe")]
            state.update(index=0, flipped=False, items=list(items))
        elif kind == "storybook":
            state["index"] = 0
        elif kind == "coloring":
            state.update(color=PALETTE[0], fills={})
        elif kind == "stickers":
            names = self.legacy.sticker_names(tool) if tool and self.legacy else ["星星", "爱心", "太阳", "云朵"]
            state.update(sticker_names=list(names), sticker_index=0, stickers=[])
        elif kind.startswith("game:"):
            self._reset_game(state, item)
        elif kind == "attendance":
            state["attendance"] = {name: False for name in NAMES}
        elif kind == "helper":
            state.update(result="", highlight=-1)
        elif kind == "groups":
            state["groups"] = self._new_groups()
        elif kind == "stars":
            tasks = self.legacy.get_star_tasks(tool) if tool and self.legacy else ["完成任务", "帮助家人", "认真阅读"]
            state.update(count=0, tasks=list(tasks))
        return state

    def _reset_game(self, state: dict[str, Any], item: dict[str, Any]) -> None:
        game = str(item.get("kind") or "game:lottery").split(":", 1)[1]
        state.update(game=game, message="")
        tool = self._legacy_tool(item)
        if game == "puzzle":
            pieces = list(range(1, 7)); random.shuffle(pieces)
            state.update(pieces=pieces, selected=None)
        elif game == "spot":
            state["found"] = set()
        elif game == "match":
            right = ["小猫", "小狗", "小鱼", "小鸟"]; random.shuffle(right)
            state.update(left=["小猫", "小狗", "小鱼", "小鸟"], right=right, selected=None, matches=set())
        elif game == "memory":
            cards = ["猫", "狗", "鱼", "车"] * 2; random.shuffle(cards)
            state.update(cards=cards, opened=[], matched=set(), hide_at=0.0)
        elif game == "sort":
            values = [1, 2, 3, 4, 5]; random.shuffle(values)
            state.update(values=values, order=[])
        elif game == "count":
            state["target"] = random.randint(1, 6)
        elif game == "classify":
            state.update(
                items=[("小猫", "动物"), ("苹果", "水果"), ("积木", "玩具"), ("小狗", "动物"), ("香蕉", "水果"), ("皮球", "玩具")],
                selected=None, done=set(),
            )
        elif game == "lottery":
            choices = self.legacy.get_lottery_items(tool) if tool and self.legacy else ["给家人一个抱抱", "讲一个小故事", "喝一杯水"]
            state.update(choices=list(choices), current="点击抽一张")
        elif game == "wheel":
            rewards = self.legacy.get_wheel_rewards(tool) if tool and self.legacy else ["贴纸", "讲故事", "抱抱", "画画", "听儿歌", "亲子游戏"]
            state.update(rewards=list(rewards), result="", spinning_until=0.0, angle=0.0)

    def _new_groups(self) -> dict[str, list[str]]:
        names = NAMES[:]; random.shuffle(names)
        groups = {"红队": [], "蓝队": [], "绿队": []}
        values = list(groups.values())
        for index, name in enumerate(names):
            values[index % 3].append(name)
        return groups

    def _add_hit(self, rect: Any, action: str, payload: Any = None) -> None:
        self.hitboxes.append((rect, action, payload))

    def _button(self, ui: Any, desktop: Any, rect: Any, label: str, *, active: bool = False, color: tuple[int, int, int] | None = None) -> None:
        fill = color or ((255, 219, 123) if active else (255, 252, 242))
        ui.rounded_panel(desktop.screen, rect, fill, border=(199, 133, 62), radius=14, width=3 if active else 2)
        ui.draw_text(desktop.screen, label, rect.center, max(15, int(desktop.screen.get_height() * 0.020)), bold=active)

    def _label(self, ui: Any, desktop: Any, text: str, center: tuple[int, int], size: float, *, color: tuple[int, int, int] = (83, 54, 37), bold: bool = False) -> None:
        ui.draw_text(desktop.screen, str(text), center, max(13, int(desktop.screen.get_height() * size)), color=color, bold=bold)

    def draw(self, ui: Any, desktop: Any, item: dict[str, Any], body: Any) -> None:
        self.hitboxes = []
        state = self.activate(item)
        kind = str(item.get("kind") or "")
        if kind == "sunmoon": self._draw_sunmoon(ui, desktop, state, body)
        elif kind == "water": self._draw_water(ui, desktop, state, body)
        elif kind.startswith("player:"): self._draw_player(ui, desktop, state, body)
        elif kind == "breath": self._draw_breath(ui, desktop, state, body)
        elif kind == "mood": self._draw_mood(ui, desktop, state, body)
        elif kind.startswith("cards:"): self._draw_cards(ui, desktop, state, body)
        elif kind == "storybook": self._draw_story(ui, desktop, state, body)
        elif kind == "drawing": self._draw_drawing(ui, desktop, state, item, body)
        elif kind == "coloring": self._draw_coloring(ui, desktop, state, body)
        elif kind == "stickers": self._draw_stickers(ui, desktop, state, body)
        elif kind.startswith("game:"): self._draw_game(ui, desktop, state, item, body)
        elif kind == "attendance": self._draw_attendance(ui, desktop, state, body)
        elif kind == "helper": self._draw_helper(ui, desktop, state, body)
        elif kind == "groups": self._draw_groups(ui, desktop, state, body)
        elif kind == "stars": self._draw_stars(ui, desktop, state, body)
        else: self._draw_fallback(ui, desktop, state, body)

    def handle_touch(self, ui: Any, desktop: Any, item: dict[str, Any], pos: tuple[int, int]) -> str | None:
        state = self.activate(item)
        for rect, action, payload in reversed(self.hitboxes):
            if rect.collidepoint(pos):
                return self._act(ui, desktop, item, state, action, payload)
        return None

    def _act(self, ui: Any, desktop: Any, item: dict[str, Any], state: dict[str, Any], action: str, payload: Any) -> str | None:
        kind = str(item.get("kind") or "")
        if action == "speak":
            desktop.speak_readable(str(payload), page="tool_activity")
        elif action == "mode": state["mode"] = payload; desktop.speak_readable("早上好，慢慢起床" if payload == "wake" else "晚安，准备睡觉", page="tool_activity")
        elif action == "cup": state["cups"][int(payload)] = not state["cups"][int(payload)]
        elif action == "water_add":
            for i, value in enumerate(state["cups"]):
                if not value: state["cups"][i] = True; break
        elif action == "water_reset": state["cups"] = [False] * 8
        elif action == "player_prev": state["index"] = (state["index"] - 1) % len(PLAYER_ITEMS[kind.split(":", 1)[1]]); state["progress"] = 0.0
        elif action == "player_next": state["index"] = (state["index"] + 1) % len(PLAYER_ITEMS[kind.split(":", 1)[1]]); state["progress"] = 0.0
        elif action == "player_toggle":
            state["playing"] = not state["playing"]; state["last_tick"] = time.monotonic()
            name = PLAYER_ITEMS[kind.split(":", 1)[1]][state["index"]]
            desktop.speak_readable(("播放" if state["playing"] else "暂停") + name, page="tool_activity")
        elif action == "breath_toggle": state["running"] = not state["running"]; state["started"] = time.monotonic()
        elif action == "mood": state["mood"] = int(payload); desktop.speak_readable("今天我感觉" + MOODS[int(payload)][0], page="tool_activity")
        elif action == "card_prev": state["index"] = (state["index"] - 1) % len(state["items"]); state["flipped"] = False
        elif action == "card_next": state["index"] = (state["index"] + 1) % len(state["items"]); state["flipped"] = False
        elif action == "card_flip":
            state["flipped"] = not state["flipped"]
            title, text, _ = state["items"][state["index"]]
            desktop.speak_readable(text if state["flipped"] else title, page="tool_activity")
        elif action == "story_prev": state["index"] = max(0, state["index"] - 1)
        elif action == "story_next": state["index"] = min(len(STORY_PAGES) - 1, state["index"] + 1)
        elif action == "open_drawing": return "drawing"
        elif action == "palette": state["color"] = PALETTE[int(payload)]
        elif action == "fill": state["fills"][str(payload)] = state["color"]
        elif action == "color_reset": state["fills"] = {}
        elif action == "sticker_select": state["sticker_index"] = int(payload)
        elif action == "sticker_place":
            if len(state["stickers"]) < 40:
                state["stickers"].append((int(payload[0]), int(payload[1]), state["sticker_names"][state["sticker_index"]]))
        elif action == "sticker_reset": state["stickers"] = []
        elif action.startswith("game_"):
            return self._act_game(desktop, item, state, action, payload)
        elif action == "attendance":
            name = str(payload); state["attendance"][name] = not state["attendance"][name]
        elif action == "attendance_all": state["attendance"] = {name: True for name in NAMES}
        elif action == "attendance_clear": state["attendance"] = {name: False for name in NAMES}
        elif action == "helper_pick":
            state["highlight"] = random.randrange(len(NAMES)); state["result"] = NAMES[state["highlight"]]
            desktop.speak_readable("今天选中" + state["result"], page="tool_activity")
        elif action == "groups_shuffle": state["groups"] = self._new_groups()
        elif action == "star_add": state["count"] = min(20, int(state["count"]) + 1); desktop.speak_readable("点亮一颗星星", page="tool_activity")
        elif action == "star_clear": state["count"] = 0
        return None

    def _draw_sunmoon(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg = ui.pygame; wake = s["mode"] == "wake"; bg = (255, 247, 214) if wake else (232, 238, 255)
        ui.rounded_panel(d.screen, b, bg, radius=20)
        center = (b.centerx, b.y + int(b.h * 0.43)); radius = int(b.h * 0.20)
        pg.draw.circle(d.screen, (255, 209, 102) if wake else (221, 231, 255), center, radius)
        if not wake: pg.draw.circle(d.screen, bg, (center[0] + int(radius * .42), center[1] - int(radius * .2)), radius)
        self._label(ui, d, "早上好，慢慢起床" if wake else "晚安，准备睡觉", (b.centerx, b.y + int(b.h * .70)), .028, bold=True)
        left = pg.Rect(b.x + int(b.w*.20), b.bottom-int(b.h*.18), int(b.w*.25), int(b.h*.12)); right = pg.Rect(b.x+int(b.w*.55), left.y, left.w, left.h)
        self._button(ui,d,left,"起床卡片",active=wake); self._button(ui,d,right,"睡觉卡片",active=not wake)
        self._add_hit(left,"mode","wake"); self._add_hit(right,"mode","sleep")

    def _draw_water(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; ui.rounded_panel(d.screen,b,(239,250,255),radius=20)
        cups=s["cups"]; self._label(ui,d,"今天打卡：{} / 8 杯".format(sum(cups)),(b.centerx,b.y+int(b.h*.13)),.028,bold=True)
        gap=int(b.w*.018); cw=(b.w-gap*9)//8; y=b.y+int(b.h*.28); ch=int(b.h*.38)
        for i,on in enumerate(cups):
            r=pg.Rect(b.x+gap+(cw+gap)*i,y,cw,ch); pg.draw.rect(d.screen,(255,255,255),r,border_radius=10); pg.draw.rect(d.screen,(76,201,240),r.inflate(-8,-8) if on else pg.Rect(r.x+4,r.bottom-22,r.w-8,16),border_radius=8); pg.draw.rect(d.screen,(92,180,225),r,3,border_radius=10); self._label(ui,d,str(i+1),(r.centerx,r.bottom+18),.015); self._add_hit(r,"cup",i)
        add=pg.Rect(b.x+int(b.w*.30),b.bottom-int(b.h*.16),int(b.w*.18),int(b.h*.10)); reset=pg.Rect(b.x+int(b.w*.52),add.y,add.w,add.h)
        self._button(ui,d,add,"加一杯",active=True); self._button(ui,d,reset,"清空"); self._add_hit(add,"water_add"); self._add_hit(reset,"water_reset")

    def _draw_player(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; subtype=s["kind"].split(":",1)[1]; items=PLAYER_ITEMS[subtype]
        now=time.monotonic()
        if s["playing"]: s["progress"]=(float(s["progress"])+max(0.0,now-float(s["last_tick"])))%60.0
        s["last_tick"]=now; ui.rounded_panel(d.screen,b,(248,251,255),radius=20)
        name=items[s["index"]]; self._label(ui,d,name,(b.centerx,b.y+int(b.h*.16)),.032,bold=True)
        center=(b.centerx,b.y+int(b.h*.43)); pg.draw.circle(d.screen,(255,240,243) if subtype=="songs" else (224,242,254),center,int(b.h*.19)); self._label(ui,d,"♫" if subtype=="songs" else ("≋" if subtype=="noise" else "故事"),center,.055,bold=True)
        bar=pg.Rect(b.x+int(b.w*.20),b.y+int(b.h*.68),int(b.w*.60),int(b.h*.035)); pg.draw.rect(d.screen,(226,232,240),bar,border_radius=bar.h//2); fill=bar.copy(); fill.w=int(bar.w*s["progress"]/60.0); pg.draw.rect(d.screen,(74,173,226),fill,border_radius=bar.h//2)
        labels=[("上一首","player_prev"),("暂停" if s["playing"] else "播放","player_toggle"),("下一首","player_next")]
        for i,(label,act) in enumerate(labels):
            r=pg.Rect(b.x+int(b.w*(.22+i*.20)),b.bottom-int(b.h*.16),int(b.w*.16),int(b.h*.10)); self._button(ui,d,r,label,active=act=="player_toggle"); self._add_hit(r,act)

    def _draw_breath(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; ui.rounded_panel(d.screen,b,(240,255,244),radius=20); elapsed=(time.monotonic()-s["started"])%8 if s["running"] else 0; inhale=elapsed<4; phase=(elapsed if inhale else 8-elapsed)/4; radius=int(b.h*(.12+.13*phase)); center=(b.centerx,b.y+int(b.h*.43)); pg.draw.circle(d.screen,(140,233,154),center,radius); pg.draw.circle(d.screen,(55,178,77),center,radius,4); self._label(ui,d,"吸气" if inhale else "呼气",center,.038,bold=True); self._label(ui,d,"跟着圆球慢慢呼吸",(b.centerx,b.y+int(b.h*.72)),.022)
        r=pg.Rect(b.x+int(b.w*.40),b.bottom-int(b.h*.15),int(b.w*.20),int(b.h*.10)); self._button(ui,d,r,"暂停" if s["running"] else "继续",active=True); self._add_hit(r,"breath_toggle")

    def _draw_mood(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; name,color=MOODS[s["mood"]]; ui.rounded_panel(d.screen,b,(255,253,247),radius=20); center=(b.centerx,b.y+int(b.h*.33)); r=int(b.h*.18); pg.draw.circle(d.screen,color,center,r); pg.draw.circle(d.screen,(45,55,72),(center[0]-r//3,center[1]-r//5),max(5,r//13)); pg.draw.circle(d.screen,(45,55,72),(center[0]+r//3,center[1]-r//5),max(5,r//13)); pg.draw.arc(d.screen,(45,55,72),pg.Rect(center[0]-r//2,center[1],r,r//2),math.radians(10),math.radians(170),5); self._label(ui,d,"今天我感觉："+name,(b.centerx,b.y+int(b.h*.62)),.027,bold=True)
        for i,(label,col) in enumerate(MOODS):
            row,cc=divmod(i,3); rr=pg.Rect(b.x+int(b.w*(.16+cc*.24)),b.y+int(b.h*(.70+row*.13)),int(b.w*.20),int(b.h*.10)); self._button(ui,d,rr,label,active=i==s["mood"],color=col); self._add_hit(rr,"mood",i)

    def _draw_cards(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; title,text,color=s["items"][s["index"]]
        try: fill=tuple(int(str(color).lstrip("#")[i:i+2],16) for i in (0,2,4))
        except Exception: fill=(224,242,254)
        card=pg.Rect(b.x+int(b.w*.22),b.y+int(b.h*.07),int(b.w*.56),int(b.h*.66)); ui.rounded_panel(d.screen,card,fill,border=(129,140,159),radius=24,width=4); shown=text if s["flipped"] else title; self._label(ui,d,shown,(card.centerx,card.centery-10),.042 if not s["flipped"] else .028,bold=True); self._label(ui,d,"{} / {}".format(s["index"]+1,len(s["items"])),(card.centerx,card.bottom-28),.016)
        actions=[("上一张","card_prev"),("翻卡/发音","card_flip"),("下一张","card_next")]
        for i,(label,act) in enumerate(actions):
            r=pg.Rect(b.x+int(b.w*(.20+i*.22)),b.bottom-int(b.h*.16),int(b.w*.18),int(b.h*.10)); self._button(ui,d,r,label,active=act=="card_flip"); self._add_hit(r,act)

    def _draw_story(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; title,text=STORY_PAGES[s["index"]]; page=pg.Rect(b.x+int(b.w*.15),b.y+int(b.h*.06),int(b.w*.70),int(b.h*.70)); ui.rounded_panel(d.screen,page,(255,250,240),border=(215,199,169),radius=18,width=4)
        for x,y in [(page.x+100,page.y+90),(page.centerx,page.y+150),(page.right-110,page.y+90)]: self._star(pg,d.screen,(x,y),22,(255,209,102))
        self._label(ui,d,title,(page.centerx,page.y+int(page.h*.62)),.034,bold=True); self._label(ui,d,text,(page.centerx,page.y+int(page.h*.75)),.022); self._label(ui,d,"{} / {}".format(s["index"]+1,len(STORY_PAGES)),(page.centerx,page.bottom-25),.015)
        for i,(label,act) in enumerate([("上一页","story_prev"),("下一页","story_next")]):
            r=pg.Rect(b.x+int(b.w*(.30+i*.25)),b.bottom-int(b.h*.15),int(b.w*.20),int(b.h*.10)); self._button(ui,d,r,label,active=act=="story_next"); self._add_hit(r,act)

    def _draw_drawing(self, ui: Any, d: Any, s: dict[str, Any], item: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; ui.rounded_panel(d.screen,b,(250,252,255),radius=20); prompt="画一幅属于你的作品"
        tool=self._legacy_tool(item)
        if tool and self.legacy:
            try: prompt=self.legacy.drawing_prompt(tool)
            except Exception: pass
        canvas=pg.Rect(b.x+int(b.w*.14),b.y+int(b.h*.09),int(b.w*.72),int(b.h*.57)); pg.draw.rect(d.screen,(255,255,255),canvas,border_radius=14); pg.draw.rect(d.screen,(219,177,123),canvas,3,border_radius=14); self._label(ui,d,prompt,(canvas.centerx,canvas.centery),.029,color=(125,91,62),bold=True)
        r=pg.Rect(b.x+int(b.w*.38),b.bottom-int(b.h*.17),int(b.w*.24),int(b.h*.11)); self._button(ui,d,r,"进入星宝画板",active=True); self._add_hit(r,"open_drawing")

    def _draw_coloring(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; ui.rounded_panel(d.screen,b,(248,251,255),radius=20); top=b.y+8
        for i,col in enumerate(PALETTE):
            r=pg.Rect(b.x+int(b.w*(.15+i*.12)),top,int(b.w*.08),int(b.h*.09)); pg.draw.rect(d.screen,col,r,border_radius=10); pg.draw.rect(d.screen,(36,40,52) if col==s["color"] else (180,185,195),r,4 if col==s["color"] else 2,border_radius=10); self._add_hit(r,"palette",i)
        reset=pg.Rect(b.right-int(b.w*.15),top,int(b.w*.10),int(b.h*.09)); self._button(ui,d,reset,"重画"); self._add_hit(reset,"color_reset")
        area=pg.Rect(b.x+int(b.w*.08),b.y+int(b.h*.17),int(b.w*.84),int(b.h*.76)); pg.draw.rect(d.screen,(224,242,254),area,border_radius=12)
        regions={
            "sun":pg.Rect(area.x+30,area.y+25,90,90), "house":pg.Rect(area.x+260,area.y+210,270,160),
            "door":pg.Rect(area.x+360,area.y+280,55,90), "tree":pg.Rect(area.x+610,area.y+220,50,150),
            "leaf":pg.Rect(area.x+560,area.y+80,155,170), "grass":pg.Rect(area.x,area.bottom-70,area.w,70),
        }
        roof=[(area.x+225,area.y+210),(area.x+395,area.y+100),(area.x+565,area.y+210)]
        pg.draw.polygon(d.screen,s["fills"].get("roof",(255,255,255)),roof); pg.draw.polygon(d.screen,(45,55,72),roof,4); self._add_hit(pg.Rect(area.x+225,area.y+95,340,120),"fill","roof")
        for name,r in regions.items():
            color=s["fills"].get(name,(255,255,255));
            if name in {"sun","leaf"}: pg.draw.ellipse(d.screen,color,r); pg.draw.ellipse(d.screen,(45,55,72),r,3)
            else: pg.draw.rect(d.screen,color,r); pg.draw.rect(d.screen,(45,55,72),r,3)
            self._add_hit(r,"fill",name)

    def _draw_stickers(self, ui: Any, d: Any, s: dict[str, Any], b: Any) -> None:
        pg=ui.pygame; ui.rounded_panel(d.screen,b,(205,239,253),radius=20); names=s["sticker_names"][:6]
        for i,name in enumerate(names):
            r=pg.Rect(b.x+int(b.w*(.08+i*.13)),b.y+8,int(b.w*.11),int(b.h*.09)); self._button(ui,d,r,name,active=i==s["sticker_index"]); self._add_hit(r,"sticker_select",i)
        reset=pg.Rect(b.right-int(b.w*.13),b.y+8,int(b.w*.10),int(b.h*.09)); self._button(ui,d,reset,"清空"); self._add_hit(reset,"sticker_reset")
        area=pg.Rect(b.x+20,b.y+int(b.h*.15),b.w-40,int(b.h*.80)); pg.draw.rect(d.screen,(205,239,253),area,border_radius=12); pg.draw.rect(d.screen,(183,228,199),pg.Rect(area.x,area.bottom-int(area.h*.27),area.w,int(area.h*.27)))
        for x,y,name in s["stickers"]: self._draw_sticker(ui,d,(x,y),name)
        self._add_hit(area,"sticker_place",None)
        # The exact touch point is substituted in handle_touch below.

    def handle_touch(self, ui: Any, desktop: Any, item: dict[str, Any], pos: tuple[int, int]) -> str | None:  # type: ignore[override]
        state=self.activate(item)
        for rect,action,payload in reversed(self.hitboxes):
            if rect.collidepoint(pos):
                if action=="sticker_place": payload=pos
                return self._act(ui,desktop,item,state,action,payload)
        return None

    def _draw_sticker(self, ui: Any, d: Any, pos: tuple[int,int], name: str) -> None:
        pg=ui.pygame; x,y=pos
        if name=="星星": self._star(pg,d.screen,(x,y),28,(255,209,102))
        elif name=="爱心": pg.draw.circle(d.screen,(251,113,133),(x-15,y),22); pg.draw.circle(d.screen,(251,113,133),(x+15,y),22); pg.draw.polygon(d.screen,(251,113,133),[(x-35,y),(x+35,y),(x,y+42)])
        elif name in {"太阳","苹果","气球"}: pg.draw.circle(d.screen,(255,209,102) if name=="太阳" else (239,68,68), (x,y),30)
        elif name in {"云朵","雨滴"}: pg.draw.circle(d.screen,(255,255,255) if name=="云朵" else (96,165,250),(x,y),30)
        else: pg.draw.circle(d.screen,(255,175,204),(x,y),30); self._label(ui,d,name,(x,y),.014,bold=True)

    def _draw_game(self, ui: Any, d: Any, s: dict[str, Any], item: dict[str, Any], b: Any) -> None:
        game=s["game"]
        if game=="puzzle": self._draw_game_puzzle(ui,d,s,b)
        elif game=="spot": self._draw_game_spot(ui,d,s,b)
        elif game=="match": self._draw_game_match(ui,d,s,b)
        elif game=="memory": self._draw_game_memory(ui,d,s,b)
        elif game=="sort": self._draw_game_sort(ui,d,s,b)
        elif game=="count": self._draw_game_count(ui,d,s,b)
        elif game=="classify": self._draw_game_classify(ui,d,s,b)
        elif game=="lottery": self._draw_game_lottery(ui,d,s,b)
        elif game=="wheel": self._draw_game_wheel(ui,d,s,b)
        pg=ui.pygame; restart=pg.Rect(b.right-int(b.w*.16),b.bottom-int(b.h*.10),int(b.w*.13),int(b.h*.075)); self._button(ui,d,restart,"重新开始"); self._add_hit(restart,"game_restart")

    def _act_game(self, desktop: Any, item: dict[str, Any], s: dict[str, Any], action: str, payload: Any) -> str | None:
        """Apply a mini-game touch and return only a semantic outcome event.

        The caller forwards this event to the central controller.  No UI path
        receives or constructs an arm command, servo value, or timing value.
        """
        game=s["game"]
        if action=="game_restart":
            self._reset_game(s,item)
            return "game_started"
        if game=="puzzle" and action=="game_puzzle":
            i=int(payload)
            if s["selected"] is None:
                s["selected"]=i
            else:
                a=s["selected"]
                s["pieces"][a],s["pieces"][i]=s["pieces"][i],s["pieces"][a]
                s["selected"]=None
                if s["pieces"] == [1,2,3,4,5,6]:
                    return "game_completed"
        elif game=="spot" and action=="game_spot":
            before=len(s["found"])
            s["found"].add(int(payload))
            if len(s["found"]) == before:
                return None
            return "game_completed" if len(s["found"]) == 3 else "game_answer_correct"
        elif game=="match":
            side,index=payload
            if side=="left":
                s["selected"]=s["left"][index]
            elif s["selected"]:
                if s["right"][index] == s["selected"]:
                    s["matches"].add(s["selected"])
                    s["selected"]=None
                    return "game_completed" if len(s["matches"]) == 4 else "game_answer_correct"
                s["selected"]=None
                return "game_retry"
        elif game=="memory" and action=="game_memory":
            i=int(payload)
            if i in s["matched"] or i in s["opened"] or len(s["opened"])>=2:
                return None
            s["opened"].append(i)
            if len(s["opened"])==2:
                a,c=s["opened"]
                if s["cards"][a]==s["cards"][c]:
                    s["matched"].update(s["opened"])
                    s["opened"]=[]
                    return "game_completed" if len(s["matched"]) == 8 else "game_answer_correct"
                s["hide_at"]=time.monotonic()+0.8
                return "game_retry"
        elif game=="sort" and action=="game_sort":
            v=int(payload)
            if v not in s["order"]:
                s["order"].append(v)
                if len(s["order"]) == 5:
                    return "game_completed" if s["order"] == sorted(s["order"]) else "game_retry"
        elif game=="count" and action=="game_count":
            ok=int(payload)==s["target"]
            s["message"]="答对了" if ok else "再数一数"
            desktop.speak_readable(s["message"],page="tool_activity")
            return "game_answer_correct" if ok else "game_retry"
        elif game=="classify":
            if action=="game_item": s["selected"]=int(payload)
            elif action=="game_basket" and s["selected"] is not None:
                if s["items"][s["selected"]][1]==payload:
                    s["done"].add(s["selected"])
                    s["selected"]=None
                    return "game_completed" if len(s["done"]) == len(s["items"]) else "game_answer_correct"
                s["message"]="再想一想"
                return "game_retry"
        elif game=="lottery" and action=="game_draw":
            s["current"]=random.choice(s["choices"])
            desktop.speak_readable(s["current"],page="tool_activity")
            return "reward_received"
        elif game=="wheel" and action=="game_spin" and time.monotonic()>=s["spinning_until"]:
            s["spinning_until"]=time.monotonic()+1.8
            s["result"]=random.choice(s["rewards"])
            return "reward_received"
        return None

    def _draw_game_puzzle(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; colors=[(255,173,173),(255,214,165),(253,255,182),(202,255,191),(155,246,255),(189,178,255)]; size=min(int(b.w*.18),int(b.h*.31)); ox=b.centerx-size*3//2; oy=b.y+25
        for i,v in enumerate(s["pieces"]): r=pg.Rect(ox+(i%3)*size,oy+(i//3)*size,size-6,size-6); pg.draw.rect(d.screen,colors[v-1],r,border_radius=12); pg.draw.rect(d.screen,(239,71,111) if s["selected"]==i else (255,255,255),r,5,border_radius=12); self._label(ui,d,str(v),r.center,.042,bold=True); self._add_hit(r,"game_puzzle",i)
        self._label(ui,d,"完成！" if s["pieces"]==[1,2,3,4,5,6] else "点击两块交换位置",(b.centerx,b.bottom-28),.023,bold=True)

    def _draw_game_spot(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; scenes=[]
        for side in range(2):
            r=pg.Rect(b.x+25+side*(b.w//2),b.y+25,b.w//2-40,b.h-95); pg.draw.rect(d.screen,(224,242,254),r,border_radius=12); house=pg.Rect(r.centerx-70,r.centery-20,140,110); pg.draw.rect(d.screen,(255,247,237),house); pg.draw.polygon(d.screen,(239,71,111),[(house.x-20,house.y),(house.centerx,house.y-70),(house.right+20,house.y)]); pg.draw.circle(d.screen,(249,115,22) if side else (255,209,102),(r.x+90,r.y+70),32); scenes.append(r)
        points=[(.20,.18),(.46,.55),(.18,.60)]
        for i,(rx,ry) in enumerate(points):
            for scene in scenes:
                c=(scene.x+int(scene.w*rx),scene.y+int(scene.h*ry)); hit=pg.Rect(c[0]-32,c[1]-32,64,64); self._add_hit(hit,"game_spot",i); 
                if i in s["found"]: pg.draw.circle(d.screen,(66,184,131),c,32,5)
        self._label(ui,d,"找到 {} / 3 处不同".format(len(s["found"])),(b.centerx,b.bottom-28),.022,bold=True)

    def _draw_game_match(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame
        for side,items,x in [("left",s["left"],b.x+int(b.w*.12)),("right",s["right"],b.x+int(b.w*.68))]:
            for i,name in enumerate(items):
                r=pg.Rect(x,b.y+25+i*int(b.h*.17),int(b.w*.20),int(b.h*.12)); done=name in s["matches"]; self._button(ui,d,r,name+("影子" if side=="right" else ""),active=done or (side=="left" and s["selected"]==name)); self._add_hit(r,"game_match",(side,i))
        self._label(ui,d,"已配对 {} / 4".format(len(s["matches"])),(b.centerx,b.bottom-28),.022,bold=True)

    def _draw_game_memory(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame
        if s["hide_at"] and time.monotonic()>=s["hide_at"]: s["opened"]=[]; s["hide_at"]=0.0
        cw=int(b.w*.16); ch=int(b.h*.34); gap=int(b.w*.025); ox=b.centerx-(cw*4+gap*3)//2; oy=b.y+18
        for i,v in enumerate(s["cards"]):
            r=pg.Rect(ox+(i%4)*(cw+gap),oy+(i//4)*(ch+12),cw,ch); face=i in s["opened"] or i in s["matched"]; self._button(ui,d,r,v if face else "?",active=i in s["matched"],color=(255,247,237) if face else (144,205,244)); self._add_hit(r,"game_memory",i)
        self._label(ui,d,"配对成功 {} / 4".format(len(s["matched"])//2),(b.centerx,b.bottom-26),.021,bold=True)

    def _draw_game_sort(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; self._label(ui,d,"从小到大点选圆球",(b.centerx,b.y+25),.023,bold=True)
        for i,v in enumerate(s["values"]):
            r=pg.Rect(b.x+int(b.w*(.12+i*.16)),b.y+80,int(b.w*.12),int(b.h*.24)); pg.draw.circle(d.screen,(226,232,240) if v in s["order"] else (189,224,254),r.center,int(min(r.w,r.h)*(.24+.06*v))); self._add_hit(r,"game_sort",v)
        self._label(ui,d,"选择顺序："+"  ".join(map(str,s["order"])),(b.centerx,b.y+int(b.h*.66)),.030,bold=True)
        if len(s["order"])==5: self._label(ui,d,"排序正确" if s["order"]==sorted(s["order"]) else "顺序不对，点重新开始",(b.centerx,b.bottom-28),.022,color=(66,184,131) if s["order"]==sorted(s["order"]) else (239,71,111),bold=True)

    def _draw_game_count(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; self._label(ui,d,"这里有几只小动物？",(b.centerx,b.y+24),.024,bold=True); target=s["target"]
        for i in range(target): pg.draw.ellipse(d.screen,(255,232,181),pg.Rect(b.centerx-(target*65)//2+i*65,b.y+80,54,68));
        for i in range(1,7): r=pg.Rect(b.x+int(b.w*(.14+(i-1)*.12)),b.y+int(b.h*.60),int(b.w*.09),int(b.h*.13)); self._button(ui,d,r,str(i),active=False); self._add_hit(r,"game_count",i)
        self._label(ui,d,s.get("message",""),(b.centerx,b.bottom-28),.023,bold=True)

    def _draw_game_classify(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; self._label(ui,d,"先点物品，再点对应篮子",(b.centerx,b.y+20),.022,bold=True)
        for i,(name,_cat) in enumerate(s["items"]):
            if i in s["done"]: continue
            r=pg.Rect(b.x+int(b.w*(.08+i*.145)),b.y+55,int(b.w*.12),int(b.h*.18)); self._button(ui,d,r,name,active=s["selected"]==i); self._add_hit(r,"game_item",i)
        for i,cat in enumerate(["动物","水果","玩具"]): r=pg.Rect(b.x+int(b.w*(.16+i*.25)),b.y+int(b.h*.55),int(b.w*.20),int(b.h*.24)); self._button(ui,d,r,cat,active=False,color=[(220,252,231),(255,247,237),(219,234,254)][i]); self._add_hit(r,"game_basket",cat)
        self._label(ui,d,"已分类 {} / {}".format(len(s["done"]),len(s["items"])),(b.centerx,b.bottom-24),.020,bold=True)

    def _draw_game_lottery(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; card=pg.Rect(b.x+int(b.w*.20),b.y+int(b.h*.18),int(b.w*.60),int(b.h*.45)); self._button(ui,d,card,s["current"],active=True); self._add_hit(card,"game_draw"); self._label(ui,d,"点击卡片再抽一次",(b.centerx,b.y+int(b.h*.72)),.021)

    def _draw_game_wheel(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; now=time.monotonic(); spinning=now<s["spinning_until"]
        if spinning: s["angle"]=(s["angle"]+9)%360
        cx,cy=b.centerx,b.y+int(b.h*.42); r=int(min(b.w,b.h)*.28); cols=[(255,173,173),(255,214,165),(253,255,182),(202,255,191),(155,246,255),(189,178,255)]
        for i,reward in enumerate(s["rewards"][:6]):
            start=s["angle"]+i*60; points=[(cx,cy)]+[(cx+math.cos(math.radians(start+a))*r,cy-math.sin(math.radians(start+a))*r) for a in range(0,61,10)]; pg.draw.polygon(d.screen,cols[i],points); mid=math.radians(start+30); self._label(ui,d,reward,(int(cx+math.cos(mid)*r*.62),int(cy-math.sin(mid)*r*.62)),.014,bold=True)
        pg.draw.polygon(d.screen,(239,71,111),[(cx,cy-r-15),(cx-16,cy-r+18),(cx+16,cy-r+18)]); hit=pg.Rect(cx-r,cy-r,r*2,r*2); self._add_hit(hit,"game_spin")
        text="转盘旋转中……" if spinning else ("今天抽到："+s["result"] if s["result"] else "点击转盘开始"); self._label(ui,d,text,(b.centerx,b.bottom-28),.022,bold=True)

    def _draw_attendance(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; att=s["attendance"]
        for i,name in enumerate(NAMES): row,col=divmod(i,4); r=pg.Rect(b.x+int(b.w*(.08+col*.22)),b.y+15+row*int(b.h*.24),int(b.w*.18),int(b.h*.18)); self._button(ui,d,r,name+"\n"+("已到" if att[name] else "未到"),active=att[name]); self._add_hit(r,"attendance",name)
        a=pg.Rect(b.x+int(b.w*.28),b.bottom-int(b.h*.09),int(b.w*.18),int(b.h*.07)); c=pg.Rect(b.x+int(b.w*.54),a.y,a.w,a.h); self._button(ui,d,a,"全部到齐",active=True); self._button(ui,d,c,"全部清空"); self._add_hit(a,"attendance_all"); self._add_hit(c,"attendance_clear")

    def _draw_helper(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame
        for i,name in enumerate(NAMES): row,col=divmod(i,4); center=(b.x+int(b.w*(.18+col*.21)),b.y+int(b.h*(.18+row*.24))); pg.draw.circle(d.screen,(253,230,138) if i==s["highlight"] else (248,250,252),center,int(b.h*.075)); pg.draw.circle(d.screen,(240,160,70),center,int(b.h*.075),4 if i==s["highlight"] else 2); self._label(ui,d,name,center,.017,bold=True)
        if s["result"]: self._label(ui,d,"今天选中："+s["result"],(b.centerx,b.bottom-int(b.h*.18)),.029,color=(66,184,131),bold=True)
        r=pg.Rect(b.x+int(b.w*.39),b.bottom-int(b.h*.11),int(b.w*.22),int(b.h*.085)); self._button(ui,d,r,"开始抽取",active=True); self._add_hit(r,"helper_pick")

    def _draw_groups(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; cols=[(254,202,202),(191,219,254),(187,247,208)]
        for i,(name,names) in enumerate(s["groups"].items()): r=pg.Rect(b.x+int(b.w*(.08+i*.31)),b.y+35,int(b.w*.27),int(b.h*.70)); ui.rounded_panel(d.screen,r,cols[i],radius=18); self._label(ui,d,name,(r.centerx,r.y+30),.025,bold=True); [self._label(ui,d,n,(r.centerx,r.y+75+j*36),.018,bold=True) for j,n in enumerate(names)]
        r=pg.Rect(b.x+int(b.w*.40),b.bottom-int(b.h*.12),int(b.w*.20),int(b.h*.09)); self._button(ui,d,r,"重新分组",active=True); self._add_hit(r,"groups_shuffle")

    def _draw_stars(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        pg=ui.pygame; self._label(ui,d,"成长星星：{} / 20".format(s["count"]),(b.centerx,b.y+22),.026,bold=True)
        for i in range(20): row,col=divmod(i,5); center=(b.x+int(b.w*(.20+col*.15)),b.y+80+row*int(b.h*.13)); self._star(pg,d.screen,center,20,(255,190,11) if i<s["count"] else (226,232,240))
        tasks=s["tasks"][:5]
        for i,task in enumerate(tasks): r=pg.Rect(b.x+int(b.w*(.05+i*.185)),b.bottom-int(b.h*.17),int(b.w*.16),int(b.h*.10)); self._button(ui,d,r,task,active=False); self._add_hit(r,"star_add")
        clear=pg.Rect(b.right-int(b.w*.10),b.y+5,int(b.w*.08),int(b.h*.075)); self._button(ui,d,clear,"清空"); self._add_hit(clear,"star_clear")

    def _draw_fallback(self,ui:Any,d:Any,s:dict[str,Any],b:Any)->None:
        self._label(ui,d,"这个工具正在准备中",b.center,.030,bold=True)

    def _star(self, pg: Any, surface: Any, center: tuple[int,int], radius: int, color: tuple[int,int,int]) -> None:
        points=[]
        for i in range(10):
            angle=-math.pi/2+i*math.pi/5; rr=radius if i%2==0 else radius*.43; points.append((int(center[0]+math.cos(angle)*rr),int(center[1]+math.sin(angle)*rr)))
        pg.draw.polygon(surface,color,points)
