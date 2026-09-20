"""DashScope ASR client."""

from __future__ import annotations

import array
import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable

from core.network import NetworkClient
from core.settings import AppSettings, get_dashscope_api_key


BAILIAN_COMPAT_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


class EmptyRecognitionResult(RuntimeError):
    """Recognition completed normally but did not contain usable speech text.

    This is an expected outcome when a child pauses, whispers, or the VAD
    captures environmental sound.  Callers should end only the current
    listening turn and return to wake-word listening, rather than treating it
    as a fatal voice-service failure.
    """


class RecognitionStartTimeout(TimeoutError):
    """Streaming recognition did not initialize before its safety deadline."""


class SherpaOnnxASRClient:
    """Transcribe recorded speech with the bundled local Sherpa-ONNX runtime.

    Xingbao's VAD owns microphone capture.  Keeping recognition as a WAV-to-text
    step lets the local model replace every cloud ASR request without changing
    the rest of the dialogue, interruption, or TTS pipeline.
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings.load()
        self.model = self.settings.asr_model
        self.last_metrics: dict[str, float | str] = {}

    def transcribe(self, wav_path: Path | str) -> str:
        path = Path(wav_path)
        if not path.is_file():
            raise FileNotFoundError(f"Local ASR audio file does not exist: {path}")

        model_dir = Path(self.settings.local_asr_model_dir)
        runtime_dir = Path(self.settings.local_asr_runtime_dir)
        executable = runtime_dir / "bin" / "sherpa-onnx"
        required_paths = (
            executable,
            model_dir / "encoder.int8.onnx",
            model_dir / "decoder.onnx",
            model_dir / "joiner.int8.onnx",
            model_dir / "tokens.txt",
        )
        missing = [str(item) for item in required_paths if not item.is_file()]
        if missing:
            raise RuntimeError(
                "Local Sherpa-ONNX ASR is not ready; missing: " + ", ".join(missing)
            )

        command = [
            str(executable),
            "--provider=cpu",
            f"--num-threads={max(1, self.settings.local_asr_num_threads)}",
            "--decoding-method=greedy_search",
            f"--encoder={model_dir / 'encoder.int8.onnx'}",
            f"--decoder={model_dir / 'decoder.onnx'}",
            f"--joiner={model_dir / 'joiner.int8.onnx'}",
            f"--tokens={model_dir / 'tokens.txt'}",
            str(path),
        ]
        environment = os.environ.copy()
        runtime_lib = str(runtime_dir / "lib")
        existing_library_path = environment.get("LD_LIBRARY_PATH", "")
        environment["LD_LIBRARY_PATH"] = (
            f"{runtime_lib}:{existing_library_path}"
            if existing_library_path
            else runtime_lib
        )
        started_at = time.perf_counter()
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        self._append_log(output)
        self.last_metrics = {
            "encode_ms": 0.0,
            "request_ms": elapsed_ms,
            "engine": "sherpa_onnx_local",
            "model": self.model,
        }
        if completed.returncode != 0:
            detail = output.strip()[-800:] or "no diagnostic output"
            raise RuntimeError(
                f"Local Sherpa-ONNX recognition failed (exit {completed.returncode}): {detail}"
            )
        text = _sherpa_output_text(completed.stdout)
        if not text:
            raise EmptyRecognitionResult("Local Sherpa-ONNX returned empty text.")
        return text

    @staticmethod
    def _append_log(output: str) -> None:
        if not output:
            return
        log_path = Path(os.environ.get("XINGBAO_LOCAL_ASR_LOG", "logs/sherpa-onnx-asr.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(output.rstrip() + "\n")


class SherpaOnnxStreamingASRClient:
    """Send VAD-approved PCM frames to the local Sherpa streaming server."""

    _server_lock = threading.Lock()
    _server_process: subprocess.Popen[str] | None = None

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings.load()
        self.model = self.settings.asr_model
        self.last_metrics: dict[str, float | str] = {}
        self._socket: Any | None = None
        self._ready = threading.Event()
        self._complete = threading.Event()
        self._cancelled = threading.Event()
        self._start_error: BaseException | None = None
        self._latest_text = ""
        self._lock = threading.Lock()
        self._started_at = 0.0
        self._frame_count = 0
        self._total_bytes = 0
        self._partial_callback: Callable[[str], None] | None = None
        self._last_logged_text = ""

    def set_partial_callback(self, callback: Callable[[str], None] | None) -> None:
        """Receive every changed partial transcript from the local server."""
        self._partial_callback = callback

    def start_background(self) -> None:
        threading.Thread(target=self.start, name="sherpa-local-asr-connect", daemon=True).start()

    def start(self) -> None:
        try:
            self._ensure_server()
            import websocket

            self._socket = websocket.create_connection(
                f"ws://127.0.0.1:{self.settings.local_asr_server_port}",
                timeout=8,
            )
            self._started_at = time.perf_counter()
            threading.Thread(
                target=self._receive_loop,
                name="sherpa-local-asr-receive",
                daemon=True,
            ).start()
        except BaseException as exc:
            self._start_error = exc
        finally:
            self._ready.set()

    def send_audio_frame(self, frame: bytes) -> None:
        if not frame or self._cancelled.is_set():
            return
        if not self._ready.wait(timeout=8):
            raise RecognitionStartTimeout("Local Sherpa streaming ASR did not start.")
        if self._start_error is not None:
            raise RuntimeError("Local Sherpa streaming ASR failed to start.") from self._start_error
        ws = self._socket
        if ws is None:
            return
        samples = array.array("h")
        samples.frombytes(frame)
        if sys.byteorder != "little":
            samples.byteswap()
        waveform = array.array("f", (sample / 32768.0 for sample in samples))
        try:
            from websocket import ABNF

            ws.send(waveform.tobytes(), opcode=ABNF.OPCODE_BINARY)
        except Exception as exc:
            self._start_error = exc
            self._complete.set()
            return
        self._frame_count += 1
        self._total_bytes += len(frame)

    def partial_text(self) -> str:
        with self._lock:
            return self._latest_text

    def finish(self) -> str:
        if not self._ready.wait(timeout=8):
            self.cancel()
            raise RecognitionStartTimeout("Local Sherpa streaming ASR did not start.")
        if self._start_error is not None:
            raise RuntimeError("Local Sherpa streaming ASR failed to start.") from self._start_error
        ws = self._socket
        if ws is None:
            raise RuntimeError("Local Sherpa streaming ASR has no active socket.")
        try:
            ws.send("Done")
            self._complete.wait(timeout=8)
        finally:
            self._close_socket()
        elapsed_ms = round((time.perf_counter() - self._started_at) * 1000, 1)
        self.last_metrics = {
            "encode_ms": 0.0,
            "request_ms": elapsed_ms,
            "total_stream_ms": elapsed_ms,
            "engine": "sherpa_onnx_local_streaming",
            "model": self.model,
            "frames": float(self._frame_count),
            "bytes": float(self._total_bytes),
        }
        if self._start_error is not None:
            raise RuntimeError("Local Sherpa streaming ASR failed.") from self._start_error
        text = self.partial_text()
        if not text:
            raise EmptyRecognitionResult("Local Sherpa streaming ASR returned empty text.")
        self._append_streaming_result("final", text)
        return text

    def cancel(self) -> None:
        self._cancelled.set()
        self._close_socket()
        self._complete.set()

    def _receive_loop(self) -> None:
        ws = self._socket
        if ws is None:
            return
        try:
            while not self._cancelled.is_set():
                message = ws.recv()
                if not message or message == "Done":
                    self._complete.set()
                    return
                try:
                    result = json.loads(message)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(result, dict):
                    continue
                text = str(result.get("text", "")).strip()
                if text:
                    with self._lock:
                        changed = text != self._latest_text
                        self._latest_text = text
                    if changed:
                        self._append_streaming_result("partial", text)
                        callback = self._partial_callback
                        if callback is not None:
                            try:
                                callback(text)
                            except Exception:
                                pass
                if result.get("is_eof"):
                    self._complete.set()
                    return
        except BaseException as exc:
            if not self._cancelled.is_set():
                self._start_error = exc
        finally:
            self._complete.set()

    def _close_socket(self) -> None:
        ws, self._socket = self._socket, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _append_streaming_result(self, stage: str, text: str) -> None:
        """Mirror ASR output into the Sherpa log alongside server diagnostics."""
        if not text or (stage == "partial" and text == self._last_logged_text):
            return
        self._last_logged_text = text
        log_path = Path(
            os.environ.get("XINGBAO_LOCAL_ASR_LOG", "logs/sherpa-onnx-streaming.log")
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] [asr] {stage} text={text}\n")

    def _ensure_server(self) -> None:
        port = self.settings.local_asr_server_port
        if _local_port_open(port):
            return
        with self._server_lock:
            if _local_port_open(port):
                return
            model_dir = Path(self.settings.local_asr_model_dir)
            runtime_dir = Path(self.settings.local_asr_runtime_dir)
            executable = runtime_dir / "bin" / "sherpa-onnx-online-websocket-server"
            required = (executable, model_dir / "encoder.int8.onnx", model_dir / "decoder.onnx", model_dir / "joiner.int8.onnx", model_dir / "tokens.txt")
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                raise RuntimeError("Local Sherpa streaming ASR is not ready; missing: " + ", ".join(missing))
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = str(runtime_dir / "lib") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
            log_path = Path(os.environ.get("XINGBAO_LOCAL_ASR_LOG", "logs/sherpa-onnx-streaming.log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log_file:
                self.__class__._server_process = subprocess.Popen(
                    [str(executable), f"--port={port}", "--num-work-threads=2", f"--log-file={log_path}", "--provider=cpu", f"--num-threads={max(1, self.settings.local_asr_num_threads)}", f"--tokens={model_dir / 'tokens.txt'}", f"--encoder={model_dir / 'encoder.int8.onnx'}", f"--decoder={model_dir / 'decoder.onnx'}", f"--joiner={model_dir / 'joiner.int8.onnx'}"],
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if _local_port_open(port):
                    return
                if self.__class__._server_process.poll() is not None:
                    raise RuntimeError("Local Sherpa streaming server exited during startup.")
                time.sleep(0.1)
            raise RecognitionStartTimeout("Local Sherpa streaming server did not listen in time.")


def _local_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.15):
            return True
    except OSError:
        return False


def _sherpa_output_text(output: str) -> str:
    """Extract the final transcript from Sherpa's JSON-lines CLI output."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            text = str(value.get("text", "")).strip()
            if text:
                return text
    return ""


