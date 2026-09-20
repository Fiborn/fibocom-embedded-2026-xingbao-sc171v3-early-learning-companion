"""Structured speech lifecycle state shared by the game UI and API."""

from __future__ import annotations

from collections import UserDict


class SpeechState(UserDict):
    def __init__(self):
        super().__init__({
            "utterance_id": None,
            "role": "idle",
            "status": "idle",
            "page_state": "home",
            "game_id": None,
            "question_id": None,
            "error": None,
        })
        self._sequence = 0

    def begin(
        self,
        *,
        role,
        page_state,
        game_id=None,
        question_id=None,
        available=True,
    ):
        self._sequence += 1
        utterance_id = "game-ui-{}".format(self._sequence)
        self.data.update({
            "utterance_id": utterance_id,
            "role": str(role or "prompt"),
            "status": "queued" if available else "unavailable",
            "page_state": str(page_state or "home"),
            "game_id": game_id,
            "question_id": question_id,
            "error": None,
        })
        return utterance_id

    def apply_status(self, status):
        payload = status.get("payload") if isinstance(status, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("utterance_id") != self.data.get("utterance_id"):
            return False
        next_status = payload.get("status")
        if not next_status:
            next_status = "finished" if status.get("ok") else "failed"
        self.data["status"] = str(next_status)
        self.data["error"] = payload.get("error")
        return True

    @property
    def is_terminal(self):
        return self.data.get("status") in {
            "finished",
            "failed",
            "cancelled",
            "unavailable",
        }

    @property
    def sequence(self):
        return self._sequence

    def as_dict(self):
        return dict(self.data)
