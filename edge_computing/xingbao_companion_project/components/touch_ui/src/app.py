"""星宝陪伴桌 V6 — 竞赛级 AIoT 智能终端主应用。

Asset-driven rendering: pre-rendered PNGs for backgrounds, characters, icons.
Pygame handles: text, dynamic effects, touch hit areas, game logic.

Text rendering policy (v6.1 cleanup):
- All static Chinese text → FontManager via draw_text / draw_wrapped_text
- Status chips (LOCAL/TOUCH/SAFE/READY) → pygame font, no PNG
- Energy orbs, shape icons, character sprites → PNG (already transparent)
- Bottom buttons → FontManager (no PNG text overlay)
"""

import math
import os
import uuid
from datetime import datetime
from pathlib import Path

import pygame

from . import theme
from .asset_loader import AssetLoader
from .autosave import AutoSaveManager
from .demo_timing import get_demo_timing, normalize_demo_speed
from .demo import draw_demo_pointer
from .effects import (
    draw_hud_grid, draw_starfield, draw_scanline, init_starfield, draw_glow_circle,
)
from .events import EventName
from .games import ColorGame, CountingGame, EnglishGame, MemoryPathGame, ShapeGame, SkillGame
from .games.base_game import ChoiceResult
from .growth_support import FirstMistakeSupport
from .difficulty import PLAYER_DIFFICULTIES
from .layout import Layout
from .layout_debug import draw_debug_overlay
from .logger import JsonlEventLogger
from .records import MAX_SKILL_LEVEL, SKILL_MAX_LEVELS, SKILL_UNLOCK_LEVEL, SessionRecords
from .speech_state import SpeechState
from .states import AppState
from .system_status import SystemStatus
from .ui_registry import UIRegistry
from .xingbao_animator import XingbaoAnimator, IDLE, THINKING, HAPPY, ENCOURAGE, CELEBRATE
from .ui_components import (
    Button, CompanionPanel, GameTile, ShapeOptionCard, ColorOptionCard,
    FeedbackPanel, TechPanel,
    draw_glass_panel, draw_text, draw_wrapped_text, get_font, fit_font, blit_cover,
)


GAME_META = {
    "color":  {"title": "颜色", "desc": "", "icon": "color",
               "bg": (25, 55, 100, 200)},
    "shape":  {"title": "形状", "desc": "", "icon": "shape",
               "bg": (30, 65, 110, 200)},
    "memory": {"title": "记忆", "desc": "", "icon": "memory",
               "bg": (22, 68, 72, 200)},
    "counting": {"title": "数数", "desc": "", "icon": "counting",
                 "bg": (65, 52, 105, 200)},
    "english": {"title": "英语", "desc": "", "icon": "english",
              "bg": (28, 82, 75, 200)},
    "skill": {"title": "挑战", "desc": "", "icon": "skill",
              "bg": (72, 42, 92, 200)},
}

DEMO_MOVE_DURATION = 1.2
DEMO_PRESS_DURATION = 0.7
DEMO_RESULT_DURATION = 1.6
MEMORY_VISIBLE_UPDATE_STEP = 0.12
TOUCH_DUPLICATE_WINDOW_MS = 250
TOUCH_DUPLICATE_DISTANCE_PX = 24


