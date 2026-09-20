import json
import socket
import threading

from core.game_speech_server import GameSpeechDispatcher, GameSpeechServer


def _send(host: str, port: int, message: dict) -> dict:
    encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.create_connection((host, port), timeout=2.0) as sock:
        sock.sendall(encoded)
        raw = sock.makefile("rb").readline()
    return json.loads(raw.decode("utf-8"))


def test_speech_request_is_queued_and_played_once() -> None:
    played = []
    server = GameSpeechServer(lambda text, payload: played.append((text, payload)), port=0).start()
    try:
        host, port = server.address
        request = {
            "type": "speech_request",
            "message_id": "speech-1",
            "source": "game_ui",
            "payload": {"text": "请找到蓝色", "page": "game_running"},
        }
        first = _send(host, port, request)
        second = _send(host, port, request)
        assert server.dispatcher.wait_until_idle()

        assert first["payload"]["status"] == "queued"
        assert second["payload"]["duplicate"] is True
        assert [item[0] for item in played] == ["请找到蓝色"]
    finally:
        server.close()


def test_speech_request_applies_shared_volume_before_playback(monkeypatch) -> None:
    saved = []
    played = []
    monkeypatch.setattr(
        "core.game_speech_server.save_output_volume",
        lambda volume: saved.append(int(volume)) or int(volume),
    )
    dispatcher = GameSpeechDispatcher(
        lambda text, payload: played.append((text, payload["volume"]))
    )
    try:
        response = dispatcher.dispatch({
            "type": "speech_request",
            "message_id": "volume-1",
            "source": "xingbao_desktop_read_aloud",
            "payload": {"text": "volume test", "volume": 40},
        })
        assert dispatcher.wait_until_idle()

        assert response["payload"]["status"] == "queued"
        assert saved == [40]
        assert played == [("volume test", 40)]
    finally:
        dispatcher.close()


def test_lifecycle_reports_queued_playing_and_finished_with_cache_context() -> None:
    lifecycle = []
    server = GameSpeechServer(
        lambda _text, _payload: None,
        lifecycle_handler=lambda payload, status: lifecycle.append(
            (status, payload.get("utterance_id"))
        ),
        port=0,
    ).start()
    try:
        response = _send(
            *server.address,
            {
                "type": "speech_request",
                "source": "xingbao_touch_game",
                "payload": {
                    "text": "请找到圆形。",
                    "utterance_id": "shape:1:circle",
                    "cache_hit": True,
                    "wait_for_finish": True,
                },
            },
        )

        assert response["payload"]["status"] == "finished"
        assert [status for status, _ in lifecycle] == ["queued", "playing", "finished"]
        assert all(utterance_id == "shape:1:circle" for _, utterance_id in lifecycle)
    finally:
        server.close()


def test_invalid_speech_request_fails_without_playback() -> None:
    played = []
    server = GameSpeechServer(lambda text, payload: played.append(text), port=0).start()
    try:
        host, port = server.address
        response = _send(host, port, {"type": "speech_request", "text": ""})

        assert response["ok"] is False
        assert response["payload"]["error"] == "empty_text"
        assert played == []
    finally:
        server.close()


def test_wait_for_finish_returns_only_after_playback_with_context() -> None:
    playback_started = threading.Event()
    release_playback = threading.Event()
    response_ready = threading.Event()
    response_box: list[dict] = []

    def handler(text, payload):
        assert text == "请找到三角形在哪里。"
        assert payload["question_id"] == "shape:1:triangle"
        playback_started.set()
        release_playback.wait(timeout=1.0)

    server = GameSpeechServer(handler, port=0).start()
    try:
        host, port = server.address
        request = {
            "type": "speech_request",
            "message_id": "speech-wait-1",
            "source": "xingbao_touch_game",
            "payload": {
                "text": "请找到三角形在哪里。",
                "utterance_id": "shape:1:triangle:question:1",
                "speech_role": "question",
                "page_state": "GAME_RUNNING",
                "game_id": "shape",
                "question_id": "shape:1:triangle",
                "wait_for_finish": True,
            },
        }

        def send_request() -> None:
            response_box.append(_send(host, port, request))
            response_ready.set()

        sender = threading.Thread(target=send_request)
        sender.start()
        assert playback_started.wait(timeout=1.0)
        assert response_ready.is_set() is False

        release_playback.set()
        sender.join(timeout=2.0)

        response = response_box[0]
        assert response["ok"] is True
        assert response["payload"] == {
            "status": "finished",
            "error": None,
            "utterance_id": "shape:1:triangle:question:1",
            "speech_role": "question",
            "page_state": "GAME_RUNNING",
            "game_id": "shape",
            "question_id": "shape:1:triangle",
        }
    finally:
        release_playback.set()
        server.close()