class DashScopeASRClient:
    """Transcribes WAV files through DashScope compatible chat ASR."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        network_client: NetworkClient | None = None,
    ) -> None:
        self.settings = settings or AppSettings.load()
        self.network_client = network_client or NetworkClient(self.settings)
        self.last_metrics: dict[str, float] = {}

    def transcribe(self, wav_path: Path | str) -> str:
        path = Path(wav_path)
        api_key = get_dashscope_api_key()
        encode_started_at = time.perf_counter()
        audio_data_uri = audio_to_data_uri(path)
        encode_ms = round((time.perf_counter() - encode_started_at) * 1000, 1)
        payload = {
            "model": self.settings.asr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_data_uri},
                        }
                    ],
                }
            ],
            "stream": False,
            "asr_options": {
                "language": "zh",
                "enable_itn": True,
            },
        }
        request_started_at = time.perf_counter()
        data = self.network_client.request_json(
            "POST",
            BAILIAN_COMPAT_CHAT_URL,
            headers=_auth_headers(api_key),
            payload=payload,
            timeout=90,
        )
        request_ms = round((time.perf_counter() - request_started_at) * 1000, 1)
        self.last_metrics = {
            "encode_ms": encode_ms,
            "request_ms": request_ms,
        }
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Unexpected ASR response format.") from exc


class DashScopeRecognitionASRClient:
    """Transcribes WAV files through DashScope websocket Recognition."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        model: str | None = None,
    ) -> None:
        self.settings = settings or AppSettings.load()
        self.model = model or self.settings.realtime_asr_model
        self.last_metrics: dict[str, float | str] = {}

    def transcribe(self, wav_path: Path | str) -> str:
        path = Path(wav_path)
        dashscope, Recognition, RecognitionCallback = _import_dashscope_recognition()
        dashscope.api_key = get_dashscope_api_key()

        request_started_at = time.perf_counter()
        recognizer = Recognition(
            model=self.model,
            format="wav",
            sample_rate=self.settings.record_sample_rate,
            callback=RecognitionCallback(),
        )
        result = recognizer.call(str(path))
        request_ms = round((time.perf_counter() - request_started_at) * 1000, 1)
        self.last_metrics = {
            "encode_ms": 0.0,
            "request_ms": request_ms,
            "engine": "dashscope_recognition",
            "model": self.model,
        }

        status_code = getattr(result, "status_code", None)
        if status_code is not None and status_code != HTTPStatus.OK:
            message = getattr(result, "message", "") or getattr(result, "code", "")
            raise RuntimeError(f"Recognition ASR failed: {status_code} {message}")

        text = _recognition_result_text(result)
        if not text:
            raise EmptyRecognitionResult("Recognition ASR returned empty text.")
        return text