def _target_fps(env_name, default):
    try:
        value = int(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        value = int(default)
    return max(5, min(30, value))


SKILL_META = {
    "experience_boost": {
        "title": "星运增幅",
        "description": "提升星运，完成游戏时更容易获得额外星星。",
    },
    "focus_shield": {
        "title": "专注护盾",
        "description": "答错时自动保护得分，每次购买获得2个。",
    },
    "magic_potion": {
        "title": "魔法药水",
        "description": "让下一局获得更多经验，但答错时会扣更多分。",
    },
}


class XingbaoApp:
    def __init__(self, fullscreen=True, size=(1280, 720), log_dir=None, low_effects=False,
                 save_dir="saves", demo_speed="slow", debug_layout=False, preload_only=False,
                 on_speech_request=None, on_game_state=None):
        pygame.init()
        self.on_speech_request = on_speech_request
        self.on_game_state = on_game_state
        self.game_state_session_id = str(uuid.uuid4())
        self.game_state_revision = 0
        self._last_game_state_signature = None
        self._pending_prefetch_texts = []
        pygame.display.set_caption("星宝游戏乐园")
        flags = pygame.HIDDEN if preload_only else (pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE)
        self.fullscreen = fullscreen
        self.screen = pygame.display.set_mode((1, 1) if preload_only else size, flags)
        self.clock = pygame.time.Clock()
        self.low_effects = bool(low_effects)
        self.target_fps = _target_fps(
            "XINGBAO_GAME_FPS",
            12 if self.low_effects else 30,
        )
        self.event_fps = 30
        self.debug_layout = bool(debug_layout)
        self.effect_time = 0.0
        self.scanline_enabled = not self.low_effects
        sc = 45 if self.low_effects else 110
        self.stars = init_starfield(size[0], size[1], count=sc, seed=27)
        self.particles = self.stars  # legacy alias for tests

        # Asset loader
        assets_root = Path(__file__).resolve().parent.parent / "assets"
        self.assets = AssetLoader(str(assets_root))
        self._load_assets()

        self.logger = JsonlEventLogger(log_dir=log_dir or Path("logs"))
        self.records = SessionRecords()
        self.demo_speed = normalize_demo_speed(demo_speed)
        self.demo_timing = get_demo_timing(self.demo_speed)
        self.autosave = AutoSaveManager(save_dir=save_dir, logger=self.logger)
        self.system_status = SystemStatus(
            local_mode=True,
            touch_ready=True,
            safe_mode=True,
            session_active=True,
            autosave_enabled=True,
            storage_writable=self.logger.last_error is None and self.autosave.last_error is None,
            touch_input_mode="mouse_fallback",
        )
        self.ui_registry = UIRegistry()
        self.xingbao_animator = XingbaoAnimator()
        self.confirm_clear_save = False
        self.voice_paused = False
        loaded = self.autosave.load_latest()
        if loaded:
            self.records.restore(loaded)
            self.log(EventName.AUTOSAVE_LOADED, page="startup",
                     payload={"path": str(self.autosave.latest_path)})
        elif self.autosave.last_error:
            self.log(EventName.AUTOSAVE_FAILED, page="startup",
                     payload={"reason": "load", "error": self.autosave.last_error})
        self.log(EventName.DEMO_SPEED_CHANGED, page="startup",
                 payload={"speed": self.demo_speed})
        self.log(EventName.STATUS_INITIALIZED, page="startup",
                 payload=self.system_status.to_dict())
        self._exit_saved = False
        self.state = AppState.HOME
        self.game = None
        self.last_game_id = "color"
        self.last_summary = None
        self.last_game_screenshot = None
        self.pending_game_id = None
        self.selected_difficulty = 1
        self.last_difficulty = 1
        self.selected_skill_id = "experience_boost"
        self.focus_shields_remaining = 0
        self.current_score = 100
        self.current_game_elapsed = 0.0
        self.magic_potion_active = False
        self.buttons = []
        # Some touchscreen drivers emit both FINGERUP and MOUSEBUTTONUP for one
        # physical tap. Keep the last release so the duplicate cannot become a
        # second answer in sequence-based games.
        self._last_touch_release = None
        self.running = True
        self.active = False
        self.message = "选择一个任务模块，开始今天的星际探索吧。"
        self.mood = "normal"
        self.feedback_success = True
        self.feedback_remaining = 0.0
        self.feedback_wait_remaining = 0.0
        self.feedback_utterance_id = None
        self.feedback_speech_done = True
        self.feedback_question_id = None
        self.feedback_question_prompt = ""
        self.feedback_question_state = {}
        self.first_mistake_support = FirstMistakeSupport()
        self.active_support_sequence = None
        self.growth_support_phase = ""
        self.growth_high_five_remaining = 0.0
        self.growth_support_wait_remaining = 0.0
        self.speech_state = SpeechState()
        self.wait_elapsed = 0.0
        self.hint_after_seconds = self.records.hint_delay_seconds
        self.focus_shields_remaining = self.records.focus_shield_level
        self._summary_recorded = False
        # Demo state
        self.demo_game_ids = ["color", "shape", "memory", "counting", "english", "skill"]
        self.demo_index = 0
        self.demo_view = "home"
        self.demo_stage = "move"
        self.demo_remaining = 0.0
        self.demo_instruction = ""
        self.demo_target_kind = None
        self.demo_target_id = None
        self.demo_target_name = None
        self.demo_target_key = None
        self.demo_pointer_pos = None
        self.demo_target_rect = None
        self.demo_show_feedback = False
        self.demo_complete_after_result = False
        self.speak(self.message, page="home", role="welcome")
        self.show_state("normal", page="home")

    # ── helpers ────────────────────────────────────────────────

    def log(self, event_name, page=None, payload=None, game_id=None):
        return self.logger.log(event_name, page or self.state.value.lower(),
                               payload=payload or {},
                               game_id=game_id if game_id is None else (self.game.game_id if self.game else None))

    def current_question_id(self):
        game = getattr(self, "game", None)
        if not game or game.is_finished():
            return None
        target = getattr(game, "target_id", None)
        if target is None:
            target = getattr(game, "phase", "question")
        return "{}:{}:{}".format(
            game.game_id,
            getattr(game, "current_round_number", 1),
            target,
        )

    def _queue_prompt_prefetch(self, text):
        text = str(text or "").strip()
        if text and text not in self._pending_prefetch_texts:
            self._pending_prefetch_texts.append(text)

    def _publish_game_state(self, reason=""):
        """Send one non-blocking, versioned UI snapshot to the central core."""
        callback = getattr(self, "on_game_state", None)
        if not callable(callback):
            return int(getattr(self, "game_state_revision", 0))
        try:
            from .game_api import get_game_state
            state = dict(get_game_state(self))
        except Exception:
            state = {
                "page_state": str(getattr(getattr(self, "state", None), "value", "home")).lower(),
                "game_id": getattr(getattr(self, "game", None), "game_id", None),
                "question_id": self.current_question_id(),
            }
        # The central speech service owns the real audio lifecycle.  UI-local
        # callbacks must not create artificial state revisions.
        state.pop("speech", None)
        signature = repr(state)
        changed = signature != getattr(self, "_last_game_state_signature", None)
        if changed:
            self.game_state_revision = int(getattr(self, "game_state_revision", 0)) + 1
            self._last_game_state_signature = signature
        pending_prefetch = list(getattr(self, "_pending_prefetch_texts", []))
        if not changed and not pending_prefetch:
            return int(getattr(self, "game_state_revision", 0))
        event = {
            "type": "game_state",
            "source": "xingbao_touch_game",
            "session_id": getattr(self, "game_state_session_id", ""),
            "state_revision": int(getattr(self, "game_state_revision", 0)),
            "reason": str(reason or "state_changed"),
            "state": state,
            "prefetch_texts": pending_prefetch,
        }
        callback(event)
        self._pending_prefetch_texts = []
        return event["state_revision"]

    def speak(self, text, page=None, role="prompt", question_id=None):
        if role == "prompt":
            role = {
                "home": "welcome",
                "difficulty_select": "navigation",
                "game_running": "question",
                "game_feedback": "feedback",
            }.get(page, role)
        self.message = text
        self.log(EventName.XINGBAO_SPEAK, page=page, payload={"text": text})
        page_state = page or self.state.value.lower()
        game = getattr(self, "game", None)
        game_id = game.game_id if game else None
        if question_id is None and role in ("question", "read_question", "feedback"):
            question_id = self.current_question_id()
        speech_state = getattr(self, "speech_state", None)
        if not isinstance(speech_state, SpeechState):
            speech_state = SpeechState()
            self.speech_state = speech_state
        utterance_id = speech_state.begin(
            role=role,
            page_state=page_state,
            game_id=game_id,
            question_id=question_id,
            available=self.on_speech_request is not None,
        )
        if role == "feedback":
            self.feedback_utterance_id = utterance_id
            self.feedback_speech_done = self.on_speech_request is None
        state_revision = self._publish_game_state("speech:{}".format(role))
        if self.on_speech_request:
            self.on_speech_request({
                "type": "speech_request",
                "text": text,
                "page": page_state,
                "page_state": page_state,
                "game_id": game_id,
                "question_id": question_id,
                "utterance_id": utterance_id,
                "speech_sequence": speech_state.sequence,
                "state_revision": state_revision,
                "speech_role": role,
                "interrupt": True,
                "replace_pending": True,
                "wait_for_finish": True,
                "completion_timeout_seconds": 30.0,
                "retry_count": 1,
                "on_status": self._handle_speech_status,
                "source": "xingbao_touch_game",
            })
        return utterance_id

    def _handle_speech_status(self, status):
        payload = status.get("payload") if isinstance(status, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        utterance_id = payload.get("utterance_id")
        if utterance_id != self.speech_state.get("utterance_id"):
            if utterance_id == self.feedback_utterance_id:
                self.feedback_speech_done = payload.get("status") in (
                    "finished",
                    "failed",
                    "cancelled",
                )
            return
        self.speech_state.apply_status(status)
        self._publish_game_state("speech_status")
        if utterance_id == self.feedback_utterance_id:
            self.feedback_speech_done = self.speech_state.is_terminal

    def show_state(self, mood, page=None):
        self.mood = mood
        animation_state = {
            "normal": IDLE, "thinking": THINKING, "happy": HAPPY,
            "encourage": ENCOURAGE, "celebrate": CELEBRATE,
        }.get(mood, IDLE)
        self.xingbao_animator.set_state(animation_state)
        self.log(EventName.XINGBAO_SHOW_STATE, page=page, payload={"state": mood})
        self._publish_game_state("screen:{}".format(page or self.state.value.lower()))

    def make_game(self, game_id, demo=False):
        difficulty = 1 if demo else self.selected_difficulty
        if game_id == "color":  return ColorGame(rounds=1 if demo else 5, difficulty=difficulty)
        if game_id == "shape":  return ShapeGame(rounds=1 if demo else 5, difficulty=difficulty)
        if game_id == "memory":
            return MemoryPathGame(sequence_lengths=[2] if demo else None, demo_timing=demo,
                                  timing=self.demo_timing if demo else None, difficulty=difficulty)
        if game_id == "counting": return CountingGame(rounds=1 if demo else 5, difficulty=difficulty)
        if game_id == "english": return EnglishGame(rounds=1 if demo else 5, difficulty=difficulty)
        if game_id == "skill": return SkillGame(rounds=1 if demo else 5, difficulty=difficulty)
        raise ValueError("unknown game_id: {}".format(game_id))

    def open_difficulty_select(self, game_id):
        if game_id not in GAME_META:
            return
        self.pending_game_id = game_id
        self.state = AppState.DIFFICULTY_SELECT
        self.speak("请选择低、中或高难度。", page="difficulty_select")
        self.show_state("thinking", page="difficulty_select")

    def start_game(self, game_id, difficulty=None):
        if difficulty is not None:
            self.selected_difficulty = max(1, min(3, int(difficulty)))
        self.last_difficulty = self.selected_difficulty
        self.voice_paused = False
        self.game = self.make_game(game_id)
        self._queue_prompt_prefetch(self._game_prompt())
        self.last_game_id = game_id
        self.last_summary = None
        self._summary_recorded = False
        self.wait_elapsed = 0.0
        self.feedback_remaining = 0.0
        self.feedback_wait_remaining = 0.0
        self.feedback_utterance_id = None
        self.feedback_speech_done = True
        self.feedback_question_id = None
        self.feedback_question_prompt = ""
        self.feedback_question_state = {}
        self.first_mistake_support.reset(game_id)
        self.active_support_sequence = None
        self.growth_support_phase = ""
        self.growth_high_five_remaining = 0.0
        self.growth_support_wait_remaining = 0.0
        self.hint_after_seconds = self.records.hint_delay_seconds
        self.focus_shields_remaining = self.records.focus_shield_level
        self.current_score = 100
        self.current_game_elapsed = 0.0
        self.magic_potion_active = self.records.consume_magic_potion()
        if self.magic_potion_active:
            self.autosave.mark_dirty()
        self.state = AppState.GAME_RUNNING
        self.log(EventName.CHILD_TOUCHED_GAME, page="home", payload={"game_id": game_id})
        self.log(EventName.CHILD_SELECTED_DIFFICULTY, page="difficulty_select",
                 payload={"game_id": game_id, "difficulty": self.selected_difficulty,
                          "option_count": (2, 4, 6)[self.selected_difficulty - 1]})
        self.log(EventName.XINGBAO_START_GAME, page="game_running",
                 payload={"game_id": game_id,
                          "magic_potion_active": self.magic_potion_active,
                          "focus_shields": self.focus_shields_remaining,
                          "starting_score": self.current_score})
        self.show_state("normal", page="game_running")
        self.speak(self._game_prompt(), page="game_running")

    def _game_prompt(self):
        if not self.game: return "我们一起试试看。"
        gid = self.game.game_id
        if gid in ("color", "shape"):
            label = next(i["label"] for i in self.game.all_items if i["id"] == self.game.target_id)
            return "请找到{}在哪里。".format(label)
        if gid == "counting": return "数一数有几颗星星，再选择数字。"
        if gid == "english": return self.game.question
        if gid == "skill": return self.game.instruction
        if self.game.phase == "showing": return "留心每一颗星星哦。"
        return "轮到你啦，慢慢来。"

    def read_current_question(self):
        if self.state not in (AppState.GAME_RUNNING, AppState.GAME_FEEDBACK):
            return False
        if not self.game or self.game.is_finished():
            return False
        if self.state == AppState.GAME_FEEDBACK and self.feedback_question_prompt:
            prompt = self.feedback_question_prompt
            question_id = self.feedback_question_id
        else:
            prompt = self._game_prompt()
            question_id = self.current_question_id()
        self.speak(
            prompt,
            page="game_running",
            role="read_question",
            question_id=question_id,
        )
        self.show_state("thinking", page="game_running")
        return True

    def _feedback_speech(self, result):
        sequence = getattr(self, "active_support_sequence", None)
        if sequence is not None:
            if sequence.kind == "first_mistake" and not result.correct:
                return sequence.invitation_text
            if sequence.kind == "retry_success" and result.correct:
                return sequence.success_text
        if self.game and self.game.game_id == "shape" and not result.correct:
            return "{} {}".format(result.message, self._game_prompt())
        return result.message

    def select_game_item(self, selected):
        if self.state != AppState.GAME_RUNNING or not self.game or self.game.is_finished():
            return None
        selected = str(selected)
        answered_question_id = self.current_question_id()
        answered_question_prompt = self._game_prompt()
        from .game_api import get_game_state
        answered_question_state = get_game_state(self)
        valid_choices = {item["id"] for item in getattr(self.game, "options", [])}
        target = str(self.game.target_id)
        shieldable = (
            self.focus_shields_remaining > 0
            and selected != target
            and (self.game.game_id == "memory" or selected in valid_choices)
            and not (self.game.game_id == "memory" and self.game.phase != "input")
            and not (
                self.game.game_id == "shape"
                and not self.first_mistake_support.used
            )
        )
        if shieldable:
            self.records.consume_focus_shield()
            self.focus_shields_remaining = self.records.focus_shield_level
            self.autosave.mark_dirty()
            result = ChoiceResult(selected, target, False, ignored=True,
                                  message="专注护盾保护了这次选择，再试一次吧。")
            event = {"color": EventName.CHILD_SELECTED_COLOR,
                     "shape": EventName.CHILD_SELECTED_SHAPE,
                     "memory": EventName.CHILD_SELECTED_SEQUENCE_ITEM,
                     "counting": EventName.CHILD_SELECTED_NUMBER,
                     "english": EventName.CHILD_SELECTED_ENGLISH,
                     "skill": EventName.CHILD_SELECTED_SKILL}[self.game.game_id]
            payload = result.to_payload()
            payload.update({"shielded": True, "shields_remaining": self.focus_shields_remaining})
            self.log(event, page="game_running", payload=payload)
            self.feedback_success = False
            self.feedback_remaining = 1.15
            self.feedback_wait_remaining = 8.0
            self.feedback_question_id = answered_question_id
            self.feedback_question_prompt = answered_question_prompt
            self.feedback_question_state = answered_question_state
            self.state = AppState.GAME_FEEDBACK
            self.speak(
                self._feedback_speech(result),
                page="game_feedback",
                question_id=answered_question_id,
            )
            self.show_state("encourage", page="game_feedback")
            self.log(EventName.XINGBAO_SHOW_FEEDBACK, page="game_feedback",
                     payload={"correct": False, "shielded": True, "message": result.message,
                              "question_prompt": self._game_prompt()
                              if self.game.game_id == "shape" else ""})
            return result
        result = self.game.handle_choice(selected)
        if result.ignored:
            if self.game.game_id == "memory" and result.message:
                self.message = result.message
            return result

        if result.correct and not result.finished:
            self._queue_prompt_prefetch(self._game_prompt())

        evt = {"color": EventName.CHILD_SELECTED_COLOR,
               "shape": EventName.CHILD_SELECTED_SHAPE,
               "memory": EventName.CHILD_SELECTED_SEQUENCE_ITEM,
               "counting": EventName.CHILD_SELECTED_NUMBER,
               "english": EventName.CHILD_SELECTED_ENGLISH,
               "skill": EventName.CHILD_SELECTED_SKILL}
        score_penalty = 0
        if not result.ignored and not result.correct:
            score_penalty = 15 if self.magic_potion_active else 5
            self.current_score = max(0, self.current_score - score_penalty)
            result.message = "{} 本局扣{}分，剩余{}分。".format(
                result.message, score_penalty, self.current_score)
        payload = result.to_payload()
        payload.update({"score": self.current_score, "score_penalty": score_penalty,
                        "magic_potion_active": self.magic_potion_active})
        self.log(evt[self.game.game_id], page="game_running", payload=payload)

        if self.game.game_id == "memory" and result.correct and not result.completed_round:
            self.message = "已经点了{}个，继续吧。".format(self.game.input_index)
            return result

        target_label = next(
            (
                item.get("label") or item.get("name") or target
                for item in getattr(self.game, "all_items", [])
                if item.get("id") == target
            ),
            target,
        )
        self.active_support_sequence = self.first_mistake_support.observe_answer(
            game_id=self.game.game_id,
            correct=result.correct,
            question_id=answered_question_id,
            target_id=target,
            target_label=target_label,
        )
        if (
            self.active_support_sequence is not None
            and self.active_support_sequence.kind == "first_mistake"
        ):
            self.growth_support_phase = "invitation"
            self.growth_support_wait_remaining = 12.0
        elif (
            self.active_support_sequence is not None
            and self.active_support_sequence.kind == "retry_success"
        ):
            self.growth_support_phase = ""

        self.feedback_success = result.correct
        self.feedback_remaining = 1.15
        self.feedback_wait_remaining = 8.0
        self.feedback_question_id = answered_question_id
        self.feedback_question_prompt = answered_question_prompt
        self.feedback_question_state = answered_question_state
        self.state = AppState.GAME_FEEDBACK
        self.speak(
            self._feedback_speech(result),
            page="game_feedback",
            question_id=answered_question_id,
        )
        self.show_state("happy" if result.correct else "encourage", page="game_feedback")
        self.log(EventName.XINGBAO_SHOW_FEEDBACK, page="game_feedback",
                 payload={"correct": result.correct, "message": result.message,
                          "question_prompt": self._game_prompt()
                          if self.game.game_id == "shape" and not result.correct else ""})
        return result

    def request_hint(self):
        if not self.game or self.game.is_finished(): return
        payload = self.game.request_hint()
        self.log(EventName.CHILD_REQUESTED_HINT, page="game_running", payload=payload)
        self.show_state("thinking", page="game_running")
        self.speak("慢慢看，正确答案就在这些选项里。", page="game_running")

    def finish_game(self, record=True):
        if record:
            snapshot_dir = self.autosave.save_dir / "memory_shots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = snapshot_dir / "game_{}.png".format(
                datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            try:
                pygame.image.save(self.screen, str(snapshot_path))
                self.last_game_screenshot = str(snapshot_path.resolve())
            except (OSError, pygame.error):
                self.last_game_screenshot = None
        self.last_summary = self.game.get_summary()
        self.last_summary.update({
            "performance_score": self.current_score,
            "magic_potion_active": self.magic_potion_active,
            "duration_seconds": round(self.current_game_elapsed, 1),
        })
        if self.first_mistake_support.retry_succeeded:
            self.last_summary.update({
                "accepted_hint_and_retried": True,
                "growth_note": "遇到困难后愿意接受提示并再次尝试，最终完成挑战。",
            })
        if record and not self._summary_recorded:
            self.last_summary.update(self.records.calculate_star_reward(self.last_summary))
            self.records.add_summary(self.last_summary)
            self.last_summary["experience_gained"] = self.records.last_experience_gained
            self._summary_recorded = True
        self.log(EventName.CHILD_FINISHED_GAME, page="game_summary", payload=self.last_summary)
        self.log(EventName.XINGBAO_SAVE_GROWTH_RECORD, page="game_summary", payload=self.last_summary)
        self.state = AppState.GAME_SUMMARY
        leveled = self.records.just_leveled_up
        enc = self.last_summary["encouragement"]
        if leveled:
            enc += "  星宝升级啦！LV.{} 已解锁。".format(self.records.level)
        self.last_summary["encouragement"] = enc
        self.speak(enc, page="game_summary")
        self.show_state("celebrate", page="game_summary")
        if record:
            self.autosave.mark_dirty()
            self._save_now("game_finished")

    def replay(self): self.start_game(self.last_game_id, self.last_difficulty)

    def go_home(self):
        prev = self.state
        self.voice_paused = False
        if prev != AppState.HOME:
            self.log(EventName.CHILD_RETURNED_HOME, page="home",
                     payload={"from": prev.value},
                     game_id=self.game.game_id if self.game else None)
        self.state = AppState.HOME
        self.game = None; self.buttons = []
        self.speak("选择一个任务模块，开始今天的星际探索吧。", page="home")
        self.show_state("normal", page="home")

    def show_records(self):
        self.state = AppState.TODAY_RECORD
        self.game = None
        self.confirm_clear_save = False
        self.speak("这是我们今天一起完成的小游戏。", page="today_record")
        self.show_state("happy", page="today_record")

    def show_weekly_records(self):
        self.state = AppState.WEEKLY_RECORD
        self.game = None
        self.speak("这是最近七天的学习记录。", page="weekly_record")
        self.show_state("happy", page="weekly_record")

    def show_skill_card(self):
        self.state = AppState.SKILL_CARD
        self.game = None
        self.log(EventName.SKILL_CARD_OPENED, page="skill_card",
                 payload={"experience_boost": self.records.experience_boost_level,
                          "focus_shield": self.records.focus_shield_level,
                          "magic_potion": self.records.magic_potion_count})
        self.speak("选择一项技能，查看效果和升级消耗。", page="skill_card")
        self.show_state("thinking", page="skill_card")

    def purchase_selected_skill(self):
        if self.state != AppState.SKILL_CARD:
            return
        result = self.records.upgrade_skill(self.selected_skill_id)
        if result["purchased"]:
            self.log(EventName.SKILL_UPGRADE_PURCHASED, page="skill_card", payload=result)
            self.speak("升级成功！{}".format(self._selected_skill_effect()), page="skill_card")
            self.show_state("celebrate", page="skill_card")
            self.autosave.mark_dirty()
            self._save_now("skill_upgrade")
        else:
            self.log(EventName.SKILL_UPGRADE_REJECTED, page="skill_card", payload=result)
            self.speak(result["reason"], page="skill_card")
            self.show_state("encourage", page="skill_card")

    def _selected_skill_effect(self):
        if self.selected_skill_id == "experience_boost":
            return "星运提升了，更容易获得额外星星。"
        if self.selected_skill_id == "focus_shield":
            return "护盾库存增加到{}个。".format(self.records.focus_shield_level)
        return "药水库存增加到{}瓶，下一局自动使用。".format(
            self.records.magic_potion_count)

    def request_clear_save(self):
        if self.state != AppState.TODAY_RECORD:
            return
        self.confirm_clear_save = True
        self.log(EventName.CLEAR_SAVE_REQUESTED, page="today_record",
                 payload={"path": str(self.autosave.latest_path)})

    def cancel_clear_save(self):
        self.confirm_clear_save = False
        self.log(EventName.CLEAR_SAVE_CANCELLED, page="today_record", payload={})

    def confirm_clear_save_action(self):
        self.log(EventName.CLEAR_SAVE_CONFIRMED, page="today_record",
                 payload={"path": str(self.autosave.latest_path)})
        self.records = SessionRecords()
        self.last_summary = None
        self._summary_recorded = False
        default_state = self.get_save_state()
        result = self.autosave.clear_save(default_state)
        self.confirm_clear_save = False
        self.message = "本地存档已清空"
        self.show_state("normal", page="today_record")
        self.log(EventName.AUTOSAVE_CLEARED, page="today_record",
                 payload={"path": str(self.autosave.latest_path),
                          "growth": result.get("growth", {})})

    # ── demo system (unchanged) ─────────────────────────────────

    def start_demo(self, game_id=None):
        game_id = game_id or self.pending_game_id or "color"
        if game_id not in self.demo_game_ids:
            return
        self.state = AppState.DEMO_MODE; self.game = None
        self.demo_sequence = [game_id]
        self.demo_index = 0; self.demo_view = "game"
        self.demo_show_feedback = False; self.demo_complete_after_result = False
        self.demo_step_index = 0
        self.demo_total_steps = 3 if game_id == "memory" else 2
        self.speak("开始演示{}。".format(GAME_META[game_id]["title"]), page="demo_mode")
        self.show_state("normal", page="demo_mode")
        self._start_demo_game(game_id)
        if game_id == "memory":
            self.demo_stage = "memory_playback"
            self.demo_remaining = 0.0
            self.demo_instruction = "演示：先看星星亮起的顺序"
        else:
            self._schedule_demo_action("game_choice", self.game.target_id,
                                       "演示：点击正确答案")

    def _start_demo_game(self, game_id):
        self.game = self.make_game(game_id, demo=True)
        self.last_game_id = game_id; self.demo_view = "game"
        self.demo_show_feedback = False
        self.log(EventName.XINGBAO_START_GAME, page="demo_mode", payload={"game_id": game_id, "demo": True})
        self.speak(self._game_prompt(), page="demo_mode")

    def _demo_choose(self, selected):
        result = self.game.handle_choice(str(selected))
        evt = {"color": EventName.CHILD_SELECTED_COLOR,
               "shape": EventName.CHILD_SELECTED_SHAPE,
               "memory": EventName.CHILD_SELECTED_SEQUENCE_ITEM,
               "counting": EventName.CHILD_SELECTED_NUMBER,
               "english": EventName.CHILD_SELECTED_ENGLISH,
               "skill": EventName.CHILD_SELECTED_SKILL}
        self.log(evt[self.game.game_id], page="demo_mode", payload=result.to_payload())
        return result

    def _demo_exit_rect(self, layout):
        bw = int(layout.footer_area.w * 0.66)
        return pygame.Rect(layout.footer_area.x + bw + layout.gap,
                          layout.footer_area.y,
                          layout.footer_area.w - bw - layout.gap,
                          layout.footer_area.h)

    def _demo_target_geometry(self, kind, target_id):
        layout = Layout(self.screen.get_size())
        if kind == "home_game":
            idx = self.demo_game_ids.index(target_id)
            r = layout.home_game_cards(len(self.demo_game_ids))[idx]
            return r, (r.centerx, r.y + int(r.h * 0.25))
        elif kind == "game_choice":
            _, _, oa = layout.game_regions()
            if self.game.game_id != "memory":
                oi = next(i for i, it in enumerate(self.game.options) if it["id"] == target_id)
                r = layout.grid_rects(oa, len(self.game.options), min(4, len(self.game.options)))[oi]
                return r, (r.centerx, r.y + int(r.h * 0.35))
            else:
                r = layout.grid_rects(oa, 4, 2)[int(target_id)]
                return r, r.center
        else:
            r = self._demo_exit_rect(layout)
            return r, r.center

    def _demo_target_label(self, kind, target_id):
        if kind == "home_game": return "game_{}".format(target_id)
        if kind == "game_choice": return "{}_{}".format(self.game.game_id, target_id)
        return "summary_home"

    def _demo_target_key(self, kind, target_id):
        if kind == "home_game":
            return "home.{}_card".format(target_id)
        if kind == "game_choice" and self.game:
            return "game.choice.{}.{}".format(self.game.game_id, target_id)
        return "demo.exit_button"

    @staticmethod
    def _rect_payload(rect):
        return [rect.x, rect.y, rect.w, rect.h]

    def _resolve_demo_target(self, kind, target_id):
        target_key = self._demo_target_key(kind, str(target_id))
        rect = self.ui_registry.get(target_key)
        if rect is None:
            rect, _ = self._demo_target_geometry(kind, str(target_id))
            self.ui_registry.register(target_key, rect)
        click_pos = rect.center
        self.log(EventName.DEMO_TARGET_RESOLVED, page="demo_mode",
                 payload={"target_key": target_key,
                          "rect": self._rect_payload(rect),
                          "click_pos": [click_pos[0], click_pos[1]]})
        return target_key, rect, click_pos

    def _schedule_demo_action(self, kind, target_id, instruction):
        self.demo_target_kind = kind
        self.demo_target_id = str(target_id)
        self.demo_target_name = self._demo_target_label(kind, str(target_id))
        self.demo_target_key, self.demo_target_rect, self.demo_pointer_pos = self._resolve_demo_target(
            kind, str(target_id))
        self.demo_stage = "intro"
        self.demo_remaining = self.demo_timing["page_intro"]
        self.demo_instruction = instruction
        self.demo_step_index = min(self.demo_step_index + 1, self.demo_total_steps)
        self.log(EventName.DEMO_STEP_STARTED, page="demo_mode",
                 payload={"target": self.demo_target_name, "step": self.demo_step_index,
                          "total": self.demo_total_steps, "speed": self.demo_speed})

    def _execute_demo_action(self):
        self.log(EventName.DEMO_POINTER_CLICK, page="demo_mode",
                 payload={"target_key": getattr(self, "demo_target_key", None),
                          "target": self.demo_target_name,
                          "rect": self._rect_payload(self.demo_target_rect),
                          "click_pos": [self.demo_pointer_pos[0], self.demo_pointer_pos[1]]})
        if self.demo_target_kind == "home_game":
            self._start_demo_game(self.demo_target_id)
        elif self.demo_target_kind == "game_choice":
            result = self._demo_choose(self.demo_target_id)
            self.feedback_success = result.correct
            self.demo_show_feedback = True
            self.message = result.message
            self.mood = "happy" if result.correct else "thinking"
        else:
            self.demo_view = "home"; self.game = None
            self.demo_show_feedback = False
            self.demo_complete_after_result = True
            self.message = "演示完成，回到主控台。"
            self.mood = "normal"
        self.log(EventName.DEMO_STEP_FINISHED, page="demo_mode",
                 payload={"target_key": getattr(self, "demo_target_key", None),
                          "target": self.demo_target_name,
                          "rect": self._rect_payload(self.demo_target_rect),
                          "click_pos": [self.demo_pointer_pos[0], self.demo_pointer_pos[1]],
                          "step": "result"})

    def _prepare_demo_summary(self):
        self.last_summary = self.game.get_summary()
        self.log(EventName.CHILD_FINISHED_GAME, page="demo_mode", payload=self.last_summary)
        self.log(EventName.XINGBAO_SAVE_GROWTH_RECORD, page="demo_mode", payload=self.last_summary)
        self.demo_view = "summary"; self.demo_show_feedback = False
        self.message = self.last_summary["encouragement"]; self.mood = "happy"

    def _after_demo_result(self):
        if self.demo_complete_after_result:
            self.demo_complete_after_result = False; self.go_home(); return
        if self.demo_target_kind == "home_game":
            if self.game.game_id == "memory":
                self.demo_stage = "memory_playback"; self.demo_remaining = 0.0
                self.demo_instruction = "演示：先看星星亮起的顺序"
            else:
                self._schedule_demo_action("game_choice", self.game.target_id,
                    "演示：点击正确答案")
            return
        if self.demo_target_kind == "game_choice":
            if self.game.game_id == "memory":
                if not self.game.is_finished():
                    self.demo_show_feedback = False
                    nxt = self.game.current_sequence[self.game.input_index]
                    self._schedule_demo_action("game_choice", nxt, "演示：按顺序点击下一个圆点")
                    return
            self._prepare_demo_summary()
            self._schedule_demo_action("summary_home", "home", "演示：点击返回主控台")

    def _update_demo(self, dt):
        if self.demo_stage == "memory_playback":
            self.game.update(self._visible_game_dt(dt))
            if self.game.phase == "input":
                tgt = self.game.current_sequence[self.game.input_index]
                self._schedule_demo_action("game_choice", tgt, "演示：按亮起顺序点击圆点")
            return
        self.demo_remaining -= dt
        if self.demo_remaining > 0: return
        if self.demo_stage == "intro":
            self.demo_stage = "move"
            self.demo_remaining = self.demo_timing["pointer_move"]
            self.log(EventName.DEMO_POINTER_MOVE, page="demo_mode",
                     payload={"target_key": getattr(self, "demo_target_key", None),
                              "target": self.demo_target_name,
                              "rect": self._rect_payload(self.demo_target_rect),
                              "click_pos": [self.demo_pointer_pos[0], self.demo_pointer_pos[1]],
                              "step": "move"})
        elif self.demo_stage == "move":
            self.demo_stage = "press"; self.demo_remaining = DEMO_PRESS_DURATION
            self.demo_remaining = self.demo_timing["pointer_press"]
            self.demo_target_key, self.demo_target_rect, self.demo_pointer_pos = self._resolve_demo_target(
                self.demo_target_kind, self.demo_target_id)
            self.log(EventName.DEMO_POINTER_PRESS, page="demo_mode",
                     payload={"target_key": getattr(self, "demo_target_key", None),
                              "target": self.demo_target_name,
                              "rect": self._rect_payload(self.demo_target_rect),
                              "click_pos": [self.demo_pointer_pos[0], self.demo_pointer_pos[1]],
                              "step": "press"})
        elif self.demo_stage == "press":
            self._execute_demo_action()
            self.demo_stage = "result"
            if self.demo_target_kind == "game_choice":
                self.demo_remaining = self.demo_timing["feedback_hold"]
            elif self.demo_target_kind == "summary_home":
                self.demo_remaining = self.demo_timing["summary_hold"]
            else:
                self.demo_remaining = self.demo_timing["after_click"]
            self.demo_instruction = "演示：查看点击结果"
        elif self.demo_stage == "result":
            self.demo_stage = "between"
            self.demo_remaining = self.demo_timing["between_steps"]
            self.demo_instruction = "演示：准备下一步"
        elif self.demo_stage == "between":
            self._after_demo_result()

    # ── main loop ──────────────────────────────────────────────

    def update(self, dt=None):
        dt = 1.0 / 30.0 if dt is None else max(0.0, float(dt))
        self.effect_time += dt
        self.xingbao_animator.update(dt)
        if (
            self.state in (AppState.GAME_RUNNING, AppState.GAME_FEEDBACK)
            and self.game
            and not self.voice_paused
        ):
            self.current_game_elapsed += dt
        if self.autosave.update(dt, self.get_save_state()):
            self.log(EventName.AUTOSAVE_SAVED, page=self.state.value.lower(),
                     payload={"reason": "interval", "path": str(self.autosave.latest_path)})
        if self.voice_paused and self.state in (AppState.GAME_RUNNING, AppState.GAME_FEEDBACK):
            return
        if self.state == AppState.GAME_RUNNING and self.game:
            self.game.update(self._visible_game_dt(dt))
            if self.game.game_id != "memory":
                self.wait_elapsed += dt
                if self.wait_elapsed >= self.hint_after_seconds:
                    self.wait_elapsed = 0.0; self.request_hint()
        elif self.state == AppState.GAME_FEEDBACK:
            if self._update_first_mistake_support(dt):
                return
            self.feedback_remaining -= dt
            self.feedback_wait_remaining -= dt
            if (
                self.feedback_remaining <= 0
                and (self.feedback_speech_done or self.feedback_wait_remaining <= 0)
            ):
                if self.game.is_finished():
                    self.finish_game()
                else:
                    self.state = AppState.GAME_RUNNING; self.wait_elapsed = 0.0
                    self.log(EventName.XINGBAO_START_NEXT_ROUND, page="game_running",
                             payload={"round": self.game.current_round_number})
                    self.speak(self._game_prompt(), page="game_running")
                    self.show_state("normal", page="game_running")
        elif self.state == AppState.DEMO_MODE:
            self._update_demo(dt)

    def _visible_game_dt(self, dt):
        if (
            self.game
            and self.game.game_id == "memory"
            and getattr(self.game, "phase", None) == "showing"
        ):
            return min(float(dt), MEMORY_VISIBLE_UPDATE_STEP)
        return dt

    def _update_first_mistake_support(self, dt):
        """Hold the same question through invitation, high-five, and retry."""
        phase = str(getattr(self, "growth_support_phase", "") or "")
        sequence = getattr(self, "active_support_sequence", None)
        if not phase or sequence is None or sequence.kind != "first_mistake":
            return False

        self.growth_support_wait_remaining = max(
            0.0,
            float(getattr(self, "growth_support_wait_remaining", 0.0)) - dt,
        )
        if phase == "invitation":
            if self.feedback_speech_done or self.growth_support_wait_remaining <= 0:
                self.first_mistake_support.start_high_five()
                self.growth_support_phase = "high_five"
                self.growth_high_five_remaining = sequence.high_five_hold_seconds
                self._publish_game_state("companion_support:high_five_requested")
            return True

        if phase == "high_five":
            self.growth_high_five_remaining -= dt
            if self.growth_high_five_remaining <= 0:
                self.first_mistake_support.start_retry_prompt()
                self.growth_support_phase = "retry_prompt"
                self.growth_support_wait_remaining = 12.0
                self.feedback_speech_done = self.on_speech_request is None
                self.speak(
                    sequence.retry_text,
                    page="game_feedback",
                    role="feedback",
                    question_id=sequence.question_id,
                )
                self._publish_game_state("companion_support:retry_prompt")
            return True

        if phase == "retry_prompt":
            if self.feedback_speech_done or self.growth_support_wait_remaining <= 0:
                self.first_mistake_support.finish_retry_prompt()
                self.growth_support_phase = ""
                self.active_support_sequence = None
                self.state = AppState.GAME_RUNNING
                self.wait_elapsed = 0.0
                self.show_state("normal", page="game_running")
            return True

        return False

    def activate_display(self, fullscreen=None, size=None):
        """Reuse preloaded assets while switching back from the desktop scene."""
        if fullscreen is not None:
            self.fullscreen = bool(fullscreen)
        size = tuple(size or self.screen.get_size())
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        flags |= getattr(pygame, "SHOWN", 0)
        self.screen = pygame.display.set_mode((0, 0) if self.fullscreen else size, flags)
        pygame.display.set_caption("星宝游戏乐园")
        self.clock = pygame.time.Clock()
        sc = 45 if self.low_effects else 110
        self.stars = init_starfield(self.screen.get_width(), self.screen.get_height(), count=sc, seed=27)
        self.particles = self.stars
        self.running = True
        self.state = AppState.HOME
        self.game = None
        self.buttons = []
        self._exit_saved = False
        self.message = "选择一个任务模块，开始今天的星际探索吧。"

        self.speak(self.message, page="home", role="welcome")
        self.show_state("normal", page="home")

    def show_first_frame(self):
        """Force the newly activated game window onto the physical display."""
        self.render()
        pygame.display.flip()
        pygame.event.pump()

    def run(self, quit_pygame=True):
        from .board_adapter import runtime
        self.active = True
        last_render_ms = 0
        while self.running:
            runtime.pump()
            dt = self.clock.tick(self.event_fps) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT: self.stop()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if self.state == AppState.HOME: self.stop()
                    else: self.go_home()
                elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                    sc = 45 if self.low_effects else 110
                    self.stars = init_starfield(event.size[0], event.size[1], count=sc, seed=27)
                    self.particles = self.stars
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.handle_touch(event.pos, source="mouse")
                elif event.type == pygame.FINGERUP:
                    w, h = self.screen.get_size()
                    self.handle_touch((int(event.x * w), int(event.y * h)), source="finger")
            if not self.running: break
            self.update(dt)
            now_ms = pygame.time.get_ticks()
            render_interval_ms = max(1, int(1000 / self.target_fps))
            if now_ms - last_render_ms >= render_interval_ms:
                self.render()
                pygame.display.flip()
                last_render_ms = now_ms
        if quit_pygame:
            pygame.quit()
        self.active = False

    def _is_duplicate_touch_release(self, pos, source, timestamp_ms=None):
        """Return True for a mouse/finger pair created by one physical tap."""
        now = pygame.time.get_ticks() if timestamp_ms is None else int(timestamp_ms)
        pos = (int(pos[0]), int(pos[1]))
        previous = self._last_touch_release
        self._last_touch_release = (pos, source, now)
        if previous is None:
            return False

        previous_pos, previous_source, previous_time = previous
        dx = pos[0] - previous_pos[0]
        dy = pos[1] - previous_pos[1]
        return (
            source != previous_source
            and 0 <= now - previous_time <= TOUCH_DUPLICATE_WINDOW_MS
            and dx * dx + dy * dy <= TOUCH_DUPLICATE_DISTANCE_PX ** 2
        )

    def handle_touch(self, pos, source="mouse", timestamp_ms=None):
        if self._is_duplicate_touch_release(pos, source, timestamp_ms):
            return
        layout = Layout(self.screen.get_size())
        if self.state != AppState.HOME and layout.corner_button().collidepoint(pos):
            self.go_home()
            return
        for btn in self.buttons:
            if btn.contains(pos):
                self.handle_button(btn.event_key)
                return

    def get_click_targets(self):
        return {key: rect for key, rect in self.ui_registry.items()}

    def handle_button(self, key):
        if key.startswith("game:"):
            self.open_difficulty_select(key.split(":", 1)[1])
        elif key.startswith("difficulty:") and self.pending_game_id:
            self.start_game(self.pending_game_id, int(key.split(":", 1)[1]))
        elif key == "demo_current" and self.pending_game_id:
            self.start_demo(self.pending_game_id)
        elif key.startswith("skill_select:"):
            skill_id = key.split(":", 1)[1]
            if skill_id in SKILL_MAX_LEVELS:
                self.selected_skill_id = skill_id
        elif key.startswith("choice:"):
            self.select_game_item(key.split(":", 1)[1])
        else:
            actions = {"home": self.go_home, "records": self.show_records,
                       "weekly_records": self.show_weekly_records,
                       "exit_demo": self.go_home,
                       "replay": self.replay, "hint": self.request_hint,
                       "read_question": self.read_current_question, "exit": self.stop,
                       "skill_card": self.show_skill_card,
                       "skill_upgrade": self.purchase_selected_skill,
                       "clear_save_request": self.request_clear_save,
                       "clear_save_cancel": self.cancel_clear_save,
                       "clear_save_confirm": self.confirm_clear_save_action}
            act = actions.get(key)
            if act: act()

    def stop(self):
        if not self._exit_saved:
            self._save_now("exit")
            self._exit_saved = True
        self.running = False; self.state = AppState.EXIT

    def get_save_state(self):
        state = self.records.to_dict()
        state.update({
            "session_id": self.logger.session_id,
            "settings": {"demo_speed": self.demo_speed},
        })
        return state

    def _save_now(self, reason):
        path = self.autosave.save_now(self.get_save_state(), reason=reason)
        if path is not None:
            self.log(EventName.AUTOSAVE_SAVED, page=self.state.value.lower(),
                     payload={"reason": reason, "path": str(path)})
            return True
        self.log(EventName.AUTOSAVE_FAILED, page=self.state.value.lower(),
                 payload={"reason": reason, "error": self.autosave.last_error or "unknown"})
        return False

    def _load_assets(self):
        """Pre-load or fallback-render all assets."""
        self.bg_image = self.assets.optional_image("bg_stage", size=None) or self.assets.optional_image("bg_main", size=None)
        self.page_backgrounds = {
            "home": self.assets.optional_image("bg_stage", size=None) or self.assets.optional_image("bg_home", size=None),
            "game": self.assets.optional_image("bg_stage", size=None) or self.assets.optional_image("bg_game", size=None),
            "report": self.assets.optional_image("bg_stage", size=None) or self.assets.optional_image("bg_report", size=None),
        }
        self.xingbao_images = {}
        for state in ("normal", "happy", "thinking", "encouraging"):
            self.xingbao_images[state] = self.assets.optional_image("xingbao_{}".format(state), size=None)
        self.xingbao_images["encourage"] = self.xingbao_images.get("encouraging") or self.xingbao_images.get("normal")
        self.xingbao_images["celebrate"] = self.xingbao_images.get("happy") or self.xingbao_images.get("normal")
        self.icon_images = {
            "color": self.assets.optional_image("icon_color_energy") or self.assets.optional_image("icon_color"),
            "shape": self.assets.optional_image("icon_geometry_signal") or self.assets.optional_image("icon_geometry"),
            "memory": self.assets.optional_image("icon_memory_route") or self.assets.optional_image("icon_memory"),
            "counting": self.assets.optional_image("icon_counting_planet"),
            "english": self.assets.optional_image("icon_english_words") or self.assets.optional_image("icon_habit_match"),
            "skill": self.assets.optional_image("icon_skill_focus"),
            "star_reward": self.assets.optional_image("icon_star_reward") or self.assets.optional_image("icon_star"),
            "energy_core": self.assets.optional_image("icon_energy_core") or self.assets.optional_image("icon_energy"),
        }
        self.shape_icons = {}
        for sid in ("circle", "square", "triangle", "star", "heart", "rectangle", "ellipse"):
            self.shape_icons[sid] = self.assets.optional_image("shape_{}".format(sid), size=None)
        self.system_images = {
            "back": self.assets.optional_image("back_arrow") or self.assets.optional_image("icon_back"),
            "pointer": self.assets.optional_image("icon_touch"),
            "report": self.assets.optional_image("icon_report"),
        }
        self.panel_images = {
            "glass": self.assets.optional_image("panel_companion") or self.assets.optional_image("panel_glass"),
            "glass_active": self.assets.optional_image("panel_glass_active"),
            "mission": self.assets.optional_image("panel_mission_card") or self.assets.optional_image("mission_card"),
            "mission_active": self.assets.optional_image("card_state_selected") or self.assets.optional_image("mission_card_active"),
            "task": self.assets.optional_image("panel_top_task"),
            "feedback": self.assets.optional_image("panel_feedback"),
            "card_normal": self.assets.optional_image("card_state_normal"),
            "card_hover": self.assets.optional_image("card_state_hover"),
            "card_selected": self.assets.optional_image("card_state_selected"),
            "button_primary": self.assets.optional_image("button_primary"),
            "button_secondary": self.assets.optional_image("button_secondary"),
        }
        self.feedback_images = {
            "success": self.assets.optional_image("feedback_success"),
            "info": self.assets.optional_image("feedback_info"),
            "warning": self.assets.optional_image("feedback_warning"),
            "status_bar": self.assets.optional_image("reward_status_bar"),
        }
        self.chip_images = {
            "local": self.assets.optional_image("chip_local"),
            "touch": self.assets.optional_image("chip_touch"),
            "safe": self.assets.optional_image("chip_safe"),
            "ready": self.assets.optional_image("chip_ready"),
            "select": self.assets.optional_image("select_blue"),
        }
        self.color_orbs = {}
        for cid in ("red", "yellow", "blue", "green", "purple", "orange"):
            self.color_orbs[cid] = self.assets.optional_image("energy_{}".format(cid), size=None) or self.assets.optional_image("color_{}".format(cid), size=None)

    def _current_background(self):
        if self.state == AppState.DEMO_MODE:
            key = "home" if self.demo_view == "home" else (
                "report" if self.demo_view == "summary" else "game")
        elif self.state == AppState.HOME:
            key = "home"
        elif self.state in (AppState.GAME_SUMMARY, AppState.TODAY_RECORD,
                            AppState.WEEKLY_RECORD, AppState.SKILL_CARD):
            key = "report"
        else:
            key = "game"
        return self.page_backgrounds.get(key) or self.bg_image

    # ═══════════════════════════════════════════════════════════
    #  RENDER  (v6.1 clean — all text via FontManager, no text PNGs)
    # ═══════════════════════════════════════════════════════════

    def render(self):
        # Background
        background = self._current_background()
        if background:
            blit_cover(self.screen, background, self.screen.get_rect())
            veil = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            veil.fill((3, 12, 34, 86))
            self.screen.blit(veil, (0, 0))
        else:
            from .effects import draw_space_background
            draw_space_background(self.screen, self.effect_time)

        # Dynamic overlays
        draw_hud_grid(self.screen, self.effect_time)
        draw_starfield(self.screen, self.stars, self.effect_time)
        if self.scanline_enabled:
            draw_scanline(self.screen, self.effect_time)
        self.buttons = []
        self.ui_registry.clear_page()
        layout = Layout(self.screen.get_size())
        self._draw_top_bar(layout)
        if self.state == AppState.HOME:          self._render_home()
        elif self.state == AppState.DIFFICULTY_SELECT: self._render_difficulty_select()
        elif self.state in (AppState.GAME_RUNNING, AppState.GAME_FEEDBACK):
            self._render_game(interactive=self.state == AppState.GAME_RUNNING)
        elif self.state == AppState.GAME_SUMMARY: self._render_summary()
        elif self.state == AppState.TODAY_RECORD: self._render_records()
        elif self.state == AppState.WEEKLY_RECORD: self._render_weekly_records()
        elif self.state == AppState.SKILL_CARD: self._render_skill_card()
        elif self.state == AppState.DEMO_MODE:    self._render_demo()
        self._render_corner_button()
        if self.debug_layout:
            draw_debug_overlay(self.screen, self.ui_registry)

    # ── top bar ─────────────────────────────────────────────────

    def _draw_top_bar(self, layout):
        """Show a child-readable product label and live speech state."""
        y = layout.safe_area.y + 4

        draw_text(self.screen, "星宝游戏乐园",
                  (layout.safe_area.x + 2, y),
                  size=layout.font(16), color=(132, 150, 198))

        # Keep playback state internally for sequencing and accessibility, but
        # do not expose transient "playing" / "finished" text in the game's
        # upper-right corner.

    def _speech_status_label(self):
        status = str((getattr(self, "speech_state", {}) or {}).get("status") or "idle")
        if status == "queued":
            return "正在播放语音…", theme.STAR_GOLD
        if status == "finished":
            return "语音播放完成", theme.SUCCESS
        if status == "failed":
            return "语音暂时不可用，请点“读题”", theme.WARNING
        if status == "unavailable":
            return "语音未连接，可继续触屏游戏", theme.WARNING
        return "触屏已准备好", theme.SUCCESS

    # ── title ───────────────────────────────────────────────────

    def _draw_title(self, layout, title, subtitle=None, progress=None):
        """Draw page title via FontManager. No text PNGs."""
        title_size = min(42, layout.font(theme.F_TITLE))
        title_font = fit_font(title, title_size, layout.title_area.w - 320, bold=True)
        title_surface = title_font.render(title, True, theme.TEXT_MAIN)
        title_rect = title_surface.get_rect(midtop=(layout.title_area.centerx, layout.title_area.y + 4))
        self.screen.blit(title_surface, title_rect)

        if subtitle:
            sub_size = max(16, layout.font(theme.F_SMALL) - 1)
            sub_font = fit_font(subtitle, sub_size, layout.title_area.w - 320)
            sub_surface = sub_font.render(subtitle, True, theme.TEXT_SUB)
            sub_rect = sub_surface.get_rect(midtop=(layout.title_area.centerx, title_rect.bottom + 2))
            self.screen.blit(sub_surface, sub_rect)

        if progress:
            draw_text(self.screen, progress,
                      (layout.title_area.x + 10, layout.title_area.y + 22),
                      size=layout.font(theme.F_SMALL), color=theme.ELECTRIC, bold=True)

    # ── companion panel ─────────────────────────────────────────

    def _companion_panel(self, rect, mood=None, hint_text=None, title="星宝伙伴"):
        avatar = self.xingbao_images.get(mood or self.mood)
        avatar = self.xingbao_animator.render(avatar)
        return CompanionPanel(
            rect,
            title=title,
            hint_text=self.message if hint_text is None else hint_text,
            level=self.records.level,
            energy=self.records.energy,
            energy_max=self.records.energy_max,
            level_title=self.records.level_title,
            is_max_level=self.records.level >= 100,
            star_count=self.records.star_count,
            avatar_image=avatar,
            panel_image=self.panel_images["glass"],
            reward_image=self.icon_images["star_reward"],
            status_bar_image=self.feedback_images["status_bar"],
            chip_images=(None, None, None),
            chip_labels=tuple(chip["label"] for chip in self.system_status.get_chip_states()),
            skill_level=self.records.experience_boost_level,
            skill_bonus=self.records.experience_bonus_percent,
            skill_max_level=MAX_SKILL_LEVEL,
            skill_summary="星运{} · 盾{} · 药{}".format(
                self.records.experience_boost_level,
                self.records.focus_shield_level,
                self.records.magic_potion_count),
        )

    # ═══════════════════════════════════════════════════════════
    #  HOME  (clean — single title set per card, no text PNG overlays)
    # ═══════════════════════════════════════════════════════════

    def _render_home(self, interactive=True, show_footer=True):
        layout = Layout(self.screen.get_size())
        self._draw_title(layout, "星宝游戏乐园", "听一听 · 点一点 · 玩中学")
        char = layout.home_character_area()
        companion = self._companion_panel(
            char, hint_text="选一个喜欢的游戏，和星宝一起玩吧！")
        companion.draw(self.screen)
        self.ui_registry.register("home.skill_card", companion.skill_card_rect)
        if interactive:
            self.buttons.append(Button(companion.skill_card_rect, "", event_key="skill_card"))

        # Game tiles — single title + single description via FontManager, no PNG
        game_ids = tuple(self.demo_game_ids)
        cards = layout.home_game_cards(len(game_ids))
        difficulty = "轻松 / 认真 / 挑战"
        for idx, (rect, gid) in enumerate(zip(cards, game_ids)):
            meta = GAME_META[gid]
            tile = GameTile(rect, idx + 1, meta["title"], meta["desc"],
                           meta["bg"], "game:" + gid, meta["icon"],
                           image=self.icon_images.get(gid),
                           card_image=self.panel_images["mission"],
                           active_card_image=self.panel_images["mission_active"],
                           difficulty=difficulty)
            tile.selected = (
                self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                and self.demo_target_kind == "home_game" and self.demo_target_id == gid)
            tile.draw(self.screen)
            self.ui_registry.register("home.{}_card".format(gid), rect)
            if interactive: self.buttons.append(tile)

        # Footer buttons — FontManager only
        if show_footer:
            frs = layout.footer_buttons(3)
            items = (
                ("近七日记录", "weekly_records", theme.PANEL_GLASS, theme.CRYSTAL),
                ("今日记录", "records", theme.PANEL_GLASS, theme.SUCCESS),
                ("返回桌面", "exit", theme.PANEL_GLASS, theme.WARNING),
            )
            for r, (label, key, bg, bd) in zip(frs, items):
                btn = Button(
                    r, label, bg=bg, fg=theme.TEXT_MAIN, event_key=key, border=bd,
                    image=self.panel_images["button_primary"] if key != "exit" else self.panel_images["button_secondary"],
                    active_image=self.panel_images["button_primary"] if key != "exit" else self.panel_images["button_secondary"],
                )
                btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
                self.ui_registry.register("home.{}_button".format(key), r)
                if interactive: self.buttons.append(btn)

    # ═══════════════════════════════════════════════════════════
    #  GAME  (clean — FontManager for all text)
    # ═══════════════════════════════════════════════════════════

    def _render_difficulty_select(self):
        layout = Layout(self.screen.get_size())
        meta = GAME_META.get(self.pending_game_id, {"title": "小游戏"})
        self._draw_title(layout, "想怎么玩？", "{} · 每一局都可以重新选".format(meta["title"]))
        char = layout.home_character_area()
        is_memory = self.pending_game_id == "memory"
        hint = ("轻松玩有2个点，认真想有3个点，勇敢挑战有4个点。" if is_memory else
                "轻松玩有2个选项，认真想有4个，勇敢挑战有6个。")
        self._companion_panel(char, hint_text=hint,
                              title="星宝建议").draw(self.screen)
        area = layout.home_cards_area()
        colors = (theme.SUCCESS, theme.ELECTRIC, theme.STAR_GOLD)
        if is_memory:
            subtitles = ("2个点 · 先试一试", "3个点 · 多想一想", "4个点 · 挑战自己")
        else:
            subtitles = ("2个选项 · 先试一试", "4个选项 · 多想一想", "6个选项 · 挑战自己")
        for rect, item, color, subtitle in zip(
                layout.grid_rects(area, 3, 3), PLAYER_DIFFICULTIES, colors, subtitles):
            btn = Button(rect, item["name"], subtitle=subtitle,
                         event_key="difficulty:{}".format(item["id"]), border=color)
            btn.draw(self.screen, get_font(layout.font(28), bold=True))
            self.ui_registry.register("difficulty.{}".format(item["id"]), rect)
            self.buttons.append(btn)
        demo_rect = layout.footer_buttons(1)[0]
        demo_btn = Button(demo_rect, "先看看怎么玩", event_key="demo_current",
                          border=theme.CRYSTAL,
                          image=self.panel_images["button_primary"],
                          active_image=self.panel_images["button_primary"])
        demo_btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        self.ui_registry.register("difficulty.demo_current", demo_rect)
        self.buttons.append(demo_btn)

    def _render_game(self, interactive=True):
        layout = Layout(self.screen.get_size())
        difficulty_name = PLAYER_DIFFICULTIES[max(1, min(3, self.game.difficulty)) - 1]["name"]
        potion_status = " · 药水×2" if self.magic_potion_active else ""
        progress = "{} · 得分{}{} · 第{}轮 / 共{}轮".format(
            difficulty_name, self.current_score, potion_status,
            self.game.current_round_number, self.game.rounds)
        self._draw_title(layout, self.game.title, progress=progress)
        char = layout.home_character_area()
        right = layout.home_cards_area()
        task_h = max(120, int(right.h * 0.28))
        task = pygame.Rect(right.x, right.y, right.w, task_h)
        options = pygame.Rect(right.x, task.bottom + layout.gap,
                              right.w, right.bottom - task.bottom - layout.gap)

        self._companion_panel(char, hint_text="").draw(self.screen)

        # Task panel or feedback
        if self.state == AppState.GAME_FEEDBACK or (
            self.state == AppState.DEMO_MODE and self.demo_show_feedback):
            FeedbackPanel(
                task, self.message, success=self.feedback_success,
                decoration=self.feedback_images["success" if self.feedback_success else "warning"],
            ).draw(
                self.screen, layout.font(theme.F_BODY))
        else:
            if self.panel_images["task"] is not None:
                self.assets.draw_cover(self.screen, self.panel_images["task"], task, alpha=220)
            draw_glass_panel(self.screen, task, border=theme.ELECTRIC, radius=10, glow=7)
            task_text = self._task_text()
            # Instruction text — FontManager only
            tr = pygame.Rect(task.x + 24, task.y + 10, task.w - 48, task.h - 20)
            draw_wrapped_text(self.screen, task_text, tr,
                              size=layout.font(theme.F_SUBTITLE), bold=True,
                              align="center", valign="center")

        # Options
        if self.game.game_id == "color":
            self._render_color_options(layout, options, interactive)
        elif self.game.game_id == "shape":
            self._render_shape_options(layout, options, interactive)
        elif self.game.game_id == "memory":
            self._render_memory_options(layout, options, interactive)
        elif self.game.game_id == "counting":
            self._render_counting_options(layout, options, interactive)
        elif self.game.game_id == "english":
            self._render_english_options(layout, options, interactive)
        else:
            self._render_skill_options(layout, options, interactive)

        if not interactive:
            disabled_veil = pygame.Surface(options.size, pygame.SRCALPHA)
            disabled_veil.fill((3, 10, 28, 72))
            self.screen.blit(disabled_veil, options.topleft)

        if interactive:
            read_rect, hint_rect = layout.footer_buttons(2)
            read_btn = Button(read_rect, "读题", event_key="read_question",
                              border=theme.STAR_GOLD)
            hint_btn = Button(hint_rect, "提示", event_key="hint",
                              border=theme.ELECTRIC)
            read_btn.draw(self.screen, get_font(layout.font(22), bold=True))
            hint_btn.draw(self.screen, get_font(layout.font(22), bold=True))
            self.ui_registry.register("game.read_question", read_rect)
            self.ui_registry.register("game.hint", hint_rect)
            self.buttons.extend([read_btn, hint_btn])

    def _task_text(self):
        gid = self.game.game_id
        if gid in ("color", "shape"):
            label = next(i["label"] for i in self.game.all_items if i["id"] == self.game.target_id)
            return "请找到：{}".format(label)
        if gid == "counting":
            return "数一数：这里有几颗星星？"
        if gid == "english":
            return self.game.question
        if gid == "skill":
            return self.game.instruction
        if self.game.phase == "showing":
            return "观察星际航线亮起顺序"
        return "现在请按刚才的顺序点一遍  已点击 {} / {}".format(
            self.game.input_index, len(self.game.current_sequence))

    @staticmethod
    def _choice_columns(option_count):
        return 2 if int(option_count) <= 4 else 3

    # ── color options (FontManager text, energy orb PNGs) ───────

    def _render_color_options(self, layout, area, interactive):
        columns = self._choice_columns(len(self.game.options))
        for rect, item in zip(layout.grid_rects(area, len(self.game.options), columns), self.game.options):
            card = ColorOptionCard(rect, item, "choice:" + item["id"],
                                   image=self.color_orbs.get(item["id"]),
                                   card_image=self.panel_images["mission"],
                                   active_card_image=self.panel_images["mission"],
                                   chip_image=None)
            card.selected = (
                self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                and self.demo_target_kind == "game_choice" and self.demo_target_id == item["id"])
            # ColorOptionCard.draw already renders CN label + EN sublabel + SELECT via FontManager
            card.draw(self.screen, t=self.effect_time)
            self.ui_registry.register("game.choice.{}.{}".format(self.game.game_id, item["id"]), rect)
            if interactive:
                self.buttons.append(Button(rect, item["label"], event_key="choice:" + item["id"]))

    # ── shape options (FontManager text, shape icon PNGs) ───────

    def _render_shape_options(self, layout, area, interactive):
        columns = self._choice_columns(len(self.game.options))
        for rect, item in zip(layout.grid_rects(area, len(self.game.options), columns), self.game.options):
            card = ShapeOptionCard(rect, item, "choice:" + item["id"],
                                   image=self.shape_icons.get(item["id"]),
                                   card_image=self.panel_images["mission"],
                                   active_card_image=self.panel_images["mission_active"])
            card.selected = (
                self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                and self.demo_target_kind == "game_choice" and self.demo_target_id == item["id"])
            card.draw(self.screen)
            self.ui_registry.register("game.choice.{}.{}".format(self.game.game_id, item["id"]), rect)
            if interactive:
                self.buttons.append(Button(rect, item["label"], event_key="choice:" + item["id"]))

    # ── memory options ──────────────────────────────────────────

    def _render_memory_options(self, layout, area, interactive):
        rects = layout.grid_rects(area, 4, 2)
        centers = [r.center for r in rects]

        # Connection lines
        for a, b in ((0, 1), (0, 2), (1, 3), (2, 3)):
            pygame.draw.line(self.screen, (55, 232, 255, 30), centers[a], centers[b], width=2)

        for idx, rect in enumerate(rects):
            pid = str(idx)
            center = rect.center
            max_r = min(rect.w, rect.h) // 2 - 6
            radius = max(16, min(32, max_r))

            hl = self.game.highlighted == pid
            sel = (
                self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                and self.demo_target_kind == "game_choice" and self.demo_target_id == pid)
            fill = theme.STAR_GOLD if hl or sel else theme.ELECTRIC
            gw = 16 if hl or sel else 9

            draw_glow_circle(self.screen, center, radius, fill, glow=gw)
            pygame.draw.circle(self.screen, fill, center, radius)
            pygame.draw.circle(self.screen, (255, 255, 255, 70),
                               (center[0] - radius // 4, center[1] - radius // 4),
                               max(2, radius // 5))
            pygame.draw.circle(self.screen, theme.TEXT_MAIN, center, radius, width=3)

            if interactive and self.game.phase == "input":
                self.buttons.append(Button(rect, "", event_key="choice:" + pid))
            self.ui_registry.register("game.choice.memory.{}".format(pid), rect)

    def _render_counting_options(self, layout, area, interactive):
        visual = pygame.Rect(area.x, area.y, area.w, max(70, int(area.h * 0.42)))
        count = self.game.object_count
        columns = count if count <= 5 else min(8, (count + 1) // 2)
        rows = (count + columns - 1) // columns
        cell_w = visual.w / columns
        cell_h = visual.h / rows
        for index in range(count):
            row, column = divmod(index, columns)
            used = min(columns, count - row * columns)
            row_start = visual.centerx - used * cell_w / 2
            center = (int(row_start + (column + 0.5) * cell_w),
                      int(visual.y + (row + 0.5) * cell_h))
            glow_radius = max(12, int(18 * layout.scale))
            star_radius = max(8, int(12 * layout.scale))
            draw_glow_circle(self.screen, center, glow_radius,
                             theme.STAR_GOLD, glow=8)
            star_points = []
            for point_index in range(10):
                angle = -math.pi / 2 + point_index * math.pi / 5
                radius = star_radius if point_index % 2 == 0 else star_radius * 0.43
                star_points.append((
                    int(center[0] + math.cos(angle) * radius),
                    int(center[1] + math.sin(angle) * radius),
                ))
            pygame.draw.polygon(self.screen, theme.STAR_GOLD, star_points)
        choices = pygame.Rect(area.x, visual.bottom + layout.gap, area.w,
                              max(1, area.bottom - visual.bottom - layout.gap))
        columns = self._choice_columns(len(self.game.options))
        for rect, item in zip(layout.grid_rects(choices, len(self.game.options), columns),
                              self.game.options):
            selected = (self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                        and self.demo_target_id == item["id"])
            btn = Button(rect, item["label"], event_key="choice:" + item["id"],
                         border=theme.STAR_GOLD if selected else theme.ELECTRIC)
            btn.selected = selected
            btn.draw(self.screen, get_font(layout.font(34), bold=True))
            self.ui_registry.register("game.choice.counting.{}".format(item["id"]), rect)
            if interactive: self.buttons.append(btn)

    def _render_english_options(self, layout, area, interactive):
        rects = layout.grid_rects(
            area, len(self.game.options), self._choice_columns(len(self.game.options)))
        borders = (theme.SUCCESS, theme.ELECTRIC, theme.STAR_GOLD,
                   theme.CRYSTAL, theme.SOFT_RED, theme.WARNING)
        for index, (rect, item) in enumerate(zip(rects, self.game.options), start=1):
            selected = (self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                        and self.demo_target_id == item["id"])
            btn = Button(rect, item["label"],
                         event_key="choice:" + item["id"],
                         border=theme.STAR_GOLD if selected else borders[index - 1])
            btn.selected = selected
            btn.draw(self.screen, get_font(layout.font(24), bold=True))
            self.ui_registry.register("game.choice.english.{}".format(item["id"]), rect)
            if interactive: self.buttons.append(btn)

    def _render_skill_options(self, layout, area, interactive):
        rects = layout.grid_rects(
            area, len(self.game.options), self._choice_columns(len(self.game.options)))
        for rect, item in zip(rects, self.game.options):
            selected = (self.state == AppState.DEMO_MODE and self.demo_stage == "press"
                        and self.demo_target_id == item["id"])
            btn = Button(rect, item["label"],
                         event_key="choice:" + item["id"], border=theme.CRYSTAL)
            btn.selected = selected
            btn.draw(self.screen, get_font(layout.font(26), bold=True))
            self.ui_registry.register("game.choice.skill.{}".format(item["id"]), rect)
            if interactive: self.buttons.append(btn)

    # ═══════════════════════════════════════════════════════════
    #  SUMMARY  (clean — FontManager for all labels)
    # ═══════════════════════════════════════════════════════════

    def _render_summary(self, show_footer=True):
        layout = Layout(self.screen.get_size())
        self._draw_title(layout, "这次玩得怎么样？", "星宝把这次游戏记下来啦")
        summary = self.last_summary or {
            "game_name": "暂无", "completed_rounds": 0, "success_count": 0,
            "error_count": 0, "stars": 0,
            "encouragement": "先选择一个小游戏吧。", "parent_tip": "轻松开始就很好。",
        }
        char = layout.home_character_area()
        self._companion_panel(char, mood="happy", hint_text=summary["encouragement"]).draw(self.screen)

        panel = layout.home_cards_area()
        points_note = (" · 双倍积分{}".format(summary.get("score_points", 0))
                       if summary.get("game_id") == "skill" else "")
        TechPanel(panel,
            "任务：{}".format(summary["game_name"]),
            [("完成轮数", summary["completed_rounds"]),
             ("成功次数", summary["success_count"]),
             ("最终得分", summary.get("performance_score", 100)),
             ("获得经验", summary.get("experience_gained", 0))],
            note="本局获得{}颗星星{} · {}。给家长：{}".format(
                summary.get("stars", 0),
                points_note,
                "星宝称号：{}".format(self.records.level_title),
                summary["parent_tip"],
            ),
            border=theme.ELECTRIC,
            decoration=self.feedback_images["status_bar"],
            header_icon=self.system_images["report"],
        ).draw(self.screen, title_size=layout.font(26),
               value_size=layout.font(32), label_size=layout.font(18))

        if show_footer:
            frs = layout.footer_buttons(3)
            items = (
                ("再玩一次", "replay", theme.PANEL_GLASS, theme.STAR_GOLD),
                ("回到游戏乐园", "home", theme.PANEL_GLASS, theme.ELECTRIC),
                ("今日记录", "records", theme.PANEL_GLASS, theme.SUCCESS),
            )
            for r, (label, key, bg, bd) in zip(frs, items):
                btn = Button(
                    r, label, bg=bg, fg=theme.TEXT_MAIN, event_key=key, border=bd,
                    image=self.panel_images["button_primary"], active_image=self.panel_images["button_primary"],
                )
                btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
                self.ui_registry.register("summary.{}_button".format(key), r)
                self.buttons.append(btn)

    # ═══════════════════════════════════════════════════════════
    #  RECORDS  (clean — FontManager for all labels)
    # ═══════════════════════════════════════════════════════════

    def _render_skill_card(self):
        layout = Layout(self.screen.get_size())
        self._draw_title(layout, "星能升级舱", "三项能力 · 累计星星可购买消耗品")
        char = layout.home_character_area()
        self._companion_panel(char, hint_text=self.message, title="星能终端").draw(self.screen)

        panel = layout.home_cards_area()
        draw_glass_panel(self.screen, panel, border=theme.STAR_GOLD, radius=10, glow=8,
                         fill=(22, 34, 78, 218))
        pad = max(18, int(22 * layout.scale))
        selector = pygame.Rect(panel.x + pad, panel.y + pad, panel.w - pad * 2,
                               max(104, int(panel.h * 0.28)))
        borders = (theme.STAR_GOLD, theme.ELECTRIC, theme.SUCCESS)
        for rect, skill_id, border in zip(
                layout.grid_rects(selector, 3, 3), SKILL_META, borders):
            level = self.records.skill_level(skill_id)
            if skill_id == "experience_boost":
                subtitle = "LV.{}/{} · {}".format(
                    level, SKILL_MAX_LEVELS[skill_id], self._skill_effect_label(skill_id, level))
            else:
                subtitle = "库存{} · {}".format(level, self._skill_effect_label(skill_id, level))
            btn = Button(rect, SKILL_META[skill_id]["title"],
                         subtitle=subtitle,
                         event_key="skill_select:" + skill_id, border=border)
            btn.selected = self.selected_skill_id == skill_id
            btn.draw(self.screen, get_font(layout.font(22), bold=True))
            self._draw_skill_icon(rect, skill_id, border, layout.scale)
            self.ui_registry.register("skill.select.{}".format(skill_id), rect)
            self.buttons.append(btn)

        info_top = selector.bottom + layout.gap
        info_rect = pygame.Rect(panel.x + pad, info_top, panel.w - pad * 2,
                                panel.bottom - info_top - pad)
        skill_id = self.selected_skill_id
        current_level = self.records.skill_level(skill_id)
        maximum = SKILL_MAX_LEVELS[skill_id]
        amount_received = 2 if skill_id == "focus_shield" else 1
        next_level = min(maximum, current_level + amount_received)
        allowed, reason = self.records.can_upgrade_skill(skill_id)
        if skill_id == "experience_boost":
            level_cost = self.records.skill_upgrade_cost_for(skill_id)
            required_level = max(SKILL_UNLOCK_LEVEL, level_cost + 1)
            final_metric = (("星宝等级", "LV.{}".format(self.records.level - level_cost))
                            if allowed else
                             ("需要等级", "LV.{}".format(required_level)))
            metrics = [
                ("当前星运", "LV.{}".format(current_level)),
                ("提升后", "LV.{}".format(next_level)),
                ("本次消耗", "{}级".format(level_cost)),
                final_metric,
            ]
        else:
            received = "2个护盾" if skill_id == "focus_shield" else "1瓶药水"
            metrics = [
                ("当前库存", str(current_level)),
                ("购买获得", received),
                ("本次消耗", "5星星"),
                ("购买后星星", str(max(0, self.records.star_count - 5))),
            ]
        draw_glass_panel(self.screen, info_rect, border=theme.CRYSTAL, radius=8, glow=5,
                         fill=(18, 42, 84, 205))
        info_title_rect = draw_text(
            self.screen, SKILL_META[skill_id]["title"],
            (info_rect.x + 18, info_rect.y + 10),
            size=layout.font(21), color=theme.TEXT_MAIN, bold=True)
        info_description_rect = draw_text(
            self.screen, SKILL_META[skill_id]["description"],
            (info_rect.x + 18, info_title_rect.bottom + 6),
            size=layout.font(16), color=theme.TEXT_SUB)
        info_header_bottom = info_description_rect.bottom + 10
        cell_width = info_rect.w // 4
        value_y = info_rect.y + max(92, int(info_rect.h * 0.46))
        label_y = value_y + layout.font(36)
        for index, (label, value) in enumerate(metrics):
            center_x = info_rect.x + cell_width * index + cell_width // 2
            if index:
                pygame.draw.line(self.screen, (55, 232, 255, 38),
                                 (info_rect.x + cell_width * index, info_header_bottom),
                                 (info_rect.x + cell_width * index, info_rect.bottom - 54))
            value_text = str(value)
            value_font = fit_font(
                value_text, layout.font(28), max(40, cell_width - 20), bold=True)
            value_surface = value_font.render(value_text, True, theme.STAR_GOLD)
            self.screen.blit(value_surface, value_surface.get_rect(center=(center_x, value_y)))
            draw_text(self.screen, label, (center_x, label_y),
                      size=layout.font(16), color=theme.TEXT_SUB, center=True)
        if allowed:
            note = ("可以升级，星宝等级会立即降低。" if skill_id == "experience_boost"
                    else "")
        else:
            note = reason
        draw_text(self.screen, note, (info_rect.x + 18, info_rect.bottom - 32),
                  size=layout.font(16), color=theme.TEXT_SUB)

        home_rect, buy_rect = layout.footer_buttons(2)
        home_btn = Button(home_rect, "返回主控台", event_key="home", border=theme.ELECTRIC)
        if allowed:
            buy_label = "提升星运" if skill_id == "experience_boost" else "购买（5★）"
        else:
            buy_label = ("已满级" if skill_id == "experience_boost" and current_level >= maximum
                         else "条件不足")
        buy_btn = Button(buy_rect, buy_label, event_key="skill_upgrade",
                         border=theme.STAR_GOLD if allowed else theme.TEXT_MUTED)
        for key, btn in (("skill.home", home_btn), ("skill.upgrade", buy_btn)):
            btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
            self.ui_registry.register(key, btn.rect)
            self.buttons.append(btn)

    def _draw_skill_icon(self, rect, skill_id, color, scale):
        rect = pygame.Rect(rect)
        radius = max(12, min(int(rect.h * 0.2), int(20 * max(1.0, scale))))
        inset = max(12, int(14 * min(max(1.0, scale), 1.5)))
        center = (rect.x + radius + inset, rect.y + radius + inset)
        glow_radius = radius + 8
        glow = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, tuple(color[:3]) + (28,),
                           (glow_radius, glow_radius), glow_radius)
        self.screen.blit(glow, (center[0] - glow_radius, center[1] - glow_radius))

        if skill_id == "experience_boost":
            points = []
            for index in range(10):
                angle = -math.pi / 2 + index * math.pi / 5
                point_radius = radius if index % 2 == 0 else radius * 0.43
                points.append((
                    int(center[0] + math.cos(angle) * point_radius),
                    int(center[1] + math.sin(angle) * point_radius),
                ))
            pygame.draw.polygon(self.screen, color, points)
            pygame.draw.circle(self.screen, color, center, radius + 5, width=max(2, radius // 6))
            return

        if skill_id == "focus_shield":
            points = [
                (center[0], center[1] - radius),
                (center[0] + radius, center[1] - radius // 2),
                (center[0] + int(radius * 0.72), center[1] + radius // 2),
                (center[0], center[1] + radius),
                (center[0] - int(radius * 0.72), center[1] + radius // 2),
                (center[0] - radius, center[1] - radius // 2),
            ]
            pygame.draw.polygon(self.screen, color, points, width=max(3, radius // 5))
            pygame.draw.line(self.screen, color,
                             (center[0], center[1] - radius + 4),
                             (center[0], center[1] + radius - 5),
                             width=max(2, radius // 7))
            return

        neck_w = max(6, radius // 2)
        neck_h = max(5, radius // 3)
        bottle = [
            (center[0] - neck_w, center[1] - radius),
            (center[0] + neck_w, center[1] - radius),
            (center[0] + neck_w, center[1] - radius + neck_h),
            (center[0] + radius, center[1] + radius // 2),
            (center[0] + int(radius * 0.65), center[1] + radius),
            (center[0] - int(radius * 0.65), center[1] + radius),
            (center[0] - radius, center[1] + radius // 2),
            (center[0] - neck_w, center[1] - radius + neck_h),
        ]
        pygame.draw.polygon(self.screen, color, bottle, width=max(3, radius // 5))
        liquid_y = center[1] + radius // 4
        pygame.draw.line(self.screen, color,
                         (center[0] - int(radius * 0.72), liquid_y),
                         (center[0] + int(radius * 0.72), liquid_y),
                         width=max(3, radius // 4))

    def _skill_effect_label(self, skill_id, level):
        if skill_id == "experience_boost":
            if level <= 0:
                return "尚未激活"
            if level <= 5:
                return "小幅提升"
            if level <= 10:
                return "稳定提升"
            if level <= 15:
                return "明显提升"
            if level < 20:
                return "大幅提升"
            return "最高星运"
        if skill_id == "focus_shield":
            return "自动保护"
        return "成长能量变多"

    def _render_records(self):
        layout = Layout(self.screen.get_size())
        self._draw_title(layout, "陪伴数据", "本地成长记录与累计数据")
        snap = self.records.snapshot()

        char = layout.home_character_area()
        self._companion_panel(char, mood="happy", hint_text=self.message).draw(self.screen)

        panel = layout.home_cards_area()
        today_accuracy = (round(snap["today_success"] * 100 / snap["today_attempts"])
                          if snap["today_attempts"] else 0)
        TechPanel(panel,
            "最近任务：{}".format(snap["last_game"]),
            [("今日游戏", snap["today_games"]),
             ("今日成功", snap["today_success"]),
             ("今日正确率", "{}%".format(today_accuracy)),
             ("累计游戏", snap["games_played"]),
             ("累计成功", snap["total_success"]),
             ("累计星星", snap["star_count"])],
            note="星宝 LV.{} · {}  ".format(snap["level"], snap["level_title"])
                 + ("满级能量已稳定  " if snap["is_max_level"] else "能量 {}/{}  ".format(snap["energy"], snap["energy_max"]))
                 + "已自动保存 · {}".format(self._saved_time_label()),
            border=theme.CRYSTAL,
            decoration=self.feedback_images["status_bar"],
            header_icon=self.system_images["report"],
        ).draw(self.screen, title_size=layout.font(26),
               value_size=layout.font(32), label_size=layout.font(18))

        home_rect, clear_rect = layout.footer_buttons(2)
        home_btn = Button(home_rect, "返回主控台", bg=theme.PANEL_GLASS, fg=theme.TEXT_MAIN,
                          event_key="home", border=theme.ELECTRIC,
                          image=self.panel_images["button_primary"],
                          active_image=self.panel_images["button_primary"])
        home_btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        self.ui_registry.register("records.home_button", home_rect)
        self.buttons.append(home_btn)

        clear_btn = Button(clear_rect, "清空存档", bg=theme.PANEL_GLASS, fg=theme.TEXT_MAIN,
                           event_key="clear_save_request", border=theme.WARNING,
                           image=self.panel_images["button_secondary"],
                           active_image=self.panel_images["button_secondary"])
        clear_btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        self.ui_registry.register("records.clear_save_button", clear_rect)
        self.buttons.append(clear_btn)

        if self.confirm_clear_save:
            self._render_clear_save_confirm(layout)

    def _render_weekly_records(self):
        layout = Layout(self.screen.get_size())
        self._draw_title(layout, "近七日学习记录", "每天的学习时长与完成次数")
        history = self.records.last_seven_days()

        char = layout.home_character_area()
        total_seconds = sum(item["duration_seconds"] for item in history)
        total_games = sum(item["games"] for item in history)
        hint = "近七天学习{}，完成{}次。".format(
            self._learning_duration_label(total_seconds), total_games)
        self._companion_panel(char, mood="happy", hint_text=hint,
                              title="学习足迹").draw(self.screen)

        panel = layout.home_cards_area()
        draw_glass_panel(self.screen, panel, border=theme.CRYSTAL, radius=10, glow=7,
                         fill=(18, 36, 78, 218))
        pad = max(18, int(22 * layout.scale))
        draw_text(self.screen, "最近7天", (panel.x + pad, panel.y + pad - 4),
                  size=layout.font(22), color=theme.TEXT_MAIN, bold=True)

        legend_y = panel.y + pad + layout.font(30)
        legend_x = panel.x + pad
        for color, label in ((theme.ELECTRIC, "学习时长"),
                              (theme.STAR_GOLD, "学习次数")):
            swatch = pygame.Rect(legend_x, legend_y + 3,
                                 max(14, int(18 * layout.scale)),
                                 max(8, int(10 * layout.scale)))
            pygame.draw.rect(self.screen, color, swatch, border_radius=3)
            label_rect = draw_text(self.screen, label, (swatch.right + 8, legend_y),
                                   size=layout.font(15), color=theme.TEXT_SUB)
            legend_x = label_rect.right + max(18, int(26 * layout.scale))

        chart_top = legend_y + layout.font(26) + 10
        chart_bottom = panel.bottom - max(48, int(58 * layout.scale))
        chart = pygame.Rect(panel.x + pad, chart_top, panel.w - pad * 2,
                            max(80, chart_bottom - chart_top))
        pygame.draw.line(self.screen, (120, 160, 220, 90),
                         (chart.x, chart.bottom), (chart.right, chart.bottom), width=2)

        max_seconds = max(1, max(item["duration_seconds"] for item in history))
        max_games = max(1, max(item["games"] for item in history))
        slot_width = chart.w / 7
        bar_width = max(8, min(int(slot_width * 0.22),
                               int(24 * max(1.0, layout.scale))))
        usable_height = max(20, chart.h - layout.font(28))
        for index, item in enumerate(history):
            center_x = int(chart.x + (index + 0.5) * slot_width)
            duration_height = (int(usable_height * item["duration_seconds"] / max_seconds)
                               if item["duration_seconds"] else 0)
            games_height = (int(usable_height * item["games"] / max_games)
                            if item["games"] else 0)
            duration_rect = pygame.Rect(center_x - bar_width - 2,
                                        chart.bottom - duration_height,
                                        bar_width, duration_height)
            games_rect = pygame.Rect(center_x + 2, chart.bottom - games_height,
                                     bar_width, games_height)
            if duration_height:
                pygame.draw.rect(self.screen, theme.ELECTRIC, duration_rect, border_radius=4)
            if games_height:
                pygame.draw.rect(self.screen, theme.STAR_GOLD, games_rect, border_radius=4)
            if item["duration_seconds"] or item["games"]:
                value_label = "{} · {}次".format(
                    self._learning_duration_label(item["duration_seconds"]), item["games"])
                label_y = min(duration_rect.y if duration_height else chart.bottom,
                              games_rect.y if games_height else chart.bottom)
                draw_text(self.screen, value_label,
                          (center_x, max(chart.y, label_y - layout.font(16))),
                          size=layout.font(12), color=theme.TEXT_MAIN, center=True)
            draw_text(self.screen, item["label"],
                      (center_x, chart.bottom + max(10, int(14 * layout.scale))),
                      size=layout.font(13), color=theme.TEXT_SUB, center=True)

        home_rect = layout.footer_buttons(1)[0]
        home_btn = Button(home_rect, "返回主控台", event_key="home", border=theme.ELECTRIC,
                          image=self.panel_images["button_primary"],
                          active_image=self.panel_images["button_primary"])
        home_btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        self.ui_registry.register("weekly.home_button", home_rect)
        self.buttons.append(home_btn)

    @staticmethod
    def _learning_duration_label(seconds):
        seconds = max(0, int(seconds))
        if seconds < 60:
            return "{}秒".format(seconds)
        minutes = seconds / 60.0
        return "{:.1f}分".format(minutes) if minutes < 10 else "{}分".format(round(minutes))

    def _render_clear_save_confirm(self, layout):
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 135))
        self.screen.blit(shade, (0, 0))
        box = pygame.Rect(0, 0, int(layout.safe_area.w * 0.52), int(layout.safe_area.h * 0.36))
        box.center = layout.safe_area.center
        draw_glass_panel(self.screen, box, border=theme.WARNING, radius=12, glow=10,
                         fill=(16, 34, 66, 230))
        draw_text(self.screen, "确认清空本地存档？",
                  (box.centerx, box.y + 38),
                  size=layout.font(26), color=theme.TEXT_MAIN, bold=True, center=True)
        draw_wrapped_text(self.screen, "该操作只会清空成长记录，不会删除日志。",
                          pygame.Rect(box.x + 34, box.y + 82, box.w - 68, 60),
                          size=layout.font(theme.F_SMALL), color=theme.TEXT_SUB,
                          align="center", valign="center", max_lines=2)
        cancel_rect = pygame.Rect(box.x + 42, box.bottom - 82, (box.w - 108) // 2, 54)
        confirm_rect = pygame.Rect(cancel_rect.right + 24, cancel_rect.y, cancel_rect.w, cancel_rect.h)
        cancel = Button(cancel_rect, "取消", bg=theme.PANEL_GLASS, fg=theme.TEXT_MAIN,
                        event_key="clear_save_cancel", border=theme.ELECTRIC,
                        image=self.panel_images["button_primary"],
                        active_image=self.panel_images["button_primary"])
        confirm = Button(confirm_rect, "确认清空", bg=theme.PANEL_GLASS, fg=theme.TEXT_MAIN,
                         event_key="clear_save_confirm", border=theme.WARNING,
                         image=self.panel_images["button_secondary"],
                         active_image=self.panel_images["button_secondary"])
        cancel.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        confirm.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        self.ui_registry.register("records.clear_save_cancel", cancel_rect)
        self.ui_registry.register("records.clear_save_confirm", confirm_rect)
        self.buttons.append(cancel)
        self.buttons.append(confirm)

    def _saved_time_label(self):
        value = self.autosave.last_saved_at
        if not value:
            return "等待首次保存"
        try:
            return value[11:16]
        except (TypeError, IndexError):
            return "本地记录已保存"

    # ═══════════════════════════════════════════════════════════
    #  DEMO
    # ═══════════════════════════════════════════════════════════

    def _render_demo(self):
        layout = Layout(self.screen.get_size())
        if self.demo_view == "home":   self._render_home(interactive=False, show_footer=False)
        elif self.demo_view == "game": self._render_game(interactive=False)
        else:                           self._render_summary(show_footer=False)

        # Banner
        bw = int(layout.footer_area.w * 0.64)
        banner = pygame.Rect(layout.safe_area.x, layout.footer_area.y, bw, layout.footer_area.h)
        pulse = 0.6 + 0.4 * math.sin(self.effect_time * 1.8)
        gw = int(5 + 4 * pulse)
        draw_glass_panel(self.screen, banner, border=theme.CRYSTAL, radius=10, glow=gw)

        dl = "▶ 演示模式 · 第{}步/共{}步".format(
            getattr(self, "demo_step_index", 0), getattr(self, "demo_total_steps", 8))
        dlf = get_font(layout.font(theme.F_SMALL), bold=True)
        dlr = dlf.render(dl, True, theme.CRYSTAL)
        lx, ly = banner.x + 12, banner.y + 6
        self.screen.blit(dlr, (lx, ly))
        draw_wrapped_text(self.screen, self.demo_instruction,
                          pygame.Rect(banner.x + 12, ly + dlr.get_height(),
                                      banner.w - 24, banner.h - dlr.get_height() - 8),
                          size=layout.font(theme.F_SMALL - 2), bold=True,
                          align="center", valign="center")

        # Exit button
        er = self._demo_exit_rect(layout)
        btn = Button(er, "退出演示", bg=theme.PANEL_GLASS, fg=theme.TEXT_MAIN,
                     event_key="exit_demo", border=theme.WARNING,
                     image=self.panel_images["button_secondary"],
                     active_image=self.panel_images["button_secondary"])
        btn.draw(self.screen, get_font(layout.font(theme.F_BUTTON), bold=True))
        self.ui_registry.register("demo.exit_button", er)
        self.buttons = [btn]
        self._draw_demo_pointer(layout)

    def _draw_demo_pointer(self, layout):
        if self.demo_stage not in ("move", "press") or not self.demo_pointer_pos: return
        rect = self.ui_registry.get(getattr(self, "demo_target_key", None))
        if rect is not None:
            self.demo_target_rect = rect
            self.demo_pointer_pos = rect.center
        draw_demo_pointer(self.screen, self.demo_target_rect, self.demo_stage,
                          self.demo_remaining, DEMO_PRESS_DURATION,
                          scale=max(0.72, layout.scale), position=self.demo_pointer_pos,
                          image=self.system_images.get("pointer"))
        # Floating label
        x, y = self.demo_pointer_pos
        lw, lh = max(66, int(88 * layout.scale)), max(22, int(32 * layout.scale))
        lx = min(max(layout.safe_area.x, x + 28), layout.safe_area.right - lw)
        ly = min(max(layout.content_area.y, y - lh - 20), layout.footer_area.y - lh)
        lr = pygame.Rect(lx, ly, lw, lh)
        draw_glass_panel(self.screen, lr, border=theme.STAR_GOLD, radius=8, glow=5)
        draw_text(self.screen, "演示点击", lr.center,
                  size=layout.font(16), color=theme.TEXT_MAIN, bold=True, center=True)

    # ── corner button ─────────────────────────────────────────

    def _render_corner_button(self):
        if self.state in (AppState.EXIT, AppState.HOME):
            return
        layout = Layout(self.screen.get_size())
        r = layout.corner_button()
        self.ui_registry.register("nav.corner_back", r)
        if self.panel_images["button_secondary"] is not None:
            self.assets.draw_cover(self.screen, self.panel_images["button_secondary"], r, alpha=170)
        draw_glass_panel(self.screen, r, border=theme.ELECTRIC, radius=10, glow=5,
                         fill=(16, 34, 66, 180))
        cx, cy = r.center
        scale = max(0.8, layout.scale)
        left = int(cx - 16 * scale)
        right = int(cx + 15 * scale)
        wing = int(11 * scale)
        for width, color in ((8, (40, 220, 255, 55)), (4, theme.ELECTRIC)):
            pygame.draw.line(self.screen, color, (left, cy), (right, cy), width=width)
            pygame.draw.line(self.screen, color, (left, cy), (left + wing, cy - wing), width=width)
            pygame.draw.line(self.screen, color, (left, cy), (left + wing, cy + wing), width=width)
