"""Central, versioned view of an active touch-game session.

The touch UI remains responsive and owns rendering.  This module gives the
central controller a matching, ordered projection of that UI state so speech
can be rejected or cancelled when it no longer belongs to the visible page.
It deliberately stores only the current in-memory session state; long-term
learning memory is outside this interaction-layer module.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GameStateUpdate:
    """Result of accepting or rejecting one UI state snapshot."""

    accepted: bool
    status: str
    session_key: str
    revision: int
    state: dict[str, Any]


@dataclass
class _SessionRecord:
    revision: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.monotonic)


class GameSessionRegistry:
    """Thread-safe state projection shared by game events and speech workers."""

    def __init__(self) -> None:
        self._records: dict[str, _SessionRecord] = {}
        self._lock = threading.Lock()

    def apply_game_state(self, message: dict[str, Any]) -> GameStateUpdate:
        """Apply a versioned ``game_state`` envelope from the touch UI.

        Duplicate revisions are idempotent.  Older revisions are rejected so a
        delayed socket packet cannot make the central controller speak for a
        page that is no longer visible.
        """
        payload = _payload(message)
        state = payload.get("state")
        state = dict(state) if isinstance(state, dict) else {}
        session_key = _session_key(message, payload)
        revision = _positive_int(payload.get("state_revision"))
        if revision <= 0:
            return GameStateUpdate(False, "invalid_revision", session_key, 0, {})

        with self._lock:
            record = self._records.get(session_key)
            if record is None:
                record = _SessionRecord()
                self._records[session_key] = record
            if revision < record.revision:
                return GameStateUpdate(
                    False,
                    "stale_revision",
                    session_key,
                    record.revision,
                    self._snapshot(record),
                )
            if revision == record.revision:
                return GameStateUpdate(
                    True,
                    "duplicate_revision",
                    session_key,
                    record.revision,
                    self._snapshot(record),
                )
            record.revision = revision
            record.state = state
            record.updated_at = time.monotonic()
            return GameStateUpdate(
                True,
                "accepted",
                session_key,
                record.revision,
                self._snapshot(record),
            )

    def observe_speech(self, payload: dict[str, Any], status: str) -> bool:
        """Record a speech lifecycle transition if it belongs to the latest UI.

        Returns ``False`` for a stale speech request.  Callers should cancel
        that request before it reaches the speaker.
        """
        safe_payload = dict(payload or {})
        session_key = _session_key({}, safe_payload)
        revision = _positive_int(safe_payload.get("state_revision"))
        with self._lock:
            record = self._records.get(session_key)
            if record is not None and revision and revision < record.revision:
                return False
            if record is None:
                record = _SessionRecord(revision=revision)
                self._records[session_key] = record
            elif revision > record.revision:
                # A speech request may arrive before its non-blocking state
                # event. Keep it, but never move an existing state backwards.
                record.revision = revision
            record.audio = {
                "status": str(status or "unknown"),
                "utterance_id": safe_payload.get("utterance_id"),
                "speech_role": safe_payload.get("speech_role"),
                "page_state": safe_payload.get("page_state"),
                "question_id": safe_payload.get("question_id"),
                "cache_hit": safe_payload.get("_cache_hit"),
            }
            record.updated_at = time.monotonic()
            return True

    def snapshot(
        self,
        *,
        source: str = "xingbao_touch_game",
        client_session_id: str = "",
        client_session_epoch: int | str | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "source": source,
            "client_session_id": client_session_id,
            "client_session_epoch": client_session_epoch,
        }
        with self._lock:
            record = self._records.get(_session_key({}, payload))
            return self._snapshot(record) if record is not None else None

    @staticmethod
    def _snapshot(record: _SessionRecord) -> dict[str, Any]:
        return {
            "state_revision": record.revision,
            "state": dict(record.state),
            "audio": dict(record.audio),
        }


def _payload(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload") if isinstance(message, dict) else None
    return dict(payload) if isinstance(payload, dict) else {}


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _session_key(message: dict[str, Any], payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or message.get("source") or "xingbao_touch_game")
    session_id = str(payload.get("client_session_id") or payload.get("session_id") or "default")
    epoch = _positive_int(payload.get("client_session_epoch"))
    return "{}:{}:{}".format(source, session_id, epoch)