class DashScopeStreamingRecognitionASRClient:
    """Streams microphone frames to DashScope Recognition while VAD is recording."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        model: str | None = None,
        start_timeout_seconds: float = 8.0,
    ) -> None:
        self.settings = settings or AppSettings.load()
        self.model = model or self.settings.cloud_streaming_asr_model
        self.last_metrics: dict[str, float | str] = {}
        self._recognizer: Any | None = None
        self._callback: Any | None = None
        self._started_at = 0.0
        self._frame_count = 0
        self._total_bytes = 0
        self._started = False
        self._start_error: BaseException | None = None
        self._ready = threading.Event()
        self._pending_frames: list[bytes] = []
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._start_timeout_seconds = max(0.5, float(start_timeout_seconds))
        self._partial_callback: Callable[[str], None] | None = None

    def set_partial_callback(self, callback: Callable[[str], None] | None) -> None:
        """Receive every changed cloud transcript while PCM is streaming."""
        self._partial_callback = callback

    def start(self) -> None:
        self._open_recognition()

    def start_background(self) -> None:
        threading.Thread(target=self._open_recognition, daemon=True).start()

    def _open_recognition(self) -> None:
        try:
            if self._cancelled.is_set():
                return
            dashscope, Recognition, RecognitionCallback = _import_dashscope_recognition()
            dashscope.api_key = get_dashscope_api_key()
            callback = _StreamingRecognitionCallback(
                RecognitionCallback,
                on_text_changed=self._notify_partial_text,
            )
            self._callback = callback
            self._recognizer = Recognition(
                model=self.model,
                format="pcm",
                sample_rate=self.settings.record_sample_rate,
                callback=callback.callback,
            )
            if self._cancelled.is_set():
                return
            self._started_at = time.perf_counter()
            self._recognizer.start()
            if self._cancelled.is_set():
                self._recognizer.stop()
                return
            self._started = True
            self._flush_pending_frames()
        except BaseException as exc:
            self._start_error = exc
        finally:
            self._ready.set()

    def send_audio_frame(self, frame: bytes) -> None:
        if not frame or self._cancelled.is_set():
            return
        with self._lock:
            if not self._started or self._recognizer is None:
                self._pending_frames.append(frame)
                return
        self._send_ready_frame(frame)

    def finish(self) -> str:
        if not self._ready.wait(timeout=self._start_timeout_seconds):
            self.cancel()
            raise RecognitionStartTimeout(
                "Streaming ASR did not start within "
                f"{self._start_timeout_seconds:.1f}s."
            )
        if self._start_error is not None:
            raise RuntimeError("Streaming ASR failed to start.") from self._start_error
        self._flush_pending_frames()
        if not self._started or self._recognizer is None or self._callback is None:
            raise RuntimeError("Streaming ASR has not started.")

        finish_started_at = time.perf_counter()
        try:
            self._recognizer.stop()
        finally:
            self._started = False
        post_capture_ms = round((time.perf_counter() - finish_started_at) * 1000, 1)
        total_stream_ms = round((time.perf_counter() - self._started_at) * 1000, 1)
        self.last_metrics = {
            "encode_ms": 0.0,
            "request_ms": post_capture_ms,
            "total_stream_ms": total_stream_ms,
            "engine": "dashscope_streaming_recognition",
            "model": self.model,
            "frames": float(self._frame_count),
            "bytes": float(self._total_bytes),
        }
        if self._callback.error is not None:
            raise RuntimeError(
                f"Streaming ASR failed: {self._callback.error}"
            ) from self._callback.error
        text = self._callback.text()
        if not text:
            raise EmptyRecognitionResult("Streaming ASR returned empty text.")
        return text

    def partial_text(self) -> str:
        if self._callback is None:
            return ""
        return self._callback.text()

    def cancel(self) -> None:
        self._cancelled.set()
        if not self._started or self._recognizer is None:
            return
        try:
            self._recognizer.stop()
        except Exception:
            pass
        finally:
            self._started = False

    def _flush_pending_frames(self) -> None:
        with self._lock:
            frames = list(self._pending_frames)
            self._pending_frames.clear()
        for frame in frames:
            self._send_ready_frame(frame)

    def _send_ready_frame(self, frame: bytes) -> None:
        if not self._started or self._recognizer is None:
            return
        self._frame_count += 1
        self._total_bytes += len(frame)
        self._recognizer.send_audio_frame(frame)

    def _notify_partial_text(self, text: str) -> None:
        callback = self._partial_callback
        if callback is None or not text:
            return
        try:
            callback(text)
        except Exception:
            # UI/event observers must never terminate the ASR receiver thread.
            pass


def audio_to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    suffix = path.suffix.lower().lstrip(".") or "wav"
    mime = "wav" if suffix == "wav" else suffix
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:audio/{mime};base64,{encoded}"


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _import_dashscope_recognition() -> tuple[Any, Any, Any]:
    try:
        import dashscope
        from dashscope.audio.asr import Recognition, RecognitionCallback

        return dashscope, Recognition, RecognitionCallback
    except Exception as exc:  # pragma: no cover - optional realtime dependency
        raise RuntimeError(
            "Realtime ASR requires the DashScope SDK. Install it with "
            "`python -m pip install dashscope` or update the virtual environment "
            "from requirements.txt."
        ) from exc


class _StreamingRecognitionCallback:
    def __init__(
        self,
        callback_base: Any,
        *,
        on_text_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.error: BaseException | None = None
        self._final_sentences: list[str] = []
        self._latest_partial = ""
        self._last_emitted_text = ""
        self._on_text_changed = on_text_changed
        self._complete = threading.Event()
        self.callback = self._build_callback(callback_base)

    def _build_callback(self, callback_base: Any) -> Any:
        owner = self

        class Callback(callback_base):
            def on_complete(self) -> None:
                owner._complete.set()

            def on_error(self, result: Any) -> None:
                # DashScope 1.26.2 RecognitionResult.__str__() tries to
                # access a missing ``headers`` attribute, which masks the
                # actual cloud-side ASR error in this receiver thread.
                owner.error = RuntimeError(_recognition_error_summary(result))
                owner._complete.set()

            def on_event(self, result: Any) -> None:
                owner._handle_result(result)

        return Callback()

    def _handle_result(self, result: Any) -> None:
        sentence = result.get_sentence() if hasattr(result, "get_sentence") else None
        if isinstance(sentence, dict):
            self._handle_sentence(sentence)
        elif isinstance(sentence, list):
            for item in sentence:
                if isinstance(item, dict):
                    self._handle_sentence(item)

    def _handle_sentence(self, sentence: dict[str, Any]) -> None:
        text = str(sentence.get("text", "")).strip()
        if not text:
            return
        if sentence.get("end_time") is not None:
            self._final_sentences.append(text)
        else:
            self._latest_partial = text
        combined = self.text()
        if combined and combined != self._last_emitted_text:
            self._last_emitted_text = combined
            if self._on_text_changed is not None:
                self._on_text_changed(combined)

    def text(self) -> str:
        if self._final_sentences:
            return "".join(self._final_sentences).strip()
        return self._latest_partial.strip()


def _recognition_error_summary(result: Any) -> str:
    """Extract stable cloud error fields without calling SDK ``__str__``."""

    def field(name: str) -> str:
        try:
            value = getattr(result, name, None)
        except Exception:
            value = None
        text = str(value or "").strip()
        return text[:240] if text else "unknown"

    return (
        "DashScope streaming recognition error "
        f"status_code={field('status_code')} "
        f"code={field('code')} "
        f"message={field('message')} "
        f"request_id={field('request_id')}"
    )


def _recognition_result_text(result: Any) -> str:
    sentence = result.get_sentence() if hasattr(result, "get_sentence") else None
    if isinstance(sentence, list):
        pieces = [
            str(item.get("text", "")).strip()
            for item in sentence
            if isinstance(item, dict)
        ]
        return "".join(piece for piece in pieces if piece).strip()
    if isinstance(sentence, dict):
        return str(sentence.get("text", "")).strip()

    output = getattr(result, "output", None)
    if isinstance(output, dict):
        raw_sentence = output.get("sentence")
        if isinstance(raw_sentence, list):
            pieces = [
                str(item.get("text", "")).strip()
                for item in raw_sentence
                if isinstance(item, dict)
            ]
            return "".join(piece for piece in pieces if piece).strip()
        if isinstance(raw_sentence, dict):
            return str(raw_sentence.get("text", "")).strip()
    return ""
