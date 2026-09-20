"""Pure rules for Xingbao's color block card-lane mini game."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.action_safety import ActionSanitizer, SafeAction


DEFAULT_COLOR_BLOCK_CONFIG_PATH = Path("config/color_block_game.json")
LANES = ("star_lane", "guard_lane")
PLAYERS = ("child", "xingbao")

LaneId = Literal["star_lane", "guard_lane"]
PlayerId = Literal["child", "xingbao"]
WinnerId = Literal["child", "xingbao", "tie"]
DifficultyId = Literal["easy", "normal", "challenge"]


@dataclass(frozen=True)
class ColorBlock:
    """A configured physical block color and its game effect."""

    id: str
    label: str
    hex: str
    effect: str


@dataclass(frozen=True)
class ColorBlockGameConfig:
    """Configurable rules for the color block game."""

    colors: dict[str, ColorBlock]
    starting_hand: dict[str, int]
    rounds_to_win: int = 2
    max_rounds: int = 3
    lane_labels: dict[str, str] = field(
        default_factory=lambda: {"star_lane": "星光线", "guard_lane": "守护线"}
    )

    @classmethod
    def load(cls, path: Path | str = DEFAULT_COLOR_BLOCK_CONFIG_PATH) -> "ColorBlockGameConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Color block game config must be a JSON object.")
        colors: dict[str, ColorBlock] = {}
        for raw_color in _object_list(data.get("colors")):
            block = ColorBlock(
                id=_required_string(raw_color, "id"),
                label=_required_string(raw_color, "label"),
                hex=_required_string(raw_color, "hex"),
                effect=_required_string(raw_color, "effect"),
            )
            colors[block.id] = block
        if not colors:
            raise ValueError("Color block game config needs at least one color.")
        starting_hand = _int_mapping(data.get("starting_hand"))
        if not starting_hand:
            starting_hand = {color_id: 1 for color_id in colors}
        lane_labels = {
            lane["id"]: lane["label"]
            for lane in _object_list(data.get("lanes"))
            if isinstance(lane.get("id"), str) and isinstance(lane.get("label"), str)
        }
        for lane_id in LANES:
            lane_labels.setdefault(lane_id, lane_id)
        return cls(
            colors=colors,
            starting_hand={color_id: max(0, count) for color_id, count in starting_hand.items()},
            rounds_to_win=int(data.get("rounds_to_win", 2)),
            max_rounds=int(data.get("max_rounds", 3)),
            lane_labels=lane_labels,
        )


@dataclass(frozen=True)
class MoveResult:
    """Result returned by one attempted game action."""

    ok: bool
    message: str
    action: SafeAction
    round_over: bool = False
    game_over: bool = False


@dataclass(frozen=True)
class PlayRecord:
    """One visible block placed on the digital star board."""

    player: PlayerId
    color_id: str
    lane_id: LaneId
    points_gained: int


@dataclass
class ColorBlockGame:
    """Stateful, UI-independent game engine."""

    config: ColorBlockGameConfig = field(default_factory=ColorBlockGameConfig.load)
    rng: random.Random = field(default_factory=random.Random)
    sanitizer: ActionSanitizer = field(default_factory=ActionSanitizer)
    difficulty: DifficultyId = "normal"
    current_round: int = 1
    turn: PlayerId = "child"
    scores: dict[str, dict[str, int]] = field(default_factory=dict)
    hands: dict[str, dict[str, int]] = field(default_factory=dict)
    passed: dict[str, bool] = field(default_factory=dict)
    next_bonus: dict[str, int] = field(default_factory=dict)
    stable_lanes: dict[str, LaneId | None] = field(default_factory=dict)
    round_combo_keys: set[str] = field(default_factory=set)
    round_combo_count: int = 0
    round_winners: list[WinnerId] = field(default_factory=list)
    play_records: list[PlayRecord] = field(default_factory=list)
    game_winner: WinnerId | None = None
    final_badge: str | None = None
    last_message: str = "拿起一个颜色方块，选择一条战线吧。"

    def __post_init__(self) -> None:
        self._reset_round_state()

    def start_action(self) -> SafeAction:
        """Return the safe kickoff expression for UI or serial bridge output."""
        return self._safe({"screen_expression": "smile", "arm_action": "wave_hand"})

    def thinking_action(self) -> SafeAction:
        """Return the safe thinking expression for Xingbao's turn."""
        return self._safe({"screen_expression": "thinking", "arm_action": "stay_still"})

    def child_play(self, color_id: str, lane_id: str) -> MoveResult:
        """Play one child block into a lane."""
        return self._play("child", color_id, lane_id)

    def child_pass(self) -> MoveResult:
        """Let the child stop playing blocks for this round."""
        return self._pass("child")

    def xingbao_take_turn(self) -> MoveResult:
        """Choose and apply Xingbao's rule-based move."""
        if self.turn != "xingbao":
            return self._invalid("还没轮到星宝。")
        if self.game_winner is not None:
            return self._invalid("这一局已经结束啦。")
        if self._should_xingbao_pass():
            return self._pass("xingbao")
        color_id, lane_id = self._choose_xingbao_move()
        return self._play("xingbao", color_id, lane_id)

    def snapshot(self) -> dict[str, Any]:
        """Return serializable state for UI, tests, or future voice narration."""
        return {
            "current_round": self.current_round,
            "turn": self.turn,
            "scores": self.scores,
            "totals": {player: self.total_score(player) for player in PLAYERS},
            "hands": self.hands,
            "passed": self.passed,
            "round_winners": list(self.round_winners),
            "play_records": [record.__dict__ for record in self.play_records],
            "difficulty": self.difficulty,
            "round_combo_count": self.round_combo_count,
            "game_winner": self.game_winner,
            "final_badge": self.final_badge,
            "last_message": self.last_message,
        }

    def total_score(self, player: PlayerId) -> int:
        return sum(self.scores[player].values())

    def round_score_leader(self) -> WinnerId:
        child_score = self.total_score("child")
        xingbao_score = self.total_score("xingbao")
        if child_score > xingbao_score:
            return "child"
        if xingbao_score > child_score:
            return "xingbao"
        return "tie"

    def _play(self, player: PlayerId, color_id: str, lane_id: str) -> MoveResult:
        if self.game_winner is not None:
            return self._invalid("这一局已经结束啦。")
        if self.turn != player:
            return self._invalid("现在不是这个玩家的回合。")
        if self.passed[player]:
            return self._invalid("这一回合已经停手，不能继续出块。")
        if lane_id not in LANES:
            return self._invalid("请选择星光线或守护线。")
        if color_id not in self.config.colors:
            return self._invalid("这个颜色还没有加入游戏配置。")
        if self.hands[player].get(color_id, 0) <= 0:
            return self._invalid("这个颜色的方块已经用完啦。")

        self.hands[player][color_id] -= 1
        block = self.config.colors[color_id]
        score_before = self.total_score(player)
        effect_message = self._apply_effect(player, block, lane_id)  # type: ignore[arg-type]
        effect_message += self._apply_post_play_rules(player, color_id, lane_id)  # type: ignore[arg-type]
        self.play_records.append(
            PlayRecord(
                player=player,
                color_id=color_id,
                lane_id=lane_id,  # type: ignore[arg-type]
                points_gained=self.total_score(player) - score_before,
            )
        )
        self.passed[player] = False
        self.last_message = effect_message
        return self._finish_turn(
            player,
            effect_message,
            self._lane_action(lane_id),
        )

    def _pass(self, player: PlayerId) -> MoveResult:
        if self.game_winner is not None:
            return self._invalid("这一局已经结束啦。")
        if self.turn != player:
            return self._invalid("现在不是这个玩家的回合。")
        self.passed[player] = True
        message = "孩子停手，看看星宝怎么选择。" if player == "child" else "星宝停手，等你来收尾。"
        self.last_message = message
        return self._finish_turn(
            player,
            message,
            self._safe({"screen_expression": "smile", "arm_action": "stay_still"}),
        )

    def _finish_turn(self, player: PlayerId, message: str, action: SafeAction) -> MoveResult:
        if self._round_should_end():
            winner = self._finish_round()
            final_message = self._round_result_message(winner)
            return MoveResult(
                ok=True,
                message=final_message,
                action=self._round_result_action(winner),
                round_over=True,
                game_over=self.game_winner is not None,
            )
        self.turn = "xingbao" if player == "child" else "child"
        if self.passed[self.turn]:
            return self._finish_turn(self.turn, message, action)
        return MoveResult(ok=True, message=message, action=action)

    def _apply_effect(self, player: PlayerId, block: ColorBlock, lane_id: LaneId) -> str:
        bonus = self.next_bonus[player]
        if bonus:
            self.scores[player][lane_id] += bonus
            self.next_bonus[player] = 0

        lane_label = self.config.lane_labels[lane_id]
        player_name = "你" if player == "child" else "星宝"
        prefix = f"{player_name}把{block.label}放到{lane_label}。"
        if block.effect == "bravery":
            self.scores[player][lane_id] += 4
            return prefix + "勇气爆发，得 4 分。"
        if block.effect == "guard":
            self.scores[player][lane_id] += 3
            self.stable_lanes[player] = lane_id
            return prefix + "守护很稳，得 3 分。"
        if block.effect == "inspire":
            self.scores[player][lane_id] += 2
            self.next_bonus[player] += 2
            return prefix + "灵感亮起，得 2 分，下次出块额外加 2 分。"
        if block.effect == "repair":
            weak_lane = self._weaker_lane(player)
            self.scores[player][lane_id] += 2
            self.scores[player][weak_lane] += 2
            return prefix + "修复能量流向较弱战线，本线 2 分，弱线 2 分。"
        if block.effect == "surprise":
            return prefix + self._apply_surprise(player)
        self.scores[player][lane_id] += 1
        return prefix + "这个颜色先记 1 分。"

    def _apply_post_play_rules(self, player: PlayerId, color_id: str, lane_id: LaneId) -> str:
        messages = []
        guard_echo = self._apply_guard_echo(player)
        if guard_echo:
            messages.append(guard_echo)
        if player == "child":
            combo = self._apply_child_combo(color_id, lane_id)
            if combo:
                messages.append(combo)
        return " " + " ".join(messages) if messages else ""

    def _apply_guard_echo(self, player: PlayerId) -> str:
        if player != "xingbao":
            return ""
        stable_lane = self.stable_lanes.get("child")
        if stable_lane is None:
            return ""
        if self.total_score("child") >= self.total_score("xingbao"):
            return ""
        self.scores["child"][stable_lane] += 1
        self.stable_lanes["child"] = None
        return "蓝色守护发出回声，帮孩子补 1 点星光。"

    def _apply_child_combo(self, color_id: str, lane_id: LaneId) -> str:
        last_child_record = next(
            (record for record in reversed(self.play_records) if record.player == "child"),
            None,
        )
        if last_child_record is None:
            return ""
        pair = frozenset((last_child_record.color_id, color_id))
        combo_key = "+".join(sorted(pair))
        if combo_key in self.round_combo_keys:
            return ""

        message = ""
        if pair == frozenset(("red", "yellow")):
            self.scores["child"][lane_id] += 2
            message = "触发勇气灵感连携，本线额外 +2。"
        elif pair == frozenset(("blue", "green")):
            weak_lane = self._weaker_lane("child")
            self.scores["child"][weak_lane] += 2
            message = "触发守护修复连携，较弱战线额外 +2。"
        elif pair == frozenset(("red", "blue")):
            if abs(self.scores["child"]["star_lane"] - self.scores["child"]["guard_lane"]) <= 2:
                self.scores["child"]["star_lane"] += 1
                self.scores["child"]["guard_lane"] += 1
                message = "触发平衡之心，两条线各 +1。"
        elif pair == frozenset(("yellow", "purple")):
            weak_lane = self._weaker_lane("child")
            self.scores["child"][weak_lane] += 2
            message = "触发星谜灵感，小星门照亮较弱战线 +2。"
        elif pair == frozenset(("green", "purple")):
            revived = self._revive_child_block(exclude=color_id)
            if revived:
                message = f"触发生命星尘，{self.config.colors[revived].label}可以再用一次。"

        if not message:
            return ""
        self.round_combo_keys.add(combo_key)
        self.round_combo_count += 1
        return message

    def _revive_child_block(self, exclude: str) -> str | None:
        for color_id in self.config.colors:
            if color_id != exclude and self.hands["child"].get(color_id, 0) <= 0:
                self.hands["child"][color_id] = 1
                return color_id
        return None

    def _apply_surprise(self, player: PlayerId) -> str:
        surprise = self.rng.choice(("star", "guard", "both"))
        if surprise == "star":
            self.scores[player]["star_lane"] += 3
            return "惊喜落在星光线，得 3 分。"
        if surprise == "guard":
            self.scores[player]["guard_lane"] += 3
            return "惊喜落在守护线，得 3 分。"
        self.scores[player]["star_lane"] += 1
        self.scores[player]["guard_lane"] += 1
        return "惊喜分给两条战线，各得 1 分。"

    def _choose_xingbao_move(self) -> tuple[str, LaneId]:
        hand = self.hands["xingbao"]
        available = [color_id for color_id, count in hand.items() if count > 0]
        if not available:
            return "red", "star_lane"
        lane = self._weaker_lane("xingbao")
        if self.difficulty == "easy":
            for preferred in ("green", "blue", "yellow", "purple", "red"):
                if preferred in available:
                    return preferred, lane
        if self.difficulty == "challenge" and self._last_xingbao_color() == "yellow" and "red" in available:
            return "red", lane
        if self.total_score("xingbao") < self.total_score("child"):
            for preferred in ("red", "green", "purple", "blue", "yellow"):
                if preferred in available:
                    return preferred, lane
        for preferred in ("blue", "yellow", "green", "purple", "red"):
            if preferred in available:
                return preferred, lane
        return available[0], lane

    def _should_xingbao_pass(self) -> bool:
        if not any(count > 0 for count in self.hands["xingbao"].values()):
            return True
        if self.passed["child"] and self.total_score("xingbao") > self.total_score("child"):
            return True
        lead_limit = 3 if self.difficulty == "easy" else 6 if self.difficulty == "challenge" else 5
        if self.total_score("xingbao") - self.total_score("child") >= lead_limit:
            return True
        return False

    def _last_xingbao_color(self) -> str | None:
        for record in reversed(self.play_records):
            if record.player == "xingbao":
                return record.color_id
        return None

    def _finish_round(self) -> WinnerId:
        winner = self.round_score_leader()
        self.round_winners.append(winner)
        if winner == "child":
            child_wins = self.round_winners.count("child")
            if child_wins >= self.config.rounds_to_win:
                self.game_winner = "child"
        elif winner == "xingbao":
            xingbao_wins = self.round_winners.count("xingbao")
            if xingbao_wins >= self.config.rounds_to_win:
                self.game_winner = "xingbao"

        if self.game_winner is None and len(self.round_winners) >= self.config.max_rounds:
            child_wins = self.round_winners.count("child")
            xingbao_wins = self.round_winners.count("xingbao")
            if child_wins > xingbao_wins:
                self.game_winner = "child"
            elif xingbao_wins > child_wins:
                self.game_winner = "xingbao"
            else:
                self.game_winner = "tie"

        if self.game_winner is None:
            self.current_round += 1
            self._reset_round_state()
        return winner

    def _round_result_message(self, winner: WinnerId) -> str:
        if self.game_winner == "child":
            self._assign_final_badge()
            self.last_message = f"你赢下整局啦，星宝为你鼓掌！{self.final_badge}"
            return self.last_message
        if self.game_winner == "xingbao":
            self._assign_final_badge()
            self.last_message = f"星宝赢下整局，但它也在给你加油。{self.final_badge}"
            return self.last_message
        if self.game_winner == "tie":
            self._assign_final_badge()
            self.last_message = f"整局打成平手，配合得刚刚好。{self.final_badge}"
            return self.last_message
        if winner == "child":
            self.last_message = "这一回合你领先，下一回合继续！"
        elif winner == "xingbao":
            self.last_message = "这一回合星宝领先，它提醒你还有机会。"
        else:
            self.last_message = "这一回合平手，新的回合开始。"
        return self.last_message

    def _assign_final_badge(self) -> None:
        if self.final_badge is not None:
            return
        child_colors = [record.color_id for record in self.play_records if record.player == "child"]
        if self.round_combo_count:
            self.final_badge = " 本局称号：灵感连携星。"
            return
        if not child_colors:
            self.final_badge = " 本局称号：安静观察星。"
            return
        favorite = max(child_colors, key=child_colors.count)
        badge_by_color = {
            "red": " 本局称号：勇气星。",
            "blue": " 本局称号：守护星。",
            "yellow": " 本局称号：灵感星。",
            "green": " 本局称号：修复星。",
            "purple": " 本局称号：惊喜星。",
        }
        self.final_badge = badge_by_color.get(favorite, " 本局称号：平衡星。")

    def _round_result_action(self, winner: WinnerId) -> SafeAction:
        if self.game_winner == "child":
            return self._safe({"screen_expression": "smile", "arm_action": "nod"})
        if self.game_winner == "xingbao":
            return self._safe({"screen_expression": "smile", "led_mode": "warm_breath"})
        if winner == "child":
            return self._safe({"screen_expression": "smile", "arm_action": "nod"})
        if winner == "xingbao":
            return self._safe({"screen_expression": "curious", "led_mode": "warm_breath"})
        return self._safe({"screen_expression": "smile"})

    def _round_should_end(self) -> bool:
        return all(self.passed.values()) or all(
            not any(count > 0 for count in self.hands[player].values()) for player in PLAYERS
        )

    def _reset_round_state(self) -> None:
        self.scores = {player: {lane: 0 for lane in LANES} for player in PLAYERS}
        self.hands = {
            player: {
                color_id: int(self.config.starting_hand.get(color_id, 0))
                for color_id in self.config.colors
            }
            for player in PLAYERS
        }
        self.passed = {player: False for player in PLAYERS}
        self.next_bonus = {player: 0 for player in PLAYERS}
        self.stable_lanes = {player: None for player in PLAYERS}
        self.round_combo_keys = set()
        self.round_combo_count = 0
        self.play_records = []
        self.turn = "child"

    def _weaker_lane(self, player: PlayerId) -> LaneId:
        star_score = self.scores[player]["star_lane"]
        guard_score = self.scores[player]["guard_lane"]
        return "star_lane" if star_score <= guard_score else "guard_lane"

    def _lane_action(self, lane_id: str) -> SafeAction:
        arm_action = "point_left" if lane_id == "star_lane" else "point_right"
        return self._safe({"screen_expression": "smile", "arm_action": arm_action})

    def _invalid(self, message: str) -> MoveResult:
        self.last_message = message
        return MoveResult(
            ok=False,
            message=message,
            action=self._safe({"screen_expression": "sad", "arm_action": "shake_head"}),
            game_over=self.game_winner is not None,
        )

    def _safe(self, proposal: Mapping[str, Any] | str | None) -> SafeAction:
        return self.sanitizer.sanitize(proposal)


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required string: {key}")
    return value.strip()


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        if isinstance(key, str) and isinstance(raw_count, int):
            result[key] = raw_count
    return result
