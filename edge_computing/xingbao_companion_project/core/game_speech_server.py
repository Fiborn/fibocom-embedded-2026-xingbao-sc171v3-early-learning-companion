"""Local NDJSON service for queued game speech and demo module events."""

from __future__ import annotations

import json
import queue
import socketserver
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict

from core.audio_preferences import save_output_volume


SpeechHandler = Callable[[str, Dict[str, Any]], None]
EventHandler = Callable[[Dict[str, Any]], None]
InterruptHandler = Callable[[Dict[str, Any]], None]
LifecycleHandler = Callable[[Dict[str, Any], str], None]

EVENT_MESSAGE_TYPES = {
    "game_event",
    "game_state",
    "mini_game_state",
    "vision_state",
    "vision_event",
    "xingbao_expression_request",
}


@dataclass(frozen=True)
class SpeechJob:
    message_id: str
    text: str
    payload: dict[str, Any]
    message: dict[str, Any] | None = None
    completion: threading.Event | None = None
    result: dict[str, Any] = field(default_factory=dict)


class GameSpeechDispatcher:
    """Validates, deduplicates, and serializes speech requests."""

    def __init__(
        self,
        handler: SpeechHandler,
        *,
        event_handler: EventHandler | None = None,
        interrupt_handler: InterruptHandler | None = None,
        lifecycle_handler: LifecycleHandler | None = None,
        max_text_chars: int = 300,
        replacement_coalesce_seconds: float = 0.015,
    ) -> None:
        self.handler = handler
        self.event_handler = event_handler
        self.interrupt_handler = interrupt_handler
        self.lifecycle_handler = lifecycle_handler
        self.max_text_chars = max(1, int(max_text_chars))
        self.replacement_coalesce_seconds = max(
            0.0, float(replacement_coalesce_seconds)
        )
        self._queue: queue.Queue[SpeechJob | None] = queue.Queue()
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._speech_jobs: dict[str, SpeechJob] = {}
        self._seen_lock = threading.Lock()
        self._replacement_lock = threading.Lock()
        self._replacement_generation: dict[str, int] = {}
        self._latest_source_sequence: dict[str, int] = {}
        self._latest_source_epoch: dict[str, int] = {}
        self._active_lock = threading.Lock()
        self._active_jobs: dict[str, SpeechJob] = {}
        self._job_threads_lock = threading.Lock()
        self._job_threads: set[threading.Thread] = set()
        self._replace_slots = threading.BoundedSemaphore(2)
        self._deferred_jobs: dict[str, SpeechJob] = {}
        self._worker = threading.Thread(
            target=self._run,
            name="game-speech-worker",
            daemon=True,
        )
        self._worker.start()

    def dispatch(self, message: dict[str, Any]) -> dict[str, Any]:
        message_type = str(message.get("type") or "")
        if message_type in EVENT_MESSAGE_TYPES:
            return self._dispatch_event(message)
        if message_type != "speech_request":
            return self._status(message, "failed", error="unsupported_message_type")

        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = message
        text = str(payload.get("text") or "").strip()
        if not text:
            return self._status(message, "failed", error="empty_text")
        if len(text) > self.max_text_chars:
            return self._status(message, "failed", error="text_too_long")
        if payload.get("request_tts") is False:
            return self._status(message, "finished")

        message_id = str(message.get("message_id") or uuid.uuid4())
        job_payload = dict(payload)
        job_payload.setdefault("source", message.get("source"))
        job_payload.setdefault("text", text)
        if "volume" in job_payload:
            try:
                job_payload["volume"] = save_output_volume(
                    job_payload["volume"]
                )
            except OSError:
                pass
        wait_for_finish = bool(job_payload.get("wait_for_finish", False))
        enqueue_job = False
        with self._replacement_lock:
            with self._seen_lock:
                job = self._speech_jobs.get(message_id)
                if job is None:
                    if self._is_replaceable(job_payload):
                        job_payload["_interrupt_event"] = threading.Event()
                    self._seen.add(message_id)
                    self._seen_order.append(message_id)
                    job = SpeechJob(
                        message_id=message_id,
                        text=text,
                        payload=job_payload,
                        completion=threading.Event(),
                    )
                    self._speech_jobs[message_id] = job
                    enqueue_job = True
                    self._prune_history_locked()
            if enqueue_job:
                if self._is_replaceable(job_payload):
                    channel = self._channel_key(job_payload)
                    sequence = self._speech_sequence(job_payload)
                    session_epoch = self._session_epoch(job_payload)
                    latest_epoch = self._latest_source_epoch.get(channel, 0)
                    if latest_epoch > 0 and session_epoch < latest_epoch:
                        self._cancel_job(job, "stale_client_session")
                        return self._status(
                            message,
                            "cancelled",
                            error="stale_client_session",
                            message_id=message_id,
                            context=job_payload,
                        )
                    if session_epoch > latest_epoch:
                        self._latest_source_epoch[channel] = session_epoch
                        self._latest_source_sequence[channel] = 0
                    latest_sequence = self._latest_source_sequence.get(channel, 0)
                    if sequence > 0 and sequence <= latest_sequence:
                        self._cancel_job(job, "stale_speech_sequence")
                        return self._status(
                            message,
                            "cancelled",
                            error="stale_speech_sequence",
                            message_id=message_id,
                            context=job_payload,
                        )
                    if sequence > 0:
                        self._latest_source_sequence[channel] = sequence
                    generation = self._replacement_generation.get(channel, 0) + 1
                    self._replacement_generation[channel] = generation
                    job_payload["_replacement_generation"] = generation
                    self._interrupt_current(job_payload)
                    self._drop_pending_replaceable(job_payload)
                    deferred = self._deferred_jobs.pop(channel, None)
                    if deferred is not None:
                        self._cancel_job(deferred)
                self._queue.put(job)
                self._notify_lifecycle(job_payload, "queued")
        if not enqueue_job and not wait_for_finish:
            return self._status(message, "finished", duplicate=True)
        if wait_for_finish and job.completion is not None:
            timeout = _bounded_completion_timeout(
                job_payload.get("completion_timeout_seconds")
            )
            if not job.completion.wait(timeout=timeout):
                self._cancel_job(job, "speech_timeout")
                self._interrupt_job_if_active(job)
                return self._status(
                    message,
                    "failed",
                    error="speech_timeout",
                    message_id=message_id,
                    context=job_payload,
                )
            return self._status(
                message,
                str(job.result.get("status") or "failed"),
                error=job.result.get("error"),
                duplicate=not enqueue_job,
                message_id=message_id,
                context=job_payload,
            )
        return self._status(message, "queued", message_id=message_id)

    def _dispatch_event(self, message: dict[str, Any]) -> dict[str, Any]:
        if self.event_handler is None:
            return self._status(message, "failed", error="event_handler_unavailable")
        message_id = str(message.get("message_id") or uuid.uuid4())
        with self._seen_lock:
            if message_id in self._seen:
                return self._status(message, "finished", duplicate=True)
            self._seen.add(message_id)
            self._seen_order.append(message_id)
            self._prune_history_locked()
        self._queue.put(
            SpeechJob(
                message_id=message_id,
                text="",
                payload={},
                message=dict(message),
            )
        )
        return self._status(message, "queued", message_id=message_id)

    def close(self, timeout: float = 2.0) -> None:
        self._queue.put(None)
        deadline = max(0.0, timeout)
        self._worker.join(timeout=deadline)
        with self._job_threads_lock:
            threads = list(self._job_threads)
        for thread in threads:
            thread.join(timeout=deadline)

    def wait_until_idle(self, timeout: float = 2.0) -> bool:
        done = threading.Event()
        marker = SpeechJob(message_id="", text="", payload={"_done": done})
        self._queue.put(marker)
        return done.wait(timeout=max(0.0, timeout))

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                done = job.payload.get("_done")
                if isinstance(done, threading.Event):
                    self._wait_for_job_threads()
                    done.set()
                    continue
                async_started = False
                try:
                    if job.message is not None:
                        if self.event_handler is not None:
                            self.event_handler(job.message)
                    else:
                        if self._is_replaceable(job.payload):
                            if self._is_stale_replacement(job):
                                self._cancel_job(job)
                            if not self._is_cancelled(job):
                                self._start_replaceable_job(job)
                                async_started = True
                            continue
                        with self._active_lock:
                            self._active_jobs[self._channel_key(job.payload)] = job
                        if self._is_stale_replacement(job):
                            self._cancel_job(job)
                        if self._is_cancelled(job):
                            continue
                        self._notify_lifecycle(job.payload, "playing")
                        self.handler(job.text, job.payload)
                    if not self._is_cancelled(job):
                        job.result.update({"status": "finished", "error": None})
                except Exception as exc:  # pragma: no cover - process must remain alive
                    if not self._is_cancelled(job):
                        job.result.update(
                            {
                                "status": "failed",
                                "error": type(exc).__name__,
                                "message": str(exc),
                            }
                        )
                    print(
                        "[game-speech] failed message_id={} error={}: {}".format(
                            job.message_id, type(exc).__name__, exc
                        ),
                        flush=True,
                    )
                finally:
                    if not async_started:
                        with self._active_lock:
                            channel = self._channel_key(job.payload)
                            if self._active_jobs.get(channel) is job:
                                self._active_jobs.pop(channel, None)
                        if job.completion is not None:
                            job.completion.set()
                        if job.message is None:
                            self._notify_lifecycle(
                                job.payload,
                                str(job.result.get("status") or "finished"),
                            )
                        with self._seen_lock:
                            self._prune_history_locked()
            finally:
                self._queue.task_done()

    def _start_replaceable_job(self, job: SpeechJob) -> None:
        if not self._replace_slots.acquire(blocking=False):
            channel = self._channel_key(job.payload)
            with self._replacement_lock:
                previous = self._deferred_jobs.get(channel)
                if previous is not None:
                    self._cancel_job(previous)
                self._deferred_jobs[channel] = job
            return
        self._launch_replaceable_job(job)

    def _launch_replaceable_job(self, job: SpeechJob) -> None:
        thread = threading.Thread(
            target=self._run_replaceable_job,
            args=(job,),
            name="game-speech-replaceable",
            daemon=True,
        )
        with self._job_threads_lock:
            self._job_threads.add(thread)
        thread.start()

    def _run_replaceable_job(self, job: SpeechJob) -> None:
        try:
            if self.replacement_coalesce_seconds:
                time.sleep(self.replacement_coalesce_seconds)
            with self._replacement_lock:
                channel = self._channel_key(job.payload)
                generation = int(job.payload.get("_replacement_generation") or 0)
                if generation != self._replacement_generation.get(channel, generation):
                    self._cancel_job(job)
                else:
                    with self._active_lock:
                        self._active_jobs[channel] = job
            if self._is_cancelled(job):
                return
            try:
                self._notify_lifecycle(job.payload, "playing")
                self.handler(job.text, job.payload)
                if not self._is_cancelled(job):
                    job.result.update({"status": "finished", "error": None})
            except Exception as exc:  # pragma: no cover - worker must remain alive
                if not self._is_cancelled(job):
                    job.result.update(
                        {
                            "status": "failed",
                            "error": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
        finally:
            with self._active_lock:
                channel = self._channel_key(job.payload)
                if self._active_jobs.get(channel) is job:
                    self._active_jobs.pop(channel, None)
            if job.completion is not None:
                job.completion.set()
            self._notify_lifecycle(
                job.payload,
                str(job.result.get("status") or "finished"),
            )
            with self._seen_lock:
                self._prune_history_locked()
            self._replace_slots.release()
            self._start_next_deferred_job()
            with self._job_threads_lock:
                self._job_threads.discard(threading.current_thread())

    def _start_next_deferred_job(self) -> None:
        selected = None
        with self._replacement_lock:
            for channel, job in list(self._deferred_jobs.items()):
                self._deferred_jobs.pop(channel, None)
                if not self._is_cancelled(job):
                    selected = job
                    break
        if selected is None:
            return
        if not self._replace_slots.acquire(blocking=False):
            with self._replacement_lock:
                self._deferred_jobs[self._channel_key(selected.payload)] = selected
            return
        self._launch_replaceable_job(selected)

    def _wait_for_job_threads(self) -> None:
        while True:
            with self._job_threads_lock:
                threads = [
                    thread
                    for thread in self._job_threads
                    if thread is not threading.current_thread()
                ]
            if not threads:
                return
            for thread in threads:
                thread.join()

    @staticmethod
    def _is_replaceable_read_aloud(payload: dict[str, Any]) -> bool:
        return (
            bool(payload.get("interrupt", False))
            and str(payload.get("source") or "") == "xingbao_desktop_read_aloud"
        )

    @classmethod
    def _is_replaceable(cls, payload: dict[str, Any]) -> bool:
        if cls._is_replaceable_read_aloud(payload):
            return True
        return (
            bool(payload.get("interrupt", False))
            and bool(payload.get("replace_pending", False))
            and str(payload.get("source") or "") == "xingbao_touch_game"
        )

    def _interrupt_current(self, payload: dict[str, Any]) -> None:
        with self._active_lock:
            channel = self._channel_key(payload)
            active = self._active_jobs.get(channel)
            if active is None:
                return
            self._cancel_job(active)
        self._call_interrupt_handler(payload)

    def _interrupt_job_if_active(self, job: SpeechJob) -> None:
        with self._active_lock:
            channel = self._channel_key(job.payload)
            if self._active_jobs.get(channel) is not job:
                return
        self._call_interrupt_handler(job.payload)

    def _call_interrupt_handler(self, payload: dict[str, Any]) -> None:
        if self.interrupt_handler is None:
            return
        try:
            self.interrupt_handler(dict(payload))
        except Exception as exc:  # pragma: no cover - interruption must not stop service
            print(
                "[game-speech] interrupt failed error={}: {}".format(
                    type(exc).__name__, exc
                ),
                flush=True,
            )

    def _notify_lifecycle(self, payload: dict[str, Any], status: str) -> None:
        if self.lifecycle_handler is None:
            return
        try:
            self.lifecycle_handler(dict(payload), str(status or "unknown"))
        except Exception as exc:  # pragma: no cover - observer must never stop audio
            print(
                "[game-speech] lifecycle observer failed error={}: {}".format(
                    type(exc).__name__, exc
                ),
                flush=True,
            )

    def _is_stale_replacement(self, job: SpeechJob) -> bool:
        if not self._is_replaceable(job.payload):
            return False
        channel = self._channel_key(job.payload)
        generation = int(job.payload.get("_replacement_generation") or 0)
        with self._replacement_lock:
            return generation != self._replacement_generation.get(channel, generation)

    @staticmethod
    def _is_cancelled(job: SpeechJob) -> bool:
        return str(job.result.get("status") or "") == "cancelled"

    @staticmethod
    def _cancel_job(job: SpeechJob, error: str = "speech_cancelled") -> None:
        job.result.update({"status": "cancelled", "error": error})
        interrupt_event = job.payload.get("_interrupt_event")
        if isinstance(interrupt_event, threading.Event):
            interrupt_event.set()
        if job.completion is not None:
            job.completion.set()

    def _drop_pending_replaceable(self, incoming: dict[str, Any]) -> None:
        kept: list[SpeechJob | None] = []
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if (
                    job is None
                    or job.message is not None
                    or not self._same_replaceable_channel(job.payload, incoming)
                ):
                    kept.append(job)
                else:
                    self._cancel_job(job)
            finally:
                self._queue.task_done()
        for job in kept:
            self._queue.put(job)

    def _prune_history_locked(self, limit: int = 512) -> None:
        attempts = len(self._seen_order)
        while len(self._seen_order) > limit and attempts > 0:
            attempts -= 1
            message_id = self._seen_order.popleft()
            job = self._speech_jobs.get(message_id)
            if (
                job is not None
                and job.completion is not None
                and not job.completion.is_set()
            ):
                self._seen_order.append(message_id)
                continue
            self._seen.discard(message_id)
            self._speech_jobs.pop(message_id, None)

    @classmethod
    def _same_replaceable_channel(
        cls,
        queued: dict[str, Any],
        incoming: dict[str, Any],
    ) -> bool:
        if cls._is_replaceable_read_aloud(incoming):
            return cls._is_replaceable_read_aloud(queued)
        return (
            cls._is_replaceable(incoming)
            and cls._is_replaceable(queued)
            and str(queued.get("source") or "") == str(incoming.get("source") or "")
        )

    @staticmethod
    def _channel_key(payload: dict[str, Any]) -> str:
        return str(payload.get("source") or "game_ui")

    @staticmethod
    def _speech_sequence(payload: dict[str, Any]) -> int:
        try:
            return max(0, int(payload.get("speech_sequence") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _session_epoch(payload: dict[str, Any]) -> int:
        try:
            return max(0, int(payload.get("client_session_epoch") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _status(
        message: dict[str, Any],
        status: str,
        *,
        error: str | None = None,
        duplicate: bool = False,
        message_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status, "error": error}
        if duplicate:
            payload["duplicate"] = True
        for key in (
            "utterance_id",
            "speech_sequence",
            "client_session_id",
            "client_session_epoch",
            "speech_role",
            "page_state",
            "game_id",
            "question_id",
            "state_revision",
            "cache_hit",
        ):
            value = (context or {}).get(key)
            if value not in (None, ""):
                payload[key] = value
        return {
            "version": "1.0",
            "message_id": str(uuid.uuid4()),
            "type": "speech_status",
            "source": "central_controller",
            "target": str(message.get("source") or "game_ui"),
            "reply_to": message_id or message.get("message_id"),
            "payload": payload,
            "ok": status not in {"failed", "cancelled"},
        }


def _bounded_completion_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = 30.0
    return max(1.0, min(timeout, 120.0))


class _SpeechRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        dispatcher: GameSpeechDispatcher = self.server.dispatcher  # type: ignore[attr-defined]
        while True:
            try:
                raw = self.rfile.readline()
            except (ConnectionResetError, OSError):
                return
            if not raw:
                return
            try:
                message = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(message, dict):
                    raise ValueError("message must be a JSON object")
                response = dispatcher.dispatch(message)
            except Exception as exc:
                response = {
                    "type": "speech_status",
                    "ok": False,
                    "payload": {
                        "status": "failed",
                        "error": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            try:
                self.wfile.write(
                    (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                )
            except (BrokenPipeError, ConnectionResetError, OSError):
                return


class _ThreadedSpeechServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class GameSpeechServer:
    """Owns the loopback TCP server and the serialized TTS dispatcher."""

    def __init__(
        self,
        handler: SpeechHandler,
        *,
        event_handler: EventHandler | None = None,
        interrupt_handler: InterruptHandler | None = None,
        lifecycle_handler: LifecycleHandler | None = None,
        host: str = "127.0.0.1",
        port: int = 8766,
        max_text_chars: int = 300,
    ) -> None:
        self.dispatcher = GameSpeechDispatcher(
            handler,
            event_handler=event_handler,
            interrupt_handler=interrupt_handler,
            lifecycle_handler=lifecycle_handler,
            max_text_chars=max_text_chars,
        )
        self.server = _ThreadedSpeechServer((host, int(port)), _SpeechRequestHandler)
        self.server.dispatcher = self.dispatcher  # type: ignore[attr-defined]
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="game-speech-server",
            daemon=True,
        )

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.server.server_address[:2]
        return str(host), int(port)

    def start(self) -> "GameSpeechServer":
        self.thread.start()
        return self

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        self.dispatcher.close()
