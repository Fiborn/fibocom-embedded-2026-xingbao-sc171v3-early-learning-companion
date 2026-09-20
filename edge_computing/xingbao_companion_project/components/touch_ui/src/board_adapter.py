"""Board-facing UI adapters. Network threads enqueue; Pygame's main thread executes."""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Future, TimeoutError

from .action_schema import ARM_ACTIONS, LED_MODES, sanitize_feedback
from .game_api import GameCommandAdapter, normalize_game_id


EXPRESSION_TO_DESKTOP = {
    "neutral": "idle", "smile": "happy", "thinking": "thinking",
    "curious": "thinking", "sad": "thinking", "surprised": "celebrate",
    "sleepy": "yawn",
}


class BoardUIAdapter:
    """Thread-safe facade shared by the desktop, game and central controller."""

    def __init__(self):
        self.desktop = None
        self.app = None
        self.main_thread_id = threading.get_ident()
        self.tasks = queue.Queue()
        self.pending_game = None

    def bind(self, desktop=None, app=None):
        if desktop is not None:
            self.desktop = desktop
        if app is not None:
            self.app = app
        self.main_thread_id = threading.get_ident()
        return self

    def submit(self, function, *args, wait=True, timeout=5.0, **kwargs):
        if threading.get_ident() == self.main_thread_id:
            return function(*args, **kwargs)
        future = Future()
        self.tasks.put((future, function, args, kwargs))
        if not wait:
            return {"ok": True, "queued": True}
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise

    def pump(self, limit=16):
        """Call once per frame from the active Pygame UI loop."""
        for _ in range(limit):
            try:
                future, function, args, kwargs = self.tasks.get_nowait()
            except queue.Empty:
                break
            try:
                if not future.set_running_or_notify_cancel():
                    continue
                result = function(*args, **kwargs)
                future.set_result(result)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                self.tasks.task_done()

    def open_game(self, game_id=None, source="voice", context=None):
        return self.submit(self._open_game, game_id, source, context)

    def return_to_desktop(self, source="voice", context=None):
        return self.submit(self._return_to_desktop, source, context)

    def _open_game(self, game_id, source, context):
        internal = None if game_id is None else normalize_game_id(game_id)
        difficulty = int((context or {}).get("difficulty", 1))
        if game_id is not None and internal is None:
            return {"ok": False, "action": "open_game", "error": "unknown_game_id"}
        if difficulty not in (1, 2, 3):
            return {"ok": False, "action": "open_game", "error": "invalid_difficulty"}
        self.pending_game = {"game_id": internal, "difficulty": difficulty,
                             "source": source, "context": dict(context or {})}
        desktop_active = (
            self.desktop is not None
            and getattr(self.desktop, "active", False)
            and getattr(self.desktop, "running", False)
        )
        app_active = (
            self.app is not None
            and getattr(self.app, "active", False)
            and getattr(self.app, "running", False)
        )
        if app_active:
            if internal is None:
                self.app.go_home()
            else:
                self.app.start_game(internal, difficulty=difficulty)
                self.pending_game = None
        elif desktop_active:
            self.desktop.open_game()
        elif self.app is not None:
            if internal is None:
                self.app.go_home()
            else:
                self.app.start_game(internal, difficulty=difficulty)
                self.pending_game = None
        elif self.desktop is not None:
            self.desktop.open_game()
        else:
            return {"ok": False, "action": "open_game", "error": "ui_not_bound"}
        return {"ok": True, "action": "open_game", "game_id": game_id,
                "difficulty": difficulty, "source": source, "executed_on_ui_thread": True}

    def _return_to_desktop(self, source, context):
        self.pending_game = None
        if self.app is not None and getattr(self.app, "running", False):
            self.app.stop()
            return {"ok": True, "action": "return_to_desktop", "source": source,
                    "executed_on_ui_thread": True}
        if self.desktop is not None:
            return {"ok": True, "action": "return_to_desktop", "source": source,
                    "already_on_desktop": True, "executed_on_ui_thread": True}
        return {"ok": False, "action": "return_to_desktop", "error": "ui_not_bound"}

    def set_expression(self, expression, screen_text="", source="voice", context=None):
        return self.submit(self._set_expression, expression, screen_text, source, context)

    def _set_expression(self, expression, screen_text, source, context):
        clean = sanitize_feedback({"screen_expression": expression})["screen_expression"]
        state = EXPRESSION_TO_DESKTOP[clean]
        target = self.desktop
        if target is None:
            return {"ok": False, "action": "set_expression", "error": "desktop_not_bound",
                    "expression": clean, "desktop_state": state}
        seconds = max(0.2, min(30.0, float((context or {}).get("duration_ms", 4000)) / 1000.0))
        target.set_xingbao_state(state, seconds=seconds)
        if screen_text:
            priority = str((context or {}).get("subtitle_priority") or "external")
            target.show_notice(str(screen_text), seconds=seconds, priority=priority)
        return {"ok": True, "action": "set_expression", "expression": clean,
                "desktop_state": state, "fallback": clean != expression, "source": source,
                "executed_on_ui_thread": True}

    def hardware_feedback(self, arm_action="stay_still", led_mode="off"):
        """Validation boundary only; actual motor/LED driver belongs to hardware team."""
        valid_arm = arm_action in ARM_ACTIONS
        valid_led = led_mode in LED_MODES
        clean = sanitize_feedback({"arm_action": arm_action, "led_mode": led_mode})
        return {"ok": valid_arm and valid_led, "implemented_by": "board_hardware_team",
                "arm_action": clean["arm_action"], "led_mode": clean["led_mode"],
                "error": None if valid_arm and valid_led else "unsupported_hardware_feedback"}

    def handle_game_command(self, command):
        return self.submit(self._handle_game_command, command)

    def _handle_game_command(self, command):
        if self.app is None:
            return {"type": "game_response", "ok": False, "error": {"code": "ui_not_bound"},
                    "message": "当前游戏还没有准备好。", "state": {}}
        return GameCommandAdapter(self.app).handle_command(command)


runtime = BoardUIAdapter()


def open_game(game_id=None, source="voice", context=None):
    return runtime.open_game(game_id, source, context)


def return_to_desktop(source="voice", context=None):
    return runtime.return_to_desktop(source, context)


def set_xingbao_expression(expression, screen_text="", source="voice", context=None):
    return runtime.set_expression(expression, screen_text, source, context)


def apply_hardware_feedback(arm_action="stay_still", led_mode="off"):
    return runtime.hardware_feedback(arm_action, led_mode)


def handle_game_command(command):
    return runtime.handle_game_command(command)
