"""Non-blocking game-to-central speech_request client."""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
import uuid


def _bounded_volume(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 100
    return max(0, min(100, parsed))


class CentralSpeechClient:
    def __init__(self, host="127.0.0.1", port=8766, timeout=1.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.session_id = str(uuid.uuid4())
        self.session_epoch = time.time_ns()
        self._sequence_lock = threading.Lock()
        self._source_sequences = {}
        self._queue = queue.Queue()
        self._response_threads = set()
        self._response_threads_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run,
            name="central-speech-client",
            daemon=True,
        )
        self._worker.start()

    def submit(self, request):
        """Queue a speech callback without blocking the Pygame UI thread."""
        if not isinstance(request, dict):
            return
        text = str(request.get("text") or "").strip()
        if not text:
            return
        if self._is_replaceable(request):
            self._drop_pending_replaceable(request)
        source = request.get("source") or "game_ui"
        with self._sequence_lock:
            current_sequence = int(self._source_sequences.get(source, 0))
            requested_sequence = int(request.get("speech_sequence") or 0)
            speech_sequence = max(current_sequence + 1, requested_sequence)
            self._source_sequences[source] = speech_sequence
        message = {
            "version": "1.0",
            "message_id": str(uuid.uuid4()),
            "type": "speech_request",
            "source": source,
            "target": "central_controller",
            "payload": {
                "text": text,
                "scene": request.get("scene") or "game",
                "game_id": request.get("game_id"),
                "page": request.get("page") or "game_running",
                "page_state": request.get("page_state") or request.get("page") or "game_running",
                "question_id": request.get("question_id"),
                "utterance_id": request.get("utterance_id") or str(uuid.uuid4()),
                "speech_sequence": speech_sequence,
                "client_session_id": self.session_id,
                "client_session_epoch": self.session_epoch,
                "speech_role": request.get("speech_role") or "prompt",
                "priority": request.get("priority") or "normal",
                "interrupt": bool(request.get("interrupt", False)),
                "pause_conversation": bool(request.get("pause_conversation", False)),
                "replace_pending": bool(request.get("replace_pending", False)),
                "latency_mode": request.get("latency_mode") or "",
                "voice": request.get("voice") or "child_friendly",
                "request_tts": True,
                "wait_for_finish": bool(request.get("wait_for_finish", False)),
                "completion_timeout_seconds": request.get(
                    "completion_timeout_seconds", 30.0
                ),
            },
        }
        if "volume" in request:
            message["payload"]["volume"] = _bounded_volume(request.get("volume"))
        message["_on_status"] = request.get("on_status")
        message["_retry_count"] = max(0, int(request.get("retry_count", 1)))
        self._queue.put(message)

    def submit_state(self, state):
        """Queue a versioned game-state event without blocking Pygame."""
        if not isinstance(state, dict):
            return
        snapshot = state.get("state")
        if not isinstance(snapshot, dict):
            return
        try:
            revision = int(state.get("state_revision") or 0)
        except (TypeError, ValueError):
            return
        if revision <= 0:
            return
        message = {
            "version": "1.0",
            "message_id": str(uuid.uuid4()),
            "type": "game_state",
            "source": state.get("source") or "xingbao_touch_game",
            "target": "central_controller",
            "payload": {
                "state": dict(snapshot),
                "state_revision": revision,
                "reason": state.get("reason") or "state_changed",
                "prefetch_texts": list(state.get("prefetch_texts") or []),
                "session_id": state.get("session_id") or "",
                "client_session_id": self.session_id,
                "client_session_epoch": self.session_epoch,
            },
        }
        message["_on_status"] = None
        message["_retry_count"] = 0
        self._queue.put(message)

    def close(self, timeout=1.0):
        deadline = time.monotonic() + max(0.0, float(timeout))
        self._queue.put(None)
        self._worker.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._response_threads_lock:
            threads = list(self._response_threads)
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _run(self):
        while True:
            message = self._queue.get()
            try:
                if message is None:
                    return
                callback = message.pop("_on_status", None)
                retries = int(message.pop("_retry_count", 0))
                sock = None
                last_error = None
                for attempt in range(retries + 1):
                    try:
                        sock = self._open_request(message)
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt < retries:
                            time.sleep(0.15)
                if sock is None:
                    status = self._failure_status(message, last_error)
                    print(
                        "[game-speech] central unavailable: {}".format(last_error),
                        flush=True,
                    )
                    if callable(callback):
                        callback(status)
                else:
                    response_thread = threading.Thread(
                        target=self._read_response,
                        args=(sock, message, callback),
                        name="central-speech-response",
                        daemon=True,
                    )
                    with self._response_threads_lock:
                        self._response_threads.add(response_thread)
                    response_thread.start()
            except Exception as exc:
                print("[game-speech] central unavailable: {}".format(exc), flush=True)
            finally:
                self._queue.task_done()

    def _open_request(self, message):
        encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        payload = message.get("payload") or {}
        if payload.get("wait_for_finish"):
            response_timeout = max(
                self.timeout,
                float(payload.get("completion_timeout_seconds") or 30.0) + 2.0,
            )
        else:
            response_timeout = self.timeout
        sock.settimeout(response_timeout)
        try:
            sock.sendall(encoded)
        except Exception:
            sock.close()
            raise
        return sock

    def _read_response(self, sock, message, callback):
        try:
            with sock:
                response = sock.makefile("rb").readline()
            if not response:
                raise RuntimeError("central returned no speech_status")
            status = json.loads(response.decode("utf-8-sig"))
        except Exception as exc:
            status = self._failure_status(message, exc)
            print("[game-speech] central unavailable: {}".format(exc), flush=True)
        try:
            if callable(callback):
                callback(status)
        finally:
            with self._response_threads_lock:
                self._response_threads.discard(threading.current_thread())

    @staticmethod
    def _failure_status(message, error):
        payload = message.get("payload") or {}
        return {
            "type": "speech_status",
            "ok": False,
            "reply_to": message.get("message_id"),
            "payload": {
                "status": "failed",
                "error": type(error).__name__,
                "message": str(error),
                "utterance_id": payload.get("utterance_id"),
                "speech_role": payload.get("speech_role"),
                "page_state": payload.get("page_state"),
                "game_id": payload.get("game_id"),
                "question_id": payload.get("question_id"),
            },
        }

    def _send(self, message):
        sock = self._open_request(message)
        with sock:
            response = sock.makefile("rb").readline()
        if not response:
            raise RuntimeError("central returned no speech_status")
        status = json.loads(response.decode("utf-8-sig"))
        return status

    @staticmethod
    def _is_replaceable_read_aloud(request):
        return (
            bool(request.get("interrupt", False))
            and str(request.get("source") or "") == "xingbao_desktop_read_aloud"
        )

    @classmethod
    def _is_replaceable(cls, request):
        if cls._is_replaceable_read_aloud(request):
            return True
        return (
            bool(request.get("interrupt", False))
            and bool(request.get("replace_pending", False))
            and str(request.get("source") or "") == "xingbao_touch_game"
        )

    @staticmethod
    def _message_is_read_aloud(message):
        if not isinstance(message, dict):
            return False
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return False
        return (
            str(message.get("source") or "") == "xingbao_desktop_read_aloud"
            and bool(payload.get("interrupt", False))
        )

    @classmethod
    def _message_is_replaceable(cls, message):
        if not isinstance(message, dict):
            return False
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return False
        request = dict(payload)
        request.setdefault("source", message.get("source"))
        return cls._is_replaceable(request)

    @classmethod
    def _same_replaceable_channel(cls, message, incoming):
        if cls._is_replaceable_read_aloud(incoming):
            return cls._message_is_read_aloud(message)
        payload = message.get("payload") if isinstance(message, dict) else None
        return (
            isinstance(payload, dict)
            and cls._message_is_replaceable(message)
            and str(message.get("source") or "") == str(incoming.get("source") or "")
        )

    def _drop_pending_replaceable(self, incoming):
        kept = []
        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if not self._same_replaceable_channel(message, incoming):
                    kept.append(message)
                else:
                    self._cancel_pending_message(message)
            finally:
                self._queue.task_done()
        for message in kept:
            self._queue.put(message)

    @staticmethod
    def _cancel_pending_message(message):
        callback = message.get("_on_status") if isinstance(message, dict) else None
        if not callable(callback):
            return
        payload = message.get("payload") or {}
        callback({
            "type": "speech_status",
            "ok": False,
            "reply_to": message.get("message_id"),
            "payload": {
                "status": "cancelled",
                "error": "speech_replaced",
                "utterance_id": payload.get("utterance_id"),
                "speech_role": payload.get("speech_role"),
                "page_state": payload.get("page_state"),
                "game_id": payload.get("game_id"),
                "question_id": payload.get("question_id"),
            },
        })

    def _drop_pending_read_aloud(self):
        self._drop_pending_replaceable(
            {
                "source": "xingbao_desktop_read_aloud",
                "interrupt": True,
            }
        )