def test_wait_for_finish_reports_playback_failure() -> None:
    def handler(_text, _payload):
        raise RuntimeError("speaker unavailable")

    server = GameSpeechServer(handler, port=0).start()
    try:
        host, port = server.address
        response = _send(
            host,
            port,
            {
                "type": "speech_request",
                "message_id": "speech-failed-1",
                "source": "xingbao_touch_game",
                "payload": {
                    "text": "请找到蓝色。",
                    "utterance_id": "color:1:blue:question:1",
                    "speech_role": "question",
                    "page_state": "GAME_RUNNING",
                    "game_id": "color",
                    "question_id": "color:1:blue",
                    "wait_for_finish": True,
                },
            },
        )

        assert response["ok"] is False
        assert response["payload"]["status"] == "failed"
        assert response["payload"]["error"] == "RuntimeError"
        assert response["payload"]["utterance_id"] == "color:1:blue:question:1"
    finally:
        server.close()


def test_duplicate_waiting_request_does_not_finish_before_original_playback() -> None:
    release = threading.Event()
    started = threading.Event()

    def handler(_text, _payload):
        started.set()
        assert release.wait(2.0)

    dispatcher = GameSpeechDispatcher(handler)
    message = {
        "message_id": "same-request",
        "type": "speech_request",
        "source": "game_ui",
        "payload": {
            "text": "请找到圆形。",
            "request_tts": True,
            "wait_for_finish": True,
            "utterance_id": "u-duplicate",
        },
    }
    responses = []
    first = threading.Thread(target=lambda: responses.append(dispatcher.dispatch(message)))
    duplicate = threading.Thread(target=lambda: responses.append(dispatcher.dispatch(message)))
    first.start()
    assert started.wait(1.0)
    duplicate.start()

    duplicate.join(timeout=0.1)
    assert duplicate.is_alive()

    release.set()
    first.join(timeout=2.0)
    duplicate.join(timeout=2.0)
    assert [response["payload"]["status"] for response in responses] == [
        "finished",
        "finished",
    ]
    dispatcher.close()


def test_interrupting_read_aloud_replaces_pending_read_aloud_only() -> None:
    release_first = threading.Event()
    played = []

    def handler(text, payload):
        played.append((text, payload.get("source")))
        if text == "普通游戏提示":
            release_first.wait(timeout=1.0)

    server = GameSpeechServer(handler, port=0).start()
    try:
        host, port = server.address
        _send(
            host,
            port,
            {
                "type": "speech_request",
                "message_id": "normal-1",
                "source": "game_ui",
                "payload": {"text": "普通游戏提示", "page": "game_running"},
            },
        )
        _send(
            host,
            port,
            {
                "type": "speech_request",
                "message_id": "read-1",
                "source": "xingbao_desktop_read_aloud",
                "payload": {
                    "text": "旧点读",
                    "page": "desktop",
                    "interrupt": True,
                },
            },
        )
        _send(
            host,
            port,
            {
                "type": "speech_request",
                "message_id": "read-2",
                "source": "xingbao_desktop_read_aloud",
                "payload": {
                    "text": "新点读",
                    "page": "desktop",
                    "interrupt": True,
                },
            },
        )
        release_first.set()
        assert server.dispatcher.wait_until_idle()

        assert played == [
            ("普通游戏提示", "game_ui"),
            ("新点读", "xingbao_desktop_read_aloud"),
        ]
    finally:
        release_first.set()
        server.close()


