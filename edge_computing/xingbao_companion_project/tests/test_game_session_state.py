from core.game_session_state import GameSessionRegistry


def _state(revision: int, *, page: str = "game_running") -> dict:
    return {
        "type": "game_state",
        "source": "xingbao_touch_game",
        "payload": {
            "client_session_id": "session-a",
            "client_session_epoch": 7,
            "state_revision": revision,
            "state": {
                "page_state": page,
                "game_id": "shape",
                "question_id": "shape:1:triangle",
            },
        },
    }


def test_newer_game_state_replaces_current_central_projection() -> None:
    registry = GameSessionRegistry()

    first = registry.apply_game_state(_state(1))
    second = registry.apply_game_state(_state(2, page="game_feedback"))

    assert first.status == "accepted"
    assert second.status == "accepted"
    assert second.state["state"]["page_state"] == "game_feedback"
    assert second.state["state_revision"] == 2


def test_stale_game_state_cannot_overwrite_newer_visible_page() -> None:
    registry = GameSessionRegistry()
    registry.apply_game_state(_state(3, page="game_feedback"))

    stale = registry.apply_game_state(_state(2, page="game_running"))

    assert stale.accepted is False
    assert stale.status == "stale_revision"
    assert stale.state["state"]["page_state"] == "game_feedback"


def test_stale_speech_is_rejected_and_latest_audio_lifecycle_is_kept() -> None:
    registry = GameSessionRegistry()
    registry.apply_game_state(_state(4))

    stale = registry.observe_speech(
        {
            "source": "xingbao_touch_game",
            "client_session_id": "session-a",
            "client_session_epoch": 7,
            "state_revision": 3,
            "utterance_id": "old-question",
        },
        "playing",
    )
    current = registry.observe_speech(
        {
            "source": "xingbao_touch_game",
            "client_session_id": "session-a",
            "client_session_epoch": 7,
            "state_revision": 4,
            "utterance_id": "current-question",
            "speech_role": "question",
            "page_state": "game_running",
            "question_id": "shape:1:triangle",
            "_cache_hit": True,
        },
        "finished",
    )

    snapshot = registry.snapshot(client_session_id="session-a", client_session_epoch=7)
    assert stale is False
    assert current is True
    assert snapshot["audio"] == {
        "status": "finished",
        "utterance_id": "current-question",
        "speech_role": "question",
        "page_state": "game_running",
        "question_id": "shape:1:triangle",
        "cache_hit": True,
    }
