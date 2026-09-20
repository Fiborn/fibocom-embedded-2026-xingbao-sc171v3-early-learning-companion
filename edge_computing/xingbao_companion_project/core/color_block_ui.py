"""Premium Tkinter canvas UI for Xingbao's color block mini game."""

from __future__ import annotations

import math
import random
import tkinter as tk
from dataclasses import dataclass
from typing import Any

from core.action_bus import ActionBus
from core.color_block_game import ColorBlockGame, LANES, MoveResult
from core.color_block_voice import parse_color_block_voice_command
from core.serial_bridge import SerialBridge


BG = "#070914"
PANEL = "#101829"
GOLD = "#f5c45b"
CYAN = "#55dcff"
VIOLET = "#a875ff"
TEXT = "#f4f0dc"
MUTED = "#94a0b8"
CHILD = "child"
XINGBAO = "xingbao"


@dataclass(frozen=True)
class Slot:
    x: float
    y: float
    size: float
    color_id: str


class ColorBlockGameWindow:
    """A mysterious star-board UI for voice-first physical block play."""

    def __init__(self, *, serial_port: str | None = None, game: ColorBlockGame | None = None) -> None:
        self.root = tk.Tk()
        self.root.title("星宝色块牌阵")
        self.root.geometry("1280x720")
        self.root.minsize(1024, 600)
        self.root.configure(bg=BG)
        self.game = game or ColorBlockGame()
        self.action_bus = ActionBus()
        self.serial_bridge = (
            SerialBridge(serial_port, action_bus=self.action_bus) if serial_port else None
        )
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.command_var = tk.StringVar()
        self.command_entry = tk.Entry(
            self.root,
            textvariable=self.command_var,
            font=("Microsoft YaHei UI", 16),
            bg="#0f1728",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )
        self.command_entry.bind("<Return>", lambda _event: self._submit_voice_command())
        self.submit_button = tk.Button(
            self.root,
            text="确认语音",
            command=self._submit_voice_command,
            font=("Microsoft YaHei UI", 13, "bold"),
            bg="#20344f",
            fg=TEXT,
            activebackground="#2b4d74",
            activeforeground=TEXT,
            relief="flat",
            padx=18,
            pady=8,
        )
        self.pass_button = tk.Button(
            self.root,
            text="停手",
            command=self._child_pass,
            font=("Microsoft YaHei UI", 13, "bold"),
            bg="#3d2e54",
            fg=TEXT,
            activebackground="#573f79",
            activeforeground=TEXT,
            relief="flat",
            padx=18,
            pady=8,
        )
        self.phase = 0.0
        self.avatar_state = "listening"
        self.speech_text = "我在听，你可以说：红色放星光线。"
        self.voice_status = "正在聆听"
        self.last_action_label = "等待孩子移动色块"
        self.controls_enabled = True
        self.starfield = self._build_starfield()
        self.root.bind("<Configure>", lambda _event: self._draw())
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._schedule_animation()

    def run(self) -> None:
        if self.serial_bridge is not None:
            self.serial_bridge.__enter__()
        self._emit(self.game.start_action())
        self._speak("星阵已经开启，我在听你说话。", state="listening")
        try:
            self.root.mainloop()
        finally:
            if self.serial_bridge is not None:
                self.serial_bridge.__exit__(None, None, None)

    def _submit_voice_command(self) -> None:
        if not self.controls_enabled:
            return
        text = self.command_var.get().strip()
        self.command_var.set("")
        command = parse_color_block_voice_command(text)
        self.voice_status = f"听到：{text}" if text else "没有听清"
        if command.intent == "play" and command.color_id and command.lane_id:
            self._handle_result(self.game.child_play(command.color_id, command.lane_id))
            return
        if command.intent == "pass":
            self._child_pass()
            return
        if command.intent == "hint":
            self._emit({"screen_expression": "thinking", "arm_action": "stay_still"})
            self._speak(self._build_hint(), state="thinking")
            self._draw()
            return
        self._emit({"screen_expression": "sad", "arm_action": "shake_head"})
        self._speak(command.message, state="confused")
        self._draw()

    def _child_pass(self) -> None:
        if not self.controls_enabled:
            return
        self._handle_result(self.game.child_pass())

    def _handle_result(self, result: MoveResult) -> None:
        self._emit(result.action)
        self._speak(result.message, state=self._state_for_result(result))
        self._draw()
        if result.ok and not result.game_over and self.game.turn == XINGBAO:
            self.controls_enabled = False
            self.avatar_state = "thinking"
            self.voice_status = "星宝正在思考"
            self.root.after(700, self._xingbao_turn)

    def _xingbao_turn(self) -> None:
        self._emit(self.game.thinking_action())
        result = self.game.xingbao_take_turn()
        self._emit(result.action)
        self._speak(result.message, state=self._state_for_result(result))
        self._draw()
        if result.ok and not result.game_over and self.game.turn == XINGBAO:
            self.root.after(700, self._xingbao_turn)
            return
        self.controls_enabled = not result.game_over
        # Do not append a second "Xingbao is listening" status after the
        # visible thinking state; the controls themselves already indicate
        # that the child can take the next turn.
        self.voice_status = "" if self.controls_enabled else "游戏结束"

    def _build_hint(self) -> str:
        child_star = self.game.scores[CHILD]["star_lane"]
        child_guard = self.game.scores[CHILD]["guard_lane"]
        if child_star <= child_guard:
            return "星光线现在偏弱，可以考虑把红色或绿色放到星光线。"
        return "守护线现在偏弱，可以考虑把蓝色或绿色放到守护线。"

    def _state_for_result(self, result: MoveResult) -> str:
        if not result.ok:
            return "confused"
        if result.game_over or result.round_over:
            return "celebrate" if self.game.game_winner != XINGBAO else "comfort"
        action = result.action.as_dict()
        if action.get("arm_action") == "point_left":
            return "point_left"
        if action.get("arm_action") == "point_right":
            return "point_right"
        if self.game.turn == XINGBAO:
            return "thinking"
        return "confirm"

    def _speak(self, text: str, *, state: str) -> None:
        self.speech_text = text
        self.avatar_state = state
        self.last_action_label = text

    def _schedule_animation(self) -> None:
        self.phase += 0.035
        self._draw()
        self.root.after(33, self._schedule_animation)

    def _draw(self) -> None:
        width = max(self.canvas.winfo_width(), 1024)
        height = max(self.canvas.winfo_height(), 600)
        self.canvas.delete("all")
        self._draw_background(width, height)
        self._draw_header(width, height)
        self._draw_lanes(width, height)
        self._draw_slots(width, height)
        self._draw_avatar(width, height)
        self._draw_voice_bar(width, height)

    def _draw_background(self, width: int, height: int) -> None:
        self.canvas.create_rectangle(0, 0, width, height, fill=BG, outline="")
        for x, y, size, speed in self.starfield:
            sx = (x * width + math.sin(self.phase * speed + y * 7) * 8) % width
            sy = y * height
            brightness = int(120 + 90 * (0.5 + 0.5 * math.sin(self.phase * speed + x * 11)))
            color = f"#{brightness:02x}{brightness:02x}{min(255, brightness + 30):02x}"
            self.canvas.create_oval(sx, sy, sx + size, sy + size, fill=color, outline="")
        for offset, color in ((0, "#11182a"), (44, "#0e1525")):
            for x in range(-width, width * 2, 88):
                self.canvas.create_line(x + offset, 0, x - height + offset, height, fill=color, width=1)

    def _draw_header(self, width: int, _height: int) -> None:
        snapshot = self.game.snapshot()
        child_wins = snapshot["round_winners"].count(CHILD)
        xingbao_wins = snapshot["round_winners"].count(XINGBAO)
        self._rounded_rect(28, 22, width - 28, 78, 18, fill="#0c1220", outline="#263550")
        self.canvas.create_text(
            52,
            50,
            anchor="w",
            text=f"第 {snapshot['current_round']} 回合",
            fill=TEXT,
            font=("Microsoft YaHei UI", 19, "bold"),
        )
        self.canvas.create_text(
            width / 2,
            50,
            text=f"孩子 {child_wins} : {xingbao_wins} 星宝",
            fill=GOLD,
            font=("Microsoft YaHei UI", 21, "bold"),
        )
        turn_text = "轮到孩子" if snapshot["turn"] == CHILD else "星宝回合"
        self.canvas.create_text(
            width - 52,
            50,
            anchor="e",
            text=f"{turn_text} · {self.voice_status}",
            fill=CYAN,
            font=("Microsoft YaHei UI", 14),
        )

    def _draw_lanes(self, width: int, height: int) -> None:
        star_power = self._lane_power("star_lane")
        guard_power = self._lane_power("guard_lane")
        self._draw_flow_lane(
            width * 0.16,
            height * 0.36,
            width * 0.84,
            height * 0.46,
            GOLD,
            "星光线",
            star_power,
        )
        self._draw_flow_lane(
            width * 0.18,
            height * 0.56,
            width * 0.82,
            height * 0.66,
            CYAN,
            "守护线",
            guard_power,
        )
        snapshot = self.game.snapshot()
        self.canvas.create_text(
            width / 2,
            height * 0.49,
            text=f"{snapshot['totals'][CHILD]}  :  {snapshot['totals'][XINGBAO]}",
            fill=TEXT,
            font=("Microsoft YaHei UI", 38, "bold"),
        )
        self.canvas.create_text(
            width / 2,
            height * 0.545,
            text="孩子总能量    星宝总能量",
            fill=MUTED,
            font=("Microsoft YaHei UI", 13),
        )

    def _draw_flow_lane(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        label: str,
        power: float,
    ) -> None:
        width = 8 + power * 12
        glow_width = width + 18
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2 + 26 * math.sin(self.phase * 0.8)
        self.canvas.create_line(
            x1,
            y1,
            mid_x,
            mid_y,
            x2,
            y2,
            smooth=True,
            fill=color,
            width=glow_width,
            stipple="gray25",
        )
        self.canvas.create_line(
            x1,
            y1,
            mid_x,
            mid_y,
            x2,
            y2,
            smooth=True,
            fill=color,
            width=width,
        )
        particle_count = 10 + int(power * 18)
        for index in range(particle_count):
            t = ((self.phase * (0.16 + power * 0.16)) + index / particle_count) % 1.0
            px = (1 - t) * x1 + t * x2
            py = (1 - t) * y1 + t * y2 + math.sin(t * math.pi) * 30
            radius = 2 + power * 3
            self.canvas.create_oval(
                px - radius,
                py - radius,
                px + radius,
                py + radius,
                fill=color,
                outline="",
            )
        self.canvas.create_text(
            x1 + 16,
            y1 - 34,
            anchor="w",
            text=label,
            fill=color,
            font=("Microsoft YaHei UI", 23, "bold"),
        )

    def _draw_slots(self, width: int, height: int) -> None:
        snapshot = self.game.snapshot()
        records = snapshot["play_records"]
        child_records = [record for record in records if record["player"] == CHILD]
        xingbao_records = [record for record in records if record["player"] == XINGBAO]
        child_slots = self._child_slots(width, height)
        xingbao_slots = self._xingbao_slots(width, height)
        self.canvas.create_text(
            width * 0.08,
            height * 0.13,
            anchor="w",
            text="孩子星阵",
            fill=GOLD,
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        self.canvas.create_text(
            width * 0.92,
            height * 0.74,
            anchor="e",
            text="星宝回应阵",
            fill=CYAN,
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        for index, slot in enumerate(child_slots):
            self._draw_slot(slot, child_records[index] if index < len(child_records) else None)
        for index, slot in enumerate(xingbao_slots):
            self._draw_slot(slot, xingbao_records[index] if index < len(xingbao_records) else None)

    def _draw_slot(self, slot: Slot, record: dict[str, Any] | None) -> None:
        block = self.game.config.colors[slot.color_id]
        half = slot.size / 2
        fill = "#111a2e" if record is None else block.hex
        outline = block.hex
        pulse = 0.5 + 0.5 * math.sin(self.phase * 3 + slot.x * 0.01)
        self._rounded_rect(
            slot.x - half - 5,
            slot.y - half - 5,
            slot.x + half + 5,
            slot.y + half + 5,
            14,
            fill="#0c1220",
            outline=outline,
            width=2 + int(pulse * 2),
        )
        self._rounded_rect(
            slot.x - half,
            slot.y - half,
            slot.x + half,
            slot.y + half,
            12,
            fill=fill,
            outline="#ffffff" if record else "#30405f",
            width=1,
        )
        label = block.label[:2] if record is None else f"+{record['points_gained']}"
        self.canvas.create_text(
            slot.x,
            slot.y,
            text=label,
            fill="#07101f" if record else TEXT,
            font=("Microsoft YaHei UI", 16, "bold"),
        )

    def _draw_avatar(self, width: int, height: int) -> None:
        cx = width / 2
        cy = height * 0.18 + math.sin(self.phase * 2) * 5
        self.canvas.create_oval(cx - 95, cy - 72, cx + 95, cy + 78, fill="#0c1324", outline=VIOLET, width=2)
        for index in range(4):
            angle = self.phase * 1.2 + index * math.pi / 2
            sx = cx + math.cos(angle) * 72
            sy = cy + math.sin(angle) * 30
            self.canvas.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, fill=GOLD, outline="")
        self.canvas.create_oval(cx - 42, cy - 48, cx + 42, cy + 36, fill="#ecf7ff", outline=CYAN, width=3)
        self.canvas.create_oval(cx - 58, cy + 18, cx + 58, cy + 86, fill="#d8e8ff", outline=VIOLET, width=3)
        eye_offset = 14 if self.avatar_state != "confused" else 10
        self.canvas.create_oval(cx - eye_offset - 5, cy - 18, cx - eye_offset + 5, cy - 8, fill="#14213a", outline="")
        self.canvas.create_oval(cx + eye_offset - 5, cy - 18, cx + eye_offset + 5, cy - 8, fill="#14213a", outline="")
        mouth_y = cy + 8
        if self.avatar_state in {"celebrate", "confirm"}:
            self.canvas.create_arc(cx - 14, mouth_y - 6, cx + 14, mouth_y + 18, start=200, extent=140, outline="#14213a", width=3, style="arc")
        elif self.avatar_state == "thinking":
            self.canvas.create_oval(cx - 5, mouth_y, cx + 5, mouth_y + 5, fill="#14213a", outline="")
        else:
            self.canvas.create_line(cx - 10, mouth_y + 4, cx + 10, mouth_y + 4, fill="#14213a", width=3)
        self._draw_avatar_arms(cx, cy)
        self._draw_speech_bubble(cx + 96, cy - 42, width)

    def _draw_avatar_arms(self, cx: float, cy: float) -> None:
        left_target = (cx - 78, cy + 22)
        right_target = (cx + 78, cy + 22)
        if self.avatar_state == "point_left":
            left_target = (cx - 145, cy + 18)
        elif self.avatar_state == "point_right":
            right_target = (cx + 145, cy + 18)
        elif self.avatar_state == "celebrate":
            left_target = (cx - 70, cy - 18)
            right_target = (cx + 70, cy - 18)
        elif self.avatar_state == "comfort":
            left_target = (cx - 54, cy + 42)
            right_target = (cx + 54, cy + 42)
        self.canvas.create_line(cx - 48, cy + 42, *left_target, fill="#d8e8ff", width=8, capstyle="round")
        self.canvas.create_line(cx + 48, cy + 42, *right_target, fill="#d8e8ff", width=8, capstyle="round")

    def _draw_speech_bubble(self, x: float, y: float, width: int) -> None:
        max_width = min(420, width - x - 30)
        if max_width < 230:
            x = 36
            y += 84
            max_width = min(520, width - 72)
        lines = self._wrap_text(self.speech_text, 20)
        bubble_h = 42 + 24 * len(lines)
        self._rounded_rect(x, y, x + max_width, y + bubble_h, 18, fill="#111b30", outline="#365077")
        self.canvas.create_text(
            x + 18,
            y + 20,
            anchor="nw",
            text="\n".join(lines),
            fill=TEXT,
            font=("Microsoft YaHei UI", 13, "bold"),
        )

    def _draw_voice_bar(self, width: int, height: int) -> None:
        bar_y = height - 96
        self._rounded_rect(34, bar_y, width - 34, height - 28, 24, fill="#0c1324", outline="#263a60")
        self.canvas.create_text(
            60,
            bar_y + 22,
            anchor="w",
            text="语音指令",
            fill=CYAN,
            font=("Microsoft YaHei UI", 14, "bold"),
        )
        self.canvas.create_text(
            60,
            bar_y + 48,
            anchor="w",
            text="说：红色放星光线 / 蓝色放守护线 / 我要停手 / 给我提示",
            fill=MUTED,
            font=("Microsoft YaHei UI", 12),
        )
        self.canvas.create_window(width * 0.5, bar_y + 36, window=self.command_entry, width=360, height=38)
        self.canvas.create_window(width - 240, bar_y + 36, window=self.submit_button)
        self.canvas.create_window(width - 112, bar_y + 36, window=self.pass_button)

    def _lane_power(self, lane_id: str) -> float:
        score = self.game.scores[CHILD][lane_id] + self.game.scores[XINGBAO][lane_id]
        return min(1.0, score / 16)

    def _child_slots(self, width: int, height: int) -> list[Slot]:
        size = min(width, height) * 0.07
        start_x = width * 0.1
        start_y = height * 0.21
        offsets = ((0, 0), (1.1, -0.22), (2.2, 0), (0.55, 1.05), (1.65, 1.05))
        return self._slots_from_offsets(start_x, start_y, size, offsets)

    def _xingbao_slots(self, width: int, height: int) -> list[Slot]:
        size = min(width, height) * 0.07
        start_x = width * 0.72
        start_y = height * 0.76
        offsets = ((0, 0), (1.1, -0.22), (2.2, 0), (0.55, 1.05), (1.65, 1.05))
        return self._slots_from_offsets(start_x, start_y, size, offsets)

    def _slots_from_offsets(
        self,
        start_x: float,
        start_y: float,
        size: float,
        offsets: tuple[tuple[float, float], ...],
    ) -> list[Slot]:
        color_ids = list(self.game.config.colors.keys())[:5]
        return [
            Slot(start_x + ox * size * 1.35, start_y + oy * size * 1.35, size, color_id)
            for (ox, oy), color_id in zip(offsets, color_ids)
        ]

    def _emit(self, proposal: Any) -> None:
        if self.serial_bridge is not None and self.serial_bridge.serial_connection is not None:
            self.serial_bridge.send_action(proposal)
        else:
            self.action_bus.emit(proposal)

    def _close(self) -> None:
        self.root.destroy()

    def _build_starfield(self) -> list[tuple[float, float, float, float]]:
        rng = random.Random(42)
        return [(rng.random(), rng.random(), rng.uniform(1, 3), rng.uniform(0.4, 1.4)) for _ in range(130)]

    def _rounded_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        *,
        fill: str,
        outline: str = "",
        width: int = 1,
    ) -> None:
        self.canvas.create_polygon(
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
            smooth=True,
            fill=fill,
            outline=outline,
            width=width,
        )

    def _wrap_text(self, text: str, line_chars: int) -> list[str]:
        if len(text) <= line_chars:
            return [text]
        return [text[index : index + line_chars] for index in range(0, len(text), line_chars)]


def launch_color_block_game(*, serial_port: str | None = None) -> None:
    ColorBlockGameWindow(serial_port=serial_port).run()
