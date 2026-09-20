"""星宝 V5 轻量养成系统 — local growth and daily tracking.

Local only — no cloud sync, no long-term profiling, no psychological analysis.
"""

from datetime import date, timedelta
import random

from . import theme
from .difficulty import MODULE_IDS, age_level_for_xingbao_level, default_module_progress


MAX_LEVEL = 100
MAX_SKILL_LEVEL = 20
SKILL_UNLOCK_LEVEL = 5
SKILL_MAX_LEVELS = {
    "experience_boost": 20,
    "focus_shield": 999,
    "magic_potion": 999,
}
CONSUMABLE_STAR_COST = 5
DIFFICULTY_STAR_REWARDS = {1: 3, 2: 4, 3: 5}

LEVEL_TITLES = [
    "星尘新芽",
    "星尘学徒",
    "微光伙伴",
    "微光守望者",
    "星点采集员",
    "星点导航员",
    "星轨见习生",
    "星轨探索者",
    "星核守护者",
    "星核领航员",
    "月辉观察员",
    "月辉巡航者",
    "晨星引导者",
    "晨星守护官",
    "星云记录员",
    "星云解码师",
    "星河小队长",
    "星河指挥官",
    "极光探路者",
    "极光统筹官",
    "量子协作者",
    "量子领航员",
    "银河调度员",
    "银河战略官",
    "深空守望者",
    "深空开拓者",
    "星门工程师",
    "星门指挥官",
    "超新星伙伴",
    "超新星领航者",
    "光年探索官",
    "光年守护官",
    "星际智囊",
    "星际统帅",
    "天穹巡礼者",
    "天穹执星官",
    "宇宙航标师",
    "宇宙护航官",
    "星域统御者",
    "星域大领航",
    "银河先锋",
    "银河主控官",
    "星海贤者",
    "星海总指挥",
    "苍穹领主",
    "苍穹守望王",
    "宇宙传奇",
    "宇宙总领航",
    "星宝神话",
    "满级星穹王",
]


def clamp_level(level):
    try:
        value = int(level)
    except (TypeError, ValueError):
        value = theme.START_LEVEL
    return max(theme.START_LEVEL, min(MAX_LEVEL, value))


