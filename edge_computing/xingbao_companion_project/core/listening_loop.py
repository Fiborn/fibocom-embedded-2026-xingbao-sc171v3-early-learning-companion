"""Wake-word gated listening loop for continuous companion operation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class WakeWordDetector(Protocol):
    def wait_for_wake_word(self) -> str:
        """Block until a wake word is detected."""


@dataclass
class ListeningLoop:
    """Runs one synchronous voice turn after each local wake-word detection."""

    detector: WakeWordDetector
    on_wake: Callable[[], Any]
    play_wake_ack: Callable[[], Any] | None = None
    on_turn_complete: Callable[[Any], Any] | None = None
    cooldown_seconds: float = 1.2
    sleep: Callable[[float], None] = time.sleep

    def run(self, *, max_turns: int | None = None) -> int:
        completed_turns = 0
        while max_turns is None or completed_turns < max_turns:
            self.detector.wait_for_wake_word()
            if self.play_wake_ack is not None:
                self.play_wake_ack()
            result = self.on_wake()
            completed_turns += 1
            if self.on_turn_complete is not None:
                self.on_turn_complete(result)
            if self.cooldown_seconds > 0:
                self.sleep(self.cooldown_seconds)
        return completed_turns
