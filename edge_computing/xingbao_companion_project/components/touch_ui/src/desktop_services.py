"""桌面层的本地数据与板卡状态适配。

只使用标准库，SC171V3与电脑端都可运行。读取失败时返回安全的演示值，
不会影响主界面和游戏中心。
"""

import json
import socket
from datetime import datetime
from pathlib import Path


class DesktopStore:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "saves" / "desktop_settings.json"
        self.data = {
            "volume": 70,
            "favorite_memory": False,
            "active_companion": False,
            "eye_rest_minutes": 20,
            "points": 0,
            "focus_completed": 0,
            "drawings_completed": 0,
            "eye_rest_completed": 0,
            "last_seen_game_stars": None,
            "game_star_remainder": 0,
            "reward_history": [],
            "activity_history": [],
            "artworks": [],
        }
        self.load()

    def load(self):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.data.update(saved)
        except (OSError, ValueError, TypeError):
            pass
        self.data["volume"] = max(0, min(100, int(self.data.get("volume", 70))))
        self.data["favorite_memory"] = bool(self.data.get("favorite_memory", False))
        self.data["active_companion"] = bool(self.data.get("active_companion", False))
        for key in ("points", "focus_completed", "drawings_completed", "eye_rest_completed", "game_star_remainder"):
            self.data[key] = max(0, int(self.data.get(key, 0) or 0))
        history = self.data.get("reward_history", [])
        self.data["reward_history"] = history[-30:] if isinstance(history, list) else []
        activities = self.data.get("activity_history", [])
        self.data["activity_history"] = activities[-50:] if isinstance(activities, list) else []
        artworks = self.data.get("artworks", [])
        self.data["artworks"] = artworks[-50:] if isinstance(artworks, list) else []
        return self.data

    def save(self, **updates):
        self.data.update(updates)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def award_points(self, reason, amount):
        amount = max(0, int(amount))
        if amount <= 0:
            return 0
        self.data["points"] = int(self.data.get("points", 0)) + amount
        history = list(self.data.get("reward_history", []))
        history.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "reason": str(reason),
            "amount": amount,
        })
        self.save(points=self.data["points"], reward_history=history[-30:])
        return amount

    def sync_game_stars(self, current_stars, stars_per_reward=5, points_per_reward=25):
        current_stars = max(0, int(current_stars or 0))
        previous = self.data.get("last_seen_game_stars")
        if previous is None:
            self.save(last_seen_game_stars=current_stars)
            return 0
        previous = max(0, int(previous or 0))
        if current_stars < previous:
            self.save(last_seen_game_stars=current_stars, game_star_remainder=0)
            return 0
        delta = max(0, current_stars - previous)
        accumulated = int(self.data.get("game_star_remainder", 0)) + delta
        groups, remainder = divmod(accumulated, stars_per_reward)
        self.save(last_seen_game_stars=current_stars, game_star_remainder=remainder)
        return self.award_points("每5颗游戏星兑换×{}".format(groups), groups * points_per_reward) if groups else 0

    def reward_level(self):
        points = int(self.data.get("points", 0))
        level = points // 200 + 1
        progress = points % 200
        return {"level": level, "progress": progress, "next": 200}

    def record_activity(self, kind, title, detail=""):
        history = list(self.data.get("activity_history", []))
        history.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "kind": str(kind),
            "title": str(title),
            "detail": str(detail),
        })
        self.save(activity_history=history[-50:])

    def record_artwork(self, relative_path, title="星宝画作"):
        artworks = list(self.data.get("artworks", []))
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "path": str(relative_path).replace("\\", "/"),
            "title": str(title),
        }
        artworks.append(entry)
        self.save(artworks=artworks[-50:])
        self.record_activity("artwork", "完成一幅画", entry["path"])
        return entry

    def game_summary(self):
        path = self.root / "saves" / "latest_save.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        today = payload.get("today", {}) if isinstance(payload, dict) else {}
        totals = payload.get("totals", {}) if isinstance(payload, dict) else {}
        records = payload.get("records", {}) if isinstance(payload, dict) else {}
        growth = payload.get("growth", {}) if isinstance(payload, dict) else {}
        daily_history = payload.get("daily_history", {}) if isinstance(payload, dict) else {}
        game_counts = records.get("game_counts", {}) if isinstance(records, dict) else {}
        favorite_game = str(records.get("favorite_game", "") or "")
        game_names = {
            "color": "找颜色",
            "shape": "认形状",
            "memory": "记忆游戏",
            "counting": "数一数",
            "english": "英语游戏",
            "skill": "专注反应",
            "habit": "好习惯",
        }
        if not favorite_game and isinstance(game_counts, dict) and game_counts:
            favorite_game = max(game_counts, key=lambda key: int(game_counts.get(key, 0) or 0))
        total_seconds = sum(
            max(0, int(item.get("duration_seconds", 0) or 0))
            for item in daily_history.values()
            if isinstance(item, dict)
        ) if isinstance(daily_history, dict) else 0
        return {
            "today_games": int(today.get("games_played", 0) or 0),
            "today_seconds": int(today.get("duration_seconds", 0) or 0),
            "total_games": int(totals.get("games_played", 0) or 0),
            "last_game": str(records.get("last_game", "暂无") or "暂无"),
            "level": int(growth.get("level", 1) or 1),
            "stars": int(growth.get("stars", 0) or 0),
            "total_success": int(totals.get("total_success", 0) or 0),
            "total_attempts": int(totals.get("total_attempts", 0) or 0),
            "total_seconds": total_seconds,
            "favorite_game": favorite_game,
            "favorite_game_name": game_names.get(favorite_game, favorite_game),
        }


def network_status():
    """判断是否存在可用网络地址，不主动访问互联网。"""
    try:
        host = socket.gethostname()
        addresses = socket.gethostbyname_ex(host)[2]
        online = any(address and not address.startswith("127.") for address in addresses)
        return {"online": online, "detail": addresses[0] if online else "离线可用"}
    except OSError:
        return {"online": False, "detail": "离线可用"}


def battery_status():
    """读取Linux电池节点；开发板无电池节点时报告外接电源。"""
    base = Path("/sys/class/power_supply")
    if base.exists():
        for item in base.iterdir():
            capacity = item / "capacity"
            if not capacity.exists():
                continue
            try:
                percent = max(0, min(100, int(capacity.read_text().strip())))
                status_path = item / "status"
                status = status_path.read_text().strip() if status_path.exists() else "正常"
                return {"percent": percent, "detail": status}
            except (OSError, ValueError):
                continue
    return {"percent": 100, "detail": "外接电源"}