def level_title(level):
    level = clamp_level(level)
    if level >= MAX_LEVEL:
        return LEVEL_TITLES[-1]
    index = min(len(LEVEL_TITLES) - 2, (level - 1) // 2)
    return LEVEL_TITLES[index]


def energy_required_for_level(level):
    level = clamp_level(level)
    base = theme.ENERGY_MAX
    growth = (level - 1) * 12
    milestone = ((level - 1) // 10) * 40 + ((level - 1) // 25) * 100
    return base + growth + milestone


class SessionRecords:
    """Tracks game results + 星宝 growth within a single session."""

    def __init__(self):
        self.summaries = []
        # Growth state
        self.level = theme.START_LEVEL
        self.energy = 0
        self.energy_max = energy_required_for_level(self.level)
        self.level_title = level_title(self.level)
        self.star_count = 0
        self.games_played = 0
        self.total_success = 0
        self.total_attempts = 0
        self.total_points = 0
        self.favorite_game = None
        self.last_game = "暂无"
        self._game_counts = {}
        self._just_leveled_up = False
        self.today_date = date.today().isoformat()
        self.today_games = 0
        self.today_success = 0
        self.today_attempts = 0
        self.today_stars = 0
        self.today_points = 0
        self.today_duration_seconds = 0
        self.daily_history = {}
        self.unlocked_modules = list(MODULE_IDS)
        self.module_progress = default_module_progress()
        self.experience_boost_level = 0
        self.focus_shield_level = 0
        self.magic_potion_count = 0
        self.last_experience_gained = 0

    def add_summary(self, summary):
        """Record a completed game summary and update growth."""
        summary = dict(summary)
        if not summary.get("star_reward_calculated"):
            summary.update(self.calculate_star_reward(summary))
        self.summaries.append(summary)

        # Count per game
        gid = summary.get("game_id", "unknown")
        self.last_game = summary.get("game_name", gid)
        self._game_counts[gid] = self._game_counts.get(gid, 0) + 1
        # Find favorite
        best = max(self._game_counts, key=self._game_counts.get)
        self.favorite_game = best

        # Track overall
        self.games_played += 1
        success = summary.get("success_count", 0)
        attempts = summary.get("attempt_count", 0)
        stars = summary.get("stars", 0)
        points = summary.get("score_points", round(success * 10))
        self.total_success += success
        self.total_attempts += attempts
        self.star_count += stars
        self.total_points += points
        self.today_games += 1
        self.today_success += success
        self.today_attempts += attempts
        self.today_stars += stars
        self.today_points += points
        duration_seconds = max(0, int(round(float(summary.get("duration_seconds", 0)))))
        self.today_duration_seconds += duration_seconds
        activity_date = str(summary.get("activity_date") or self.today_date)
        day_entry = self.daily_history.setdefault(activity_date, {
            "games": 0, "duration_seconds": 0, "success": 0, "attempts": 0,
        })
        day_entry["games"] += 1
        day_entry["duration_seconds"] += duration_seconds
        day_entry["success"] += success
        day_entry["attempts"] += attempts

        progress = self.module_progress.setdefault(
            gid, {"level": 1, "success": 0, "attempts": 0})
        progress["success"] += success
        progress["attempts"] += attempts
        progress["level"] = max(progress["level"], age_level_for_xingbao_level(self.level))

        # Experience is controlled by difficulty, final score and the potion.
        difficulty_multiplier = float(summary.get("score_multiplier", 1.0))
        base_energy = (success * theme.ENERGY_PER_CORRECT + theme.ENERGY_PER_ROUND) * difficulty_multiplier
        performance_score = max(0, min(100, int(summary.get("performance_score", 100))))
        potion_multiplier = 2.0 if summary.get("magic_potion_active") else 1.0
        experience_factor = performance_score / 100.0 * potion_multiplier
        self.last_experience_gained = max(
            0, round(base_energy * experience_factor))
        self.energy += self.last_experience_gained

        # Level up
        self._just_leveled_up = False
        while self.level < MAX_LEVEL and self.energy >= self.energy_max:
            self.energy -= self.energy_max
            self.level += 1
            self._just_leveled_up = True
            self._refresh_growth_metadata()
        progress["level"] = max(progress["level"], age_level_for_xingbao_level(self.level))
        if self.level >= MAX_LEVEL and self.energy > self.energy_max:
            self.energy = self.energy_max

    @property
    def just_leveled_up(self):
        return self._just_leveled_up

    @property
    def experience_bonus_percent(self):
        # Compatibility alias for older save/readout code.
        return self.bonus_star_chance_percent

    @property
    def experience_multiplier(self):
        return 1.0

    @property
    def bonus_star_chance_percent(self):
        return min(100, self.experience_boost_level * 5)

    @property
    def surprise_star_chance_percent(self):
        return min(20, self.experience_boost_level)

    def calculate_star_reward(self, summary, rng=None):
        """Return the cumulative-currency reward for one completed game."""
        rng = rng or random
        difficulty = max(1, min(3, int(summary.get("difficulty", 3))))
        base_stars = DIFFICULTY_STAR_REWARDS[difficulty]
        wrong_count = max(0, int(summary.get(
            "wrong_count", summary.get("error_count", 0))))
        wrong_penalty = 1 if wrong_count else 0
        bonus_star = 0
        surprise_stars = 0
        if rng.random() < self.bonus_star_chance_percent / 100.0:
            bonus_star = 1
            if rng.random() < self.surprise_star_chance_percent / 100.0:
                surprise_stars = 5
        stars = max(0, base_stars - wrong_penalty + bonus_star + surprise_stars)
        return {
            "stars": stars,
            "base_stars": base_stars,
            "wrong_star_penalty": wrong_penalty,
            "bonus_star": bonus_star,
            "surprise_stars": surprise_stars,
            "star_reward_calculated": True,
        }

    @property
    def skill_upgrade_cost(self):
        return self.skill_upgrade_cost_for("experience_boost")

    @property
    def hint_delay_seconds(self):
        return 8.0

    def skill_level(self, skill_id):
        return {
            "experience_boost": self.experience_boost_level,
            "focus_shield": self.focus_shield_level,
            "magic_potion": self.magic_potion_count,
        }.get(skill_id, 0)

    def _set_skill_level(self, skill_id, level):
        level = max(0, min(SKILL_MAX_LEVELS[skill_id], int(level)))
        if skill_id == "experience_boost":
            self.experience_boost_level = level
        elif skill_id == "focus_shield":
            self.focus_shield_level = level
        elif skill_id == "magic_potion":
            self.magic_potion_count = level

    def skill_upgrade_cost_for(self, skill_id):
        level = self.skill_level(skill_id)
        if skill_id == "experience_boost":
            return 2 + level // 5
        if skill_id in ("focus_shield", "magic_potion"):
            return CONSUMABLE_STAR_COST
        raise ValueError("unknown skill_id: {}".format(skill_id))

    def can_upgrade_skill(self, skill_id):
        if skill_id not in SKILL_MAX_LEVELS:
            return False, "未知技能"
        cost = self.skill_upgrade_cost_for(skill_id)
        if skill_id == "experience_boost":
            current = self.skill_level(skill_id)
            maximum = SKILL_MAX_LEVELS[skill_id]
            if current >= maximum:
                return False, "技能已达到{}级".format(maximum)
            required_level = max(SKILL_UNLOCK_LEVEL, cost + 1)
            if self.level < required_level:
                return False, "需要达到LV.{}且保留至少LV.1".format(required_level)
        elif self.star_count < cost:
            return False, "需要{}颗累计星星".format(cost)
        return True, "可以升级"

    def upgrade_skill(self, skill_id):
        allowed, reason = self.can_upgrade_skill(skill_id)
        if not allowed:
            return {"purchased": False, "skill_id": skill_id, "reason": reason}
        cost = self.skill_upgrade_cost_for(skill_id)
        before_level = self.level
        before_stars = self.star_count
        amount = 2 if skill_id == "focus_shield" else 1
        new_skill_level = self.skill_level(skill_id) + amount
        if skill_id == "experience_boost":
            self.level = max(1, self.level - cost)
        else:
            self.star_count -= cost
        self._set_skill_level(skill_id, new_skill_level)
        self._refresh_growth_metadata()
        self.energy = min(self.energy, max(0, self.energy_max - 1))
        return {
            "purchased": True,
            "skill_id": skill_id,
            "cost_levels": cost if skill_id == "experience_boost" else 0,
            "cost_stars": 0 if skill_id == "experience_boost" else cost,
            "level_before": before_level,
            "level_after": self.level,
            "stars_before": before_stars,
            "stars_after": self.star_count,
            "skill_level": new_skill_level,
            "amount_received": amount,
        }

    def consume_focus_shield(self):
        if self.focus_shield_level <= 0:
            return False
        self.focus_shield_level -= 1
        return True

    def consume_magic_potion(self):
        if self.magic_potion_count <= 0:
            return False
        self.magic_potion_count -= 1
        return True

    def can_upgrade_experience_boost(self):
        return self.can_upgrade_skill("experience_boost")

    def upgrade_experience_boost(self):
        result = self.upgrade_skill("experience_boost")
        if result["purchased"]:
            result["bonus_star_chance_percent"] = self.bonus_star_chance_percent
            result["surprise_star_chance_percent"] = self.surprise_star_chance_percent
        return result

    def snapshot(self):
        """Return display-friendly summary dict."""
        return {
            "games_played": self.games_played,
            "total_rounds": sum(s.get("completed_rounds", 0) for s in self.summaries),
            "total_success": self.total_success,
            "total_attempts": self.total_attempts,
            "total_points": self.total_points,
            "last_game": self.last_game,
            "parent_tip": (
                self.summaries[-1].get("parent_tip", "继续陪孩子轻松探索。")
                if self.summaries else "先选择一个小游戏，和孩子一起轻松开始。"
            ),
            "level": self.level,
            "energy": self.energy,
            "energy_max": self.energy_max,
            "level_title": self.level_title,
            "max_level": MAX_LEVEL,
            "is_max_level": self.level >= MAX_LEVEL,
            "star_count": self.star_count,
            "favorite_game": self.favorite_game or "暂无",
            "leveled_up": self.just_leveled_up,
            "today_games": self.today_games,
            "today_success": self.today_success,
            "today_attempts": self.today_attempts,
            "today_stars": self.today_stars,
            "today_points": self.today_points,
            "today_duration_seconds": self.today_duration_seconds,
            "weekly_history": self.last_seven_days(),
            "unlocked_modules": list(self.unlocked_modules),
            "module_progress": {key: dict(value) for key, value in self.module_progress.items()},
            "experience_boost_level": self.experience_boost_level,
            "bonus_star_chance_percent": self.bonus_star_chance_percent,
            "surprise_star_chance_percent": self.surprise_star_chance_percent,
            "focus_shield_level": self.focus_shield_level,
            "magic_potion_count": self.magic_potion_count,
            "last_experience_gained": self.last_experience_gained,
            "skill_upgrade_cost": self.skill_upgrade_cost,
            "skill_max_level": MAX_SKILL_LEVEL,
        }

    def to_dict(self):
        return {
            "growth": {
                "level": self.level,
                "energy": self.energy,
                "energy_max": self.energy_max,
                "level_title": self.level_title,
                "max_level": MAX_LEVEL,
                "stars": self.star_count,
            },
            "totals": {"games_played": self.games_played, "total_success": self.total_success,
                       "total_attempts": self.total_attempts, "total_points": self.total_points},
            "today": {"date": self.today_date, "games_played": self.today_games,
                      "success": self.today_success, "attempts": self.today_attempts,
                      "stars": self.today_stars, "points": self.today_points,
                      "duration_seconds": self.today_duration_seconds},
            "daily_history": {
                key: dict(value) for key, value in self.daily_history.items()
            },
            "records": {"last_game": self.last_game, "favorite_game": self.favorite_game,
                        "game_counts": dict(self._game_counts)},
            "unlocked_modules": list(self.unlocked_modules),
            "module_progress": {key: dict(value) for key, value in self.module_progress.items()},
            "skills": {
                "experience_boost": {
                    "level": self.experience_boost_level,
                    "max_level": MAX_SKILL_LEVEL,
                    "bonus_star_chance_percent": self.bonus_star_chance_percent,
                    "surprise_star_chance_percent": self.surprise_star_chance_percent,
                },
                "focus_shield": {
                    "level": self.focus_shield_level,
                    "charges": self.focus_shield_level,
                },
                "magic_potion": {
                    "level": self.magic_potion_count,
                    "count": self.magic_potion_count,
                },
            },
        }

    @staticmethod
    def _count(value, default=0):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    def last_seven_days(self, today=None):
        end_date = today or date.today()
        result = []
        for offset in range(6, -1, -1):
            current = end_date - timedelta(days=offset)
            key = current.isoformat()
            entry = self.daily_history.get(key, {})
            result.append({
                "date": key,
                "label": current.strftime("%m-%d"),
                "games": self._count(entry.get("games")),
                "duration_seconds": self._count(entry.get("duration_seconds")),
                "success": self._count(entry.get("success")),
                "attempts": self._count(entry.get("attempts")),
            })
        return result

    def restore(self, data, today=None):
        data = data if isinstance(data, dict) else {}
        growth = data.get("growth", {})
        totals = data.get("totals", {})
        daily = data.get("today", {})
        records = data.get("records", {})
        daily_history = data.get("daily_history", {})
        skills = data.get("skills", {})
        boost = skills.get("experience_boost", {}) if isinstance(skills, dict) else {}
        shield = skills.get("focus_shield", {}) if isinstance(skills, dict) else {}
        potion = skills.get("magic_potion", {}) if isinstance(skills, dict) else {}
        self._set_skill_level(
            "experience_boost", self._count(boost.get("level")) if isinstance(boost, dict) else 0)
        self._set_skill_level(
            "focus_shield", self._count(shield.get("level")) if isinstance(shield, dict) else 0)
        self._set_skill_level(
            "magic_potion", self._count(potion.get("count", potion.get("level", 0)))
            if isinstance(potion, dict) else 0)
        unlocked = data.get("unlocked_modules", MODULE_IDS)
        self.unlocked_modules = [str(item) for item in unlocked if str(item) in MODULE_IDS]
        if not self.unlocked_modules:
            self.unlocked_modules = list(MODULE_IDS)
        restored_progress = data.get("module_progress", {})
        self.module_progress = default_module_progress()
        if isinstance(restored_progress, dict):
            for module_id in MODULE_IDS:
                entry = restored_progress.get(
                    module_id,
                    restored_progress.get("habit", {}) if module_id == "english" else {},
                )
                if isinstance(entry, dict):
                    self.module_progress[module_id] = {
                        "level": max(1, min(4, self._count(entry.get("level"), 1))),
                        "success": self._count(entry.get("success")),
                        "attempts": self._count(entry.get("attempts")),
                    }
        self.level = clamp_level(growth.get("level"))
        self._refresh_growth_metadata()
        self.energy = min(self._count(growth.get("energy")), self.energy_max)
        self.star_count = self._count(growth.get("stars"))
        self.games_played = self._count(totals.get("games_played"))
        self.total_success = self._count(totals.get("total_success"))
        self.total_attempts = self._count(totals.get("total_attempts"))
        self.total_points = self._count(totals.get("total_points"))
        self.last_game = str(records.get("last_game") or "暂无")
        self.favorite_game = records.get("favorite_game")
        counts = records.get("game_counts", {})
        self._game_counts = {str(k): self._count(v) for k, v in counts.items()} if isinstance(counts, dict) else {}
        self.daily_history = {}
        if isinstance(daily_history, dict):
            for key, entry in daily_history.items():
                if not isinstance(entry, dict):
                    continue
                self.daily_history[str(key)] = {
                    "games": self._count(entry.get("games")),
                    "duration_seconds": self._count(entry.get("duration_seconds")),
                    "success": self._count(entry.get("success")),
                    "attempts": self._count(entry.get("attempts")),
                }
        current = (today or date.today()).isoformat()
        self.today_date = current
        if daily.get("date") == current:
            self.today_games = self._count(daily.get("games_played"))
            self.today_success = self._count(daily.get("success"))
            self.today_attempts = self._count(daily.get("attempts"))
            self.today_stars = self._count(daily.get("stars"))
            self.today_points = self._count(daily.get("points"))
            self.today_duration_seconds = self._count(daily.get("duration_seconds"))
        else:
            self.today_games = self.today_success = self.today_attempts = self.today_stars = 0
            self.today_points = self.today_duration_seconds = 0
        if current not in self.daily_history and self.today_games:
            self.daily_history[current] = {
                "games": self.today_games,
                "duration_seconds": self.today_duration_seconds,
                "success": self.today_success,
                "attempts": self.today_attempts,
            }

    def _refresh_growth_metadata(self):
        self.level = clamp_level(self.level)
        self.energy_max = energy_required_for_level(self.level)
        self.level_title = level_title(self.level)