def test_timed_out_queued_job_is_cancelled_before_playback() -> None:
    release_first = threading.Event()
    started_first = threading.Event()
    played: list[str] = []

    def handler(text, _payload):
        played.append(text)
        if text == "占用播放器":
            started_first.set()
            release_first.wait(timeout=2.0)

    dispatcher = GameSpeechDispatcher(handler)
    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "blocking",
            "payload": {"text": "占用播放器"},
        }
    )
    assert started_first.wait(1.0)

    response = dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "will-timeout",
            "source": "xingbao_touch_game",
            "payload": {
                "text": "不应播放的旧题目",
                "wait_for_finish": True,
                "completion_timeout_seconds": 0.01,
            },
        }
    )
    assert response["payload"]["status"] == "failed"
    assert response["payload"]["error"] == "speech_timeout"

    release_first.set()
    assert dispatcher.wait_until_idle()
    assert played == ["占用播放器"]
    dispatcher.close()


def test_replaceable_game_speech_interrupts_current_and_drops_pending() -> None:
    release_first = threading.Event()
    started_first = threading.Event()
    played: list[str] = []
    interrupted: list[str] = []

    def handler(text, _payload):
        played.append(text)
        if text == "旧欢迎":
            started_first.set()
            release_first.wait(timeout=2.0)

    dispatcher = GameSpeechDispatcher(
        handler,
        interrupt_handler=lambda payload: interrupted.append(payload["text"]),
    )
    common = {
        "type": "speech_request",
        "source": "xingbao_touch_game",
    }
    dispatcher.dispatch(
        {
            **common,
            "message_id": "old-playing",
            "payload": {
                "text": "旧欢迎",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    assert started_first.wait(1.0)
    dispatcher.dispatch(
        {
            **common,
            "message_id": "old-pending",
            "payload": {
                "text": "旧题目",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    dispatcher.dispatch(
        {
            **common,
            "message_id": "latest",
            "payload": {
                "text": "最新题目",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    release_first.set()
    assert dispatcher.wait_until_idle()

    assert "旧题目" not in played
    assert played[-1] == "最新题目"
    assert interrupted[-1] == "最新题目"
    dispatcher.close()


def test_duplicate_replace_request_does_not_interrupt_its_original() -> None:
    started = threading.Event()
    release = threading.Event()
    interrupted = []

    def handler(_text, _payload):
        started.set()
        release.wait(timeout=2.0)

    dispatcher = GameSpeechDispatcher(
        handler,
        interrupt_handler=lambda payload: interrupted.append(payload["text"]),
    )
    message = {
        "type": "speech_request",
        "message_id": "same-replace-id",
        "source": "xingbao_touch_game",
        "payload": {
            "text": "同一条题目",
            "interrupt": True,
            "replace_pending": True,
        },
    }
    dispatcher.dispatch(message)
    assert started.wait(1.0)

    duplicate = dispatcher.dispatch(message)

    assert duplicate["payload"]["duplicate"] is True
    assert interrupted == []
    release.set()
    dispatcher.close()


def test_concurrent_replace_requests_leave_only_one_latest_pending_job() -> None:
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    played = []

    def handler(text, _payload):
        played.append(text)
        if text == "阻塞":
            blocker_started.set()
            release_blocker.wait(timeout=2.0)

    dispatcher = GameSpeechDispatcher(handler)
    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "blocker",
            "payload": {"text": "阻塞"},
        }
    )
    assert blocker_started.wait(1.0)

    barrier = threading.Barrier(3)

    def submit(message_id, text):
        barrier.wait()
        dispatcher.dispatch(
            {
                "type": "speech_request",
                "message_id": message_id,
                "source": "xingbao_touch_game",
                "payload": {
                    "text": text,
                    "interrupt": True,
                    "replace_pending": True,
                },
            }
        )

    first = threading.Thread(target=submit, args=("replace-a", "替换A"))
    second = threading.Thread(target=submit, args=("replace-b", "替换B"))
    first.start()
    second.start()
    barrier.wait()
    first.join(timeout=1.0)
    second.join(timeout=1.0)
    release_blocker.set()
    assert dispatcher.wait_until_idle()

    replacements = [text for text in played if text.startswith("替换")]
    assert len(replacements) == 1
    dispatcher.close()


def test_replaced_active_job_reports_cancelled_not_finished() -> None:
    started = threading.Event()
    release = threading.Event()
    response_box = []

    def handler(text, _payload):
        if text == "旧题":
            started.set()
            release.wait(timeout=2.0)

    dispatcher = GameSpeechDispatcher(handler)
    old = {
        "type": "speech_request",
        "message_id": "active-old",
        "source": "xingbao_touch_game",
        "payload": {
            "text": "旧题",
            "interrupt": True,
            "replace_pending": True,
            "wait_for_finish": True,
        },
    }
    sender = threading.Thread(target=lambda: response_box.append(dispatcher.dispatch(old)))
    sender.start()
    assert started.wait(1.0)

    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "active-new",
            "source": "xingbao_touch_game",
            "payload": {
                "text": "新题",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    sender.join(timeout=1.0)

    assert response_box[0]["payload"]["status"] == "cancelled"
    assert response_box[0]["ok"] is False
    release.set()
    dispatcher.close()


def test_older_client_sequence_cannot_replace_newer_request() -> None:
    release_blocker = threading.Event()
    blocker_started = threading.Event()
    played = []

    def handler(text, _payload):
        played.append(text)
        if text == "阻塞":
            blocker_started.set()
            release_blocker.wait(timeout=2.0)

    dispatcher = GameSpeechDispatcher(handler)
    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "sequence-blocker",
            "payload": {"text": "阻塞"},
        }
    )
    assert blocker_started.wait(1.0)
    common = {
        "type": "speech_request",
        "source": "xingbao_touch_game",
    }
    newest = dispatcher.dispatch(
        {
            **common,
            "message_id": "sequence-new",
            "payload": {
                "text": "新请求",
                "speech_sequence": 2,
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    stale = dispatcher.dispatch(
        {
            **common,
            "message_id": "sequence-old",
            "payload": {
                "text": "乱序到达的旧请求",
                "speech_sequence": 1,
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    release_blocker.set()
    assert dispatcher.wait_until_idle()

    assert newest["payload"]["status"] == "queued"
    assert stale["payload"]["status"] == "cancelled"
    assert "乱序到达的旧请求" not in played
    assert "新请求" in played
    dispatcher.close()


def test_new_replaceable_handler_starts_while_cancelled_old_handler_is_blocked() -> None:
    old_started = threading.Event()
    new_started = threading.Event()
    release_old = threading.Event()

    def handler(text, _payload):
        if text == "旧动态合成":
            old_started.set()
            release_old.wait(timeout=2.0)
        else:
            new_started.set()

    dispatcher = GameSpeechDispatcher(handler)
    common = {
        "type": "speech_request",
        "source": "xingbao_touch_game",
    }
    dispatcher.dispatch(
        {
            **common,
            "message_id": "synth-old",
            "payload": {
                "text": "旧动态合成",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    assert old_started.wait(1.0)
    dispatcher.dispatch(
        {
            **common,
            "message_id": "synth-new",
            "payload": {
                "text": "新题",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )

    assert new_started.wait(1.0)
    release_old.set()
    assert dispatcher.wait_until_idle()
    dispatcher.close()


def test_newer_client_session_can_restart_sequence_and_old_session_stays_stale() -> None:
    played = []
    dispatcher = GameSpeechDispatcher(lambda text, _payload: played.append(text))
    common = {
        "type": "speech_request",
        "source": "xingbao_touch_game",
    }
    dispatcher.dispatch(
        {
            **common,
            "message_id": "old-session-50",
            "payload": {
                "text": "旧会话最后一题",
                "speech_sequence": 50,
                "client_session_id": "old",
                "client_session_epoch": 100,
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    restarted = dispatcher.dispatch(
        {
            **common,
            "message_id": "new-session-1",
            "payload": {
                "text": "重启后的第一题",
                "speech_sequence": 1,
                "client_session_id": "new",
                "client_session_epoch": 200,
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    late_old = dispatcher.dispatch(
        {
            **common,
            "message_id": "late-old-session",
            "payload": {
                "text": "迟到的旧会话",
                "speech_sequence": 51,
                "client_session_id": "old",
                "client_session_epoch": 100,
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    assert dispatcher.wait_until_idle()

    assert restarted["payload"]["status"] == "queued"
    assert late_old["payload"]["status"] == "cancelled"
    assert "重启后的第一题" in played
    assert "迟到的旧会话" not in played
    dispatcher.close()


def test_replaceable_synthesis_concurrency_is_bounded_and_keeps_latest() -> None:
    release = threading.Event()
    first_started = threading.Event()
    two_started = threading.Event()
    active = 0
    max_active = 0
    started = []
    lock = threading.Lock()

    def handler(text, _payload):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            started.append(text)
            first_started.set()
            if active >= 2:
                two_started.set()
        release.wait(timeout=2.0)
        with lock:
            active -= 1

    dispatcher = GameSpeechDispatcher(handler)
    common = {
        "type": "speech_request",
        "source": "xingbao_touch_game",
    }
    for index in range(2):
        dispatcher.dispatch(
            {
                **common,
                "message_id": f"bounded-{index}",
                "payload": {
                    "text": f"请求{index}",
                    "speech_sequence": index + 1,
                    "client_session_epoch": 1,
                    "interrupt": True,
                    "replace_pending": True,
                },
            }
        )
        if index == 0:
            assert first_started.wait(1.0)
    assert two_started.wait(1.0)
    for index in range(2, 12):
        dispatcher.dispatch(
            {
                **common,
                "message_id": f"bounded-{index}",
                "payload": {
                    "text": f"请求{index}",
                    "speech_sequence": index + 1,
                    "client_session_epoch": 1,
                    "interrupt": True,
                    "replace_pending": True,
                },
            }
        )

    release.set()
    assert dispatcher.wait_until_idle()

    assert max_active <= 2
    assert "请求11" in started
    assert len(started) <= 3
    dispatcher.close()


def test_active_replacement_is_cancelled_per_channel() -> None:
    game_started = threading.Event()
    read_started = threading.Event()
    new_game_started = threading.Event()
    release_read = threading.Event()
    game_token_box = []
    read_token_box = []

    def handler(text, payload):
        token = payload["_interrupt_event"]
        if text == "旧游戏":
            game_token_box.append(token)
            game_started.set()
            token.wait(timeout=2.0)
        elif text == "旧点读":
            read_token_box.append(token)
            read_started.set()
            release_read.wait(timeout=2.0)
        else:
            new_game_started.set()

    dispatcher = GameSpeechDispatcher(handler)
    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "channel-game-old",
            "source": "xingbao_touch_game",
            "payload": {
                "text": "旧游戏",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )
    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "channel-read-old",
            "source": "xingbao_desktop_read_aloud",
            "payload": {"text": "旧点读", "interrupt": True},
        }
    )
    assert game_started.wait(1.0)
    assert read_started.wait(1.0)

    dispatcher.dispatch(
        {
            "type": "speech_request",
            "message_id": "channel-game-new",
            "source": "xingbao_touch_game",
            "payload": {
                "text": "新游戏",
                "interrupt": True,
                "replace_pending": True,
            },
        }
    )

    assert game_token_box[0].wait(1.0)
    assert read_token_box[0].is_set() is False
    assert new_game_started.wait(1.0)
    release_read.set()
    assert dispatcher.wait_until_idle()
    dispatcher.close()
