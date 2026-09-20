"""Command-line entry point for the Xingbao Companion migration project."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app import XingbaoApp
from core.board_ui_client import BoardUIClient
from core.arm_action_bridge import enable_hand_recognition
from core.game_session_state import GameSessionRegistry
from core.game_speech_server import GameSpeechServer
from core.vision_control_server import VisionControlServer, VisionRuntimeController
from core.settings import AppSettings
from core.voice_events import VoiceEvent
from core.voice_profiles import select_voice_profile
from multimodal.audio_io import (
    BOARD_APLAY_OUTPUT_DEVICE,
    check_realtime_tts_ready,
    interrupt_active_realtime_playback,
)
from multimodal.vision_runtime import VisionProcessBridge, VisionRuntimeConfig


TOUCH_EVENT_ARM_ACTIONS = {
    # 学习、闯关等正向结果：点头肯定。
    "answer_correct": "nod",
    "child_succeeded": "nod",
    "round_completed": "nod",
    "level_completed": "nod",
    "task_completed": "nod",
    "mission_completed": "nod",
    "achievement_unlocked": "nod",
    # 真实桌面与内嵌百宝箱上报的语义事件。
    "game_started": "nod",
    "toolbox_opened": "nod",
    "toolbox_activity_started": "nod",
    "drawing_started": "nod",
    "toolbox_result_saved": "nod",
    "reward_received": "nod",
    # 失败或重试默认只给语音鼓励，不自动摇头；需要时由触控显式发出
    # touch_shake_head / shake_head_requested，避免连续做题时反复物理动作。
    # 创作完成：鞠躬表达欣赏。
    "drawing_completed": "bow",
    "painting_completed": "bow",
    "artwork_completed": "bow",
    "craft_completed": "bow",
    # 一局结束不再重复击掌。触控按钮可直接使用这些高层事件；绝不会传递
    # 舵机角度或时序。
    "touch_nod": "nod",
    "nod_requested": "nod",
    "touch_shake_head": "shake_head",
    "shake_head_requested": "shake_head",
    "touch_bow": "bow",
    "bow_requested": "bow",
    "touch_mouth": "mouth",
    "mouth_requested": "mouth",
    "mouth_open_requested": "mouth",
    "mouth_close_requested": "mouth",
    "touch_high_five": "high_five",
    "high_five_requested": "high_five",
    # Legacy event names are accepted so older touch packages do not lose the
    # interaction, but every runtime action is now the child-facing high-five.
    "touch_handshake": "high_five",
    "handshake_requested": "high_five",
}


def arm_action_for_touch_event(event_name: object) -> str:
    """Map only explicit touch/game completion events to a reviewed arm action."""
    return TOUCH_EVENT_ARM_ACTIONS.get(str(event_name or "").strip(), "")


def is_posture_vision_event(message: dict[str, object]) -> bool:
    """Return whether a vision message is specifically a distance/posture alert."""
    payload = message.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    event_name = str(payload.get("event") or payload.get("state") or "").strip()
    return event_name in {"vision_close", "face_too_close", "posture_warning"}


def vision_emotion_memory_update(
    message: dict[str, object],
) -> dict[str, str] | None:
    """Map one thresholded emotion event to the existing safe memory schema."""
    if str(message.get("type") or "").strip() != "vision_state":
        return None
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return None
    state = str(payload.get("state") or payload.get("event") or "").strip()
    if state != "child_emotion_detected":
        return None
    emotion = str(payload.get("emotion") or "").strip().lower()
    if emotion not in {
        "happiness",
        "sadness",
        "anger",
        "surprise",
        "fear",
        "disgust",
        "contempt",
        "neutral",
    }:
        return None
    confidence = payload.get("confidence", 1.0)
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        if float(confidence) < 0.60:
            return None
    return {"recent_mood": emotion}


def start_managed_vision_runtime(
    *,
    event_handler: Callable[[dict[str, object]], None],
    log_handler: Callable[[object], None],
    restart_delay_seconds: float,
    config_factory: Callable[[], Any] = VisionRuntimeConfig.from_environment,
    bridge_factory: Callable[[Callable[[dict[str, object]], None], Any, Callable[[object], None], float], Any] | None = None,
    control_server_factory: Callable[..., Any] = VisionControlServer,
    control_port: int = 8768,
) -> dict[str, Any]:
    """Start the center-owned vision bridge and its loopback control service."""
    if bridge_factory is None:
        def bridge_factory(
            handler: Callable[[dict[str, object]], None],
            config: Any,
            logger: Callable[[object], None],
            delay: float,
        ) -> VisionProcessBridge:
            return VisionProcessBridge(
                handler,
                config=config,
                log_handler=logger,
                restart_delay_seconds=delay,
            )

    controller = VisionRuntimeController(
        config_factory,
        lambda config: bridge_factory(event_handler, config, log_handler, restart_delay_seconds),
    )
    startup = controller.handle("start")
    server = None
    control_error = ""
    try:
        server = control_server_factory(
            controller,
            host="127.0.0.1",
            port=int(control_port),
        ).start()
    except (OSError, ValueError) as exc:
        control_error = "{}:{}".format(type(exc).__name__, exc)
        log_handler("vision_control_server_unavailable:{}".format(control_error))
    return {
        "controller": controller,
        "server": server,
        "startup": startup,
        "control_error": control_error,
    }


def scene_for_idle_vision_emotion(emotion: object) -> int:
    """Map only approved idle visual emotions to touch-scene IDs."""
    normalized = str(emotion or "").strip().lower()
    if normalized == "happiness":
        return 2
    if normalized in {"sadness", "anger"}:
        return 3
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Xingbao Companion desktop companion pet system."
    )
    parser.add_argument(
        "--text-demo",
        action="store_true",
        help="Run the placeholder text demo through the session layer.",
    )
    parser.add_argument(
        "--prompt-preview",
        action="store_true",
        help="Print the current system prompt built from local config and memory.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List local audio devices.",
    )
    parser.add_argument(
        "--list-output-devices",
        action="store_true",
        help="List output-capable local audio devices.",
    )
    parser.add_argument(
        "--test-output-device",
        type=int,
        default=None,
        help="Play a local chime through one output device index.",
    )
    parser.add_argument(
        "--test-board-output",
        action="store_true",
        help="Configure lahaina mixer and play a local chime through board ALSA output.",
    )
    parser.add_argument(
        "--list-voice-profiles",
        action="store_true",
        help="List configured TTS voice profiles.",
    )
    parser.add_argument(
        "--voice-profile",
        default="",
        help="Select a configured TTS voice profile id for this run.",
    )
    parser.add_argument(
        "--voice-once",
        action="store_true",
        help="Run one real voice turn. Requires audio dependencies and DASHSCOPE_API_KEY.",
    )
    parser.add_argument(
        "--test-wake-word",
        action="store_true",
        help="Wait for one local offline wake-word detection, then exit.",
    )
    parser.add_argument(
        "--test-wake-wav",
        default="",
        help="Run local offline wake-word detection against one WAV file, then exit.",
    )
    parser.add_argument(
        "--wake-loop",
        action="store_true",
        help="Run continuous voice turns gated by local offline wake-word detection.",
    )
    parser.add_argument(
        "--wake-chat",
        action="store_true",
        help="Run wake-gated multi-turn chat windows without repeating the wake word.",
    )
    parser.add_argument(
        "--max-wake-turns",
        type=int,
        default=None,
        help="Optional wake-loop turn limit for verification.",
    )
    parser.add_argument(
        "--max-wake-sessions",
        type=int,
        default=None,
        help="Optional wake-chat session limit for verification.",
    )
    parser.add_argument(
        "--max-chat-turns",
        type=int,
        default=None,
        help="Optional follow-up turn limit; 0 means unlimited.",
    )
    parser.add_argument(
        "--follow-up-timeout",
        type=float,
        default=None,
        help="Seconds to wait for follow-up speech inside --wake-chat.",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Skip TTS playback during --voice-once.",
    )
    parser.add_argument(
        "--no-quick-ack",
        action="store_true",
        help="Skip quick acknowledgement audio during --voice-once.",
    )
    parser.add_argument(
        "--no-wake-ack",
        action="store_true",
        help="Skip the local wake acknowledgement chime during wake modes.",
    )
    parser.add_argument(
        "--local-tts-fallback",
        action="store_true",
        help="Use Windows local speech if cloud TTS fails.",
    )
    parser.add_argument(
        "--no-streaming-response",
        action="store_true",
        help="Disable streaming LLM response and sentence-level TTS playback.",
    )
    parser.add_argument(
        "--realtime-tts",
        dest="realtime_tts",
        action="store_true",
        default=True,
        help="Use DashScope WebSocket TTS (enabled by default).",
    )
    parser.add_argument(
        "--no-realtime-tts",
        dest="realtime_tts",
        action="store_false",
        help="Use HTTP TTS instead of the default WebSocket streaming TTS.",
    )
    parser.add_argument(
        "--realtime-asr",
        action="store_true",
        help="Use DashScope WebSocket Recognition ASR instead of compatible HTTP ASR.",
    )
    parser.add_argument(
        "--streaming-asr",
        action="store_true",
        help="Stream microphone PCM frames while recording (backend from XINGBAO_ASR_BACKEND).",
    )
    parser.add_argument(
        "--realtime-asr-model",
        default="",
        help="Override the cloud streaming ASR model for --streaming-asr.",
    )
    parser.add_argument(
        "--check-realtime-tts",
        action="store_true",
        help="Check local prerequisites for --realtime-tts without recording or calling TTS.",
    )
    parser.add_argument(
        "--prepare-demo-tts-cache",
        action="store_true",
        help="Pre-synthesize fixed demo game utterances for faster playback.",
    )
    parser.add_argument(
        "--prewarm-game-tts-cache",
        action="store_true",
        help="Warm the fixed game speech cache in the background after services start.",
    )
    parser.add_argument(
        "--check-game-tts-cache",
        action="store_true",
        help="Inspect the fixed game speech cache without making network calls.",
    )
    parser.add_argument(
        "--show-voice-events",
        action="store_true",
        help="Print voice pipeline events for debugging wake, ASR, LLM, and TTS flow.",
    )
    parser.add_argument(
        "--low-latency-voice",
        action="store_true",
        help="Use shorter VAD timing for faster voice turns.",
    )
    parser.add_argument(
        "--listen-timeout",
        type=float,
        default=0.0,
        help="Seconds to wait for speech before stopping a single voice capture.",
    )
    parser.add_argument(
        "--vad-manual-threshold",
        type=float,
        default=0.0,
        help="Override the RMS threshold used to start speech capture.",
    )
    parser.add_argument(
        "--vad-end-silence-ms",
        type=int,
        default=0,
        help="Override the silent milliseconds that finish one voice turn (0 keeps the selected VAD default).",
    )
    parser.add_argument(
        "--vad-debug-level",
        action="store_true",
        help="Print live microphone RMS levels while waiting for speech.",
    )
    parser.add_argument(
        "--show-wake-level",
        action="store_true",
        help="Print wake-word microphone input level while waiting for wake word.",
    )
    parser.add_argument(
        "--wake-rms-interval",
        type=float,
        default=0.25,
        help="Seconds between live wake-word RMS/peak reports when wake level is shown.",
    )
    parser.add_argument(
        "--wake-word-threshold",
        type=float,
        default=None,
        help="Temporarily override wake-word keyword threshold for this run.",
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=None,
        help="Optional sounddevice input device index for --voice-once.",
    )
    parser.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="Optional sounddevice output device index for TTS playback.",
    )
    parser.add_argument(
        "--board-audio-output",
        action="store_true",
        help="Use lahaina ALSA aplay backend for TTS playback instead of sounddevice output.",
    )
    parser.add_argument(
        "--record-sample-rate",
        type=int,
        default=None,
        help="Override microphone capture sample rate for this run.",
    )
    parser.add_argument(
        "--serial-port",
        default="",
        help="Optional serial port for sanitized high-level board actions.",
    )
    parser.add_argument(
        "--send-action",
        default="",
        help="Send one sanitized high-level action to --serial-port, then exit.",
    )
    parser.add_argument(
        "--color-block-demo",
        action="store_true",
        help="Run a non-graphical scripted demo of the color block mini game.",
    )
    parser.add_argument(
        "--color-block-game",
        action="store_true",
        help="Launch the desktop UI for the color block mini game.",
    )
    parser.add_argument(
        "--color-block-web",
        action="store_true",
        help="Print the standalone browser-playable color block game UI path.",
    )
    parser.add_argument(
        "--kids-visual-tools",
        action="store_true",
        help="Launch the migrated white-box kids visual toolbox home screen.",
    )
    parser.add_argument(
        "--kids-visual-tool",
        default="",
        help="Launch one migrated white-box visual tool by number, title, or slug.",
    )
    parser.add_argument(
        "--list-kids-visual-tools",
        action="store_true",
        help="List the migrated white-box visual tools as JSON.",
    )
    parser.add_argument(
        "--coordinate-text",
        default="",
        help="Plan one full expression/TTS/tool coordination turn from child text.",
    )
    parser.add_argument(
        "--coordinate-event-json",
        default="",
        help="Plan one full expression/TTS coordination turn from a module event JSON.",
    )
    parser.add_argument(
        "--coordinate-event-file",
        default="",
        help="Plan one full expression/TTS coordination turn from a module event JSON file.",
    )
    parser.add_argument(
        "--coordinate-state-json",
        default="",
        help="Plan one coordination turn from a reserved mini-game or vision state JSON.",
    )
    parser.add_argument(
        "--coordinate-state-file",
        default="",
        help="Plan one coordination turn from a reserved mini-game or vision state JSON file.",
    )
    parser.add_argument(
        "--game-command-json",
        default="",
        help="Run one fixed-intent game_command JSON through the game adapter and coordination trace.",
    )
    parser.add_argument(
        "--game-command-file",
        default="",
        help="Run one fixed-intent game_command JSON file through the game adapter and coordination trace.",
    )
    parser.add_argument(
        "--coordinate-color-block-command",
        default="",
        help="Run one color block voice command through game rules and coordination trace.",
    )
    parser.add_argument(
        "--coordinate-apply",
        action="store_true",
        help="Apply coordinated output to memory and screen/action state.",
    )
    parser.add_argument(
        "--coordinate-launch",
        action="store_true",
        help="Actually launch the requested computer-side tool for --coordinate-text.",
    )
    parser.add_argument(
        "--board-ui",
        action="store_true",
        help="Send coordinated assistant_output to the touch desktop NDJSON bridge.",
    )
    parser.add_argument(
        "--board-ui-host",
        default="127.0.0.1",
        help="Touch desktop NDJSON bridge host for --board-ui.",
    )
    parser.add_argument(
        "--board-ui-port",
        type=int,
        default=8765,
        help="Touch desktop NDJSON bridge port for --board-ui.",
    )
    parser.add_argument(
        "--board-ui-timeout",
        type=float,
        default=3.0,
        help="Socket timeout in seconds for --board-ui.",
    )
    parser.add_argument(
        "--game-speech",
        action="store_true",
        help="Accept touch-game speech_request messages and play them through central TTS.",
    )
    parser.add_argument(
        "--game-speech-host",
        default="127.0.0.1",
        help="Loopback host for the game-to-central speech service.",
    )
    parser.add_argument(
        "--game-speech-port",
        type=int,
        default=8766,
        help="Loopback port for the game-to-central speech service.",
    )
    parser.add_argument(
        "--vision-runtime",
        action="store_true",
        help="Run the managed camera vision process and route its high-level events through central coordination.",
    )
    parser.add_argument(
        "--expression-demo",
        action="store_true",
        help="Run a scripted demo of Xingbao's expression dispatcher.",
    )
    parser.add_argument(
        "--expression-event-json",
        default="",
        help="Handle one module collaboration event JSON and print Xingbao expression output.",
    )
    parser.add_argument(
        "--expression-event-file",
        default="",
        help="Handle one module collaboration event JSON file and print Xingbao expression output.",
    )
    parser.add_argument(
        "--expression-apply",
        action="store_true",
        help="Apply expression output to memory and screen/action state.",
    )
    parser.add_argument(
        "--expression-speak",
        action="store_true",
        help="Apply expression output and play TTS for speak_text.",
    )
    parser.add_argument(
        "--growth-guidance",
        action="store_true",
        help="Route expression events through the growth guidance layer.",
    )
    return parser.parse_args()


def format_voice_event(event: VoiceEvent) -> str:
    """Return a compact one-line voice event for CLI debugging.

    Real-time ASR transcripts are intentionally included when voice-event
    logging is enabled, so operators can inspect the same result in both the
    voice log and the local Sherpa streaming log.
    """
    data_dict = dict(event.data)
    if event.type == "camera_snapshot_ready":
        data_dict.pop("data_uri", None)
    data = json.dumps(data_dict, ensure_ascii=False, sort_keys=True)
    return f"[voice] {event.type} {data}"


def print_voice_event(event: VoiceEvent) -> None:
    print(format_voice_event(event))


def build_voice_event_handler(
    *,
    show_voice_events: bool,
    board_ui_client: BoardUIClient | None,
):
    """Return an event handler that mirrors streaming ASR text onto the UI."""
    last_partial_text = ""
    last_llm_text = ""
    llm_stream_active = False
    show_realtime_result = False
    partial_lock = threading.Lock()

    def handle_voice_event(event: VoiceEvent) -> None:
        nonlocal last_partial_text, last_llm_text, llm_stream_active, show_realtime_result
        if show_voice_events:
            if event.type == "camera_snapshot_ready":
                print(
                    "[voice] camera_snapshot_ready width={} height={}".format(
                        event.data.get("width"), event.data.get("height")
                    ),
                    flush=True,
                )
            else:
                print_voice_event(event)
        if board_ui_client is None:
            return

        if event.type == "camera_snapshot_ready":
            try:
                board_ui_client.send_ui_command(
                    {
                        "name": "camera_snapshot",
                        "action": "show",
                        "data_uri": str(event.data.get("data_uri") or ""),
                        "width": int(event.data.get("width") or 0),
                        "height": int(event.data.get("height") or 0),
                        "mirror": bool(event.data.get("mirror", True)),
                    },
                    screen_text="",
                    expression="thinking",
                    led_mode="warm_breath",
                    duration_ms=30000,
                    subtitle_priority="dialogue",
                )
            except OSError as exc:
                if show_voice_events:
                    print(f"[voice] camera_snapshot_ui_failed {type(exc).__name__}: {exc}")
            return

        if event.type == "camera_snapshot_clear":
            try:
                board_ui_client.send_ui_command(
                    {"name": "camera_snapshot", "action": "clear"},
                    screen_text="",
                    expression="thinking",
                    led_mode="warm_breath",
                    duration_ms=30000,
                    subtitle_priority="dialogue",
                )
            except OSError as exc:
                if show_voice_events:
                    print(f"[voice] camera_snapshot_ui_failed {type(exc).__name__}: {exc}")
            return

        if event.type == "realtime_query_started":
            tool_names = {
                str(name)
                for name in event.data.get("tools", [])
            }
            # The board only exposes lookup results for live time and weather.
            # Ordinary chat keeps its compact default "正在想" status instead
            # of mirroring every LLM token onto the subtitle area.
            show_realtime_result = bool(
                tool_names
                & {
                    "get_current_time",
                    "get_current_weather",
                    "get_weather_forecast",
                    "get_historical_weather",
                    "get_weather_alert",
                    "get_minutely_precipitation",
                    "get_lifestyle_indices",
                    "get_air_quality",
                    "inspect_current_camera",
                    "show_reference_image",
                }
            )
            with partial_lock:
                last_llm_text = ""
                llm_stream_active = False
            if not show_realtime_result:
                return
            try:
                board_ui_client.send_ui_command(
                    None,
                    screen_text=str(event.data.get("subtitle") or "[[SEARCH]] 正在查询中"),
                    expression="thinking",
                    led_mode="warm_breath",
                    duration_ms=30000,
                    subtitle_priority="dialogue",
                )
            except OSError as exc:
                if show_voice_events:
                    print(f"[voice] realtime_query_ui_failed {type(exc).__name__}: {exc}")
            return

        if event.type == "llm_delta":
            if not show_realtime_result:
                return
            delta = str(event.data.get("text") or "")
            if not delta:
                return
            with partial_lock:
                # A new ASR turn (or tool lookup) marks the following first
                # delta as a new answer.  Never append it to the previous
                # round's subtitle.
                if not llm_stream_active:
                    last_llm_text = ""
                    llm_stream_active = True
                last_llm_text += delta
                subtitle = last_llm_text
            try:
                board_ui_client.send_ui_command(
                    None,
                    screen_text=subtitle,
                    expression="thinking",
                    led_mode="warm_breath",
                    duration_ms=30000,
                    subtitle_priority="dialogue",
                )
            except OSError as exc:
                if show_voice_events:
                    print(f"[voice] llm_delta_ui_failed {type(exc).__name__}: {exc}")
            return

        if event.type == "asr_final":
            # Some ASR backends may produce only a final result.  It still
            # establishes a new response boundary even when no partial text
            # was shown first.
            with partial_lock:
                llm_stream_active = False
                last_llm_text = ""
                show_realtime_result = False
            return

        if event.type != "asr_partial":
            return

        transcript = str(event.data.get("text") or "").strip()
        if not transcript:
            return
        with partial_lock:
            # Listening to a fresh utterance starts a new answer boundary.
            llm_stream_active = False
            last_llm_text = ""
            show_realtime_result = False
            if transcript == last_partial_text:
                return
            last_partial_text = transcript
        try:
            # This replaces the listening prompt as soon as Sherpa returns
            # the first partial result, then refreshes for every new partial.
            board_ui_client.send_ui_command(
                None,
                screen_text=transcript,
                expression="curious",
                led_mode="blue_breath",
                duration_ms=30000,
                subtitle_priority="dialogue",
            )
        except OSError as exc:
            if show_voice_events:
                print(f"[voice] asr_partial_ui_failed {type(exc).__name__}: {exc}")

    return handle_voice_event


def main() -> int:
    args = parse_args()
    vision_log_path = Path("logs/xingbao-vision-runtime.log")
    vision_log_lock = threading.Lock()

    def write_vision_log(line: object) -> None:
        """Keep child-vision diagnostics out of the voice conversation log."""
        text = str(line or "").strip()
        if not text:
            return
        try:
            vision_log_path.parent.mkdir(parents=True, exist_ok=True)
            with vision_log_lock, vision_log_path.open("a", encoding="utf-8") as handle:
                handle.write("{} {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except OSError:
            # Vision diagnostics must never prevent the main voice service
            # from starting or handling a child-facing event.
            pass
    if args.vision_runtime and not args.game_speech:
        raise SystemExit("--vision-runtime requires --game-speech.")
    if args.board_audio_output:
        args.output_device = BOARD_APLAY_OUTPUT_DEVICE
    if args.realtime_tts and args.no_streaming_response:
        raise SystemExit("--realtime-tts requires streaming response; remove --no-streaming-response.")
    if args.check_realtime_tts:
        try:
            if args.voice_profile:
                settings = AppSettings.load()
                status = check_realtime_tts_ready(
                    settings,
                    voice_profile=select_voice_profile(settings, args.voice_profile),
                )
            else:
                status = check_realtime_tts_ready()
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        app = XingbaoApp(voice_profile_id=args.voice_profile) if args.voice_profile else XingbaoApp()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if args.prepare_demo_tts_cache:
        print(json.dumps(app.prepare_demo_tts_cache(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.check_game_tts_cache:
        report = app.game_speech_cache.inspect_manifest()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["ok"] else 1
    board_ui_client = (
        BoardUIClient(
            host=args.board_ui_host,
            port=args.board_ui_port,
            timeout=args.board_ui_timeout,
        )
        if args.board_ui
        else None
    )
    game_speech_server = None
    if args.game_speech:
        game_session_registry = GameSessionRegistry()
        demo_game_state = {
            "difficulty_spoken": False,
            "answer_count": 0,
            "posture_spoken": False,
        }
        demo_game_state_lock = threading.Lock()
        vision_memory_lock = threading.Lock()
        dispatched_support_ids: set[str] = set()
        dispatched_support_lock = threading.Lock()
        demo_game_phrases = {
            "difficulty_selected": {
                "text": "\u96be\u5ea6\u9009\u597d\u4e86\uff0c\u6211\u4eec\u5f00\u59cb\u7b2c\u4e00\u9898\u3002",
                "screen_text": "\u5f00\u59cb\u7b2c\u4e00\u9898",
                "emotion": "thinking",
                "arm_action": "stay_still",
            },
            "answer_correct": {
                "text": "\u592a\u68d2\u4e86\uff0c\u4f60\u7b54\u5bf9\u4e86\u3002",
                "screen_text": "\u7b54\u5bf9\u5566",
                "emotion": "happy",
                "arm_action": "stay_still",
            },
            "answer_wrong": {
                "text": "\u6ca1\u5173\u7cfb\uff0c\u8fd9\u4e00\u9898\u6211\u4eec\u518d\u8bd5\u4e00\u6b21\u3002",
                "screen_text": "\u518d\u8bd5\u4e00\u6b21",
                "emotion": "encouraging",
                "arm_action": "stay_still",
            },
            "posture_fallback": {
                "text": "\u5c0f\u670b\u53cb\uff0c\u5e94\u8be5\u8c03\u6574\u4e00\u4e0b\u59ff\u52bf\uff0c\u79bb\u5c4f\u5e55\u7a0d\u5fae\u8fdc\u4e00\u70b9\uff0c\u4e5f\u8bb0\u5f97\u559d\u6c34\u54e6\u3002",
                "screen_text": "\u8c03\u6574\u59ff\u52bf",
                "emotion": "thinking",
                "arm_action": "stay_still",
            },
            "posture_warning": {
                "text": "\u5c0f\u670b\u53cb\uff0c\u4f60\u79bb\u5c4f\u5e55\u6709\u70b9\u8fd1\uff0c\u7a0d\u5fae\u5750\u8fdc\u4e00\u70b9\uff0c\u4e5f\u8bb0\u5f97\u559d\u6c34\u54e6\u3002",
                "screen_text": "\u6ce8\u610f\u8ddd\u79bb",
                "emotion": "thinking",
                "arm_action": "shake_head",
            },
        }

        def play_demo_game_phrase(
            *,
            intent: str,
            text: str,
            screen_text: str,
            emotion: str,
            arm_action: str = "stay_still",
            source: str = "demo_game",
        ) -> None:
            phrase = demo_game_phrases.get(intent)
            if phrase is not None:
                text = str(phrase["text"])
                screen_text = str(phrase["screen_text"])
                emotion = str(phrase["emotion"])
                arm_action = str(phrase["arm_action"])
            message = {
                "type": "xingbao_expression_request",
                "source": source,
                "priority": 1,
                "payload": {
                    "intent": intent,
                    "text": text,
                    "screen_text": screen_text,
                    "emotion": emotion,
                    "tts": True,
                    "interrupt_policy": "queue",
                    "feedback": {
                        "screen_expression": "smile",
                        "arm_action": arm_action,
                    },
                },
            }
            raw = json.dumps(message, ensure_ascii=False)
            app.run_coordinated_event_json(
                raw,
                apply_output=True,
                no_tts=False,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                board_ui_client=board_ui_client,
            )

        def schedule_posture_fallback() -> None:
            def worker() -> None:
                time.sleep(3.0)
                with demo_game_state_lock:
                    if demo_game_state["posture_spoken"]:
                        return
                    demo_game_state["posture_spoken"] = True
                print("[game-event] fallback=posture_adjustment", flush=True)
                play_demo_game_phrase(
                    intent="posture_fallback",
                    text="小朋友，应该调整一下姿势，离屏幕稍微远一点，也记得喝水哦。",
                    screen_text="调整姿势",
                    emotion="thinking",
                    source="demo_cv_fallback",
                )

            threading.Thread(
                target=worker,
                name="demo-posture-fallback",
                daemon=True,
            ).start()

        def dispatch_touch_arm_action(event_name: str) -> None:
            """Send a fixed high-level expression for a discrete game event.

            The UI and game runtime cannot send servo positions, speeds, or
            arbitrary sequences: this boundary forwards only a reviewed action
            name to the isolated arm service.
            """
            arm_action = arm_action_for_touch_event(event_name)
            if not arm_action or board_ui_client is None:
                return
            if arm_action == "high_five":
                try:
                    enabled = enable_hand_recognition()
                    if bool(enabled.get("ok")):
                        print("[game-event] high_five vision_enabled=true", flush=True)
                        return
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    print(
                        f"[game-event] high_five vision_enable_failed={type(exc).__name__}: {exc}",
                        flush=True,
                    )
            try:
                result = board_ui_client.send_arm_action(arm_action)
            except (OSError, RuntimeError, ValueError) as exc:
                print(
                    f"[game-event] arm_action={arm_action} dispatch_failed={type(exc).__name__}: {exc}",
                    flush=True,
                )
                return
            print(
                "[game-event] arm_action={} dispatched ok={}".format(
                    arm_action,
                    bool(result.get("ok")),
                ),
                flush=True,
            )

        def handle_game_event_message(message: dict[str, object]) -> None:
            payload = message.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            memory_update = vision_emotion_memory_update(message)
            if memory_update is not None and app._conversation_audio_active():
                print(
                    "[vision-emotion] dropped reason=conversation_active emotion={}".format(
                        memory_update.get("recent_mood", "")
                    ),
                    flush=True,
                )
                return
            if memory_update is not None:
                app.observe_vision_state(message)
                try:
                    with vision_memory_lock:
                        memory = app.session.memory_manager.update(memory_update)
                    print(
                        "[vision-memory] recent_mood={} persisted=true".format(
                            memory.get("recent_mood", "")
                        ),
                        flush=True,
                    )
                except (OSError, ValueError) as exc:
                    print(
                        "[vision-memory] persisted=false error={}:{}".format(
                            type(exc).__name__,
                            exc,
                        ),
                        flush=True,
                    )
            if str(message.get("type") or "") == "game_state":
                update = game_session_registry.apply_game_state(message)
                print(
                    "[game-state] status={} revision={} session={}".format(
                        update.status, update.revision, update.session_key
                    ),
                    flush=True,
                )
                if update.accepted:
                    prefetch_texts = payload.get("prefetch_texts")
                    if isinstance(prefetch_texts, list):
                        count = app.prefetch_game_tts_texts(
                            [str(text) for text in prefetch_texts]
                        )
                        if count:
                            print(
                                "[game-speech] scheduled {} future prompt(s)".format(count),
                                flush=True,
                            )
                    state = payload.get("state")
                    if not isinstance(state, dict):
                        state = {}
                    support = state.get("companion_support")
                    if not isinstance(support, dict):
                        support = {}
                    support_id = str(support.get("support_id") or "").strip()
                    if (
                        support_id
                        and str(support.get("phase") or "") == "high_five"
                        and str(support.get("action") or "") == "high_five"
                    ):
                        with dispatched_support_lock:
                            should_dispatch = support_id not in dispatched_support_ids
                            if should_dispatch:
                                dispatched_support_ids.add(support_id)
                        if should_dispatch:
                            dispatch_touch_arm_action("high_five_requested")
                return
            event_name = str(payload.get("event") or payload.get("state") or "")
            if str(message.get("type") or "") == "vision_state":
                write_vision_log(
                    "voice_receiver_received state={} payload={}".format(
                        event_name,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    )
                )
            if event_name:
                print(
                    "[game-event] event={} payload={}".format(
                        event_name,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    ),
                    flush=True,
                )
            if event_name == "synthetic_wake":
                wake = app.request_synthetic_wake()
                print(
                    "[synthetic-wake] ok={} reason={}".format(
                        bool(wake.get("ok")), wake.get("reason", "")
                    ),
                    flush=True,
                )
                if board_ui_client is not None:
                    try:
                        # The image overlay belongs to the active turn.  A
                        # manual stop must remove either a camera or web-image
                        # preview immediately, before showing its status.
                        board_ui_client.send_ui_command(
                            {"name": "camera_snapshot", "action": "clear"},
                            screen_text="",
                            expression="neutral",
                            led_mode="off",
                            duration_ms=2500,
                            subtitle_priority="dialogue",
                        )
                        board_ui_client.send_ui_command(
                            None,
                            screen_text=(
                                "星宝在这儿"
                                if wake.get("ok")
                                else "星宝正在和你聊天"
                            ),
                            expression="smile",
                            led_mode="warm_breath",
                            duration_ms=2500,
                        )
                    except OSError:
                        pass
                return
            if event_name == "conversation_stop":
                stopped = app.request_conversation_stop()
                print(
                    "[conversation-stop] ok={} reason={}".format(
                        bool(stopped.get("ok")), stopped.get("reason", "")
                    ),
                    flush=True,
                )
                if board_ui_client is not None:
                    try:
                        # Stop owns every transient conversation surface:
                        # remove a camera/web-image preview first, then clear
                        # any LLM/vision GIF back to the default mascot.
                        board_ui_client.send_ui_command(
                            {"name": "camera_snapshot", "action": "clear"},
                            screen_text="",
                            expression="neutral",
                            led_mode="off",
                            duration_ms=2500,
                            subtitle_priority="dialogue",
                        )
                        board_ui_client.send_xingbao_scene(
                            0,
                            source="manual_stop",
                        )
                        board_ui_client.send_ui_command(
                            None,
                            screen_text=(
                                "正在停止本次对话"
                                if stopped.get("ok")
                                else "当前没有正在进行的对话"
                            ),
                            expression="neutral",
                            led_mode="off",
                            duration_ms=2500,
                        )
                    except OSError:
                        pass
                return
            if event_name == "drink_reminder_reset":
                cleared = app.clear_pending_drink_reminder()
                write_vision_log(
                    "hydration_reset pending_drink_reminder_cleared={}".format(
                        cleared
                    )
                )
                return
            if event_name == "guided_expression_recover":
                # The dinosaur guided script has been retired; ignore stale
                # bridge events from an older touch UI without opening any
                # recovery conversation.
                return
            if event_name == "drawing_completed":
                if board_ui_client is not None:
                    try:
                        board_ui_client.send_ui_command(
                            None,
                            screen_text="画作已保存",
                            expression="smile",
                            led_mode="warm_breath",
                            duration_ms=2500,
                        )
                    except OSError:
                        pass
                return
            if event_name == "answer_result":
                event_name = "answer_correct" if bool(payload.get("correct")) else "answer_wrong"
                print(f"[game-event] normalized answer_result -> {event_name}", flush=True)
            event_name = {
                "child_succeeded": "answer_correct",
                "child_made_mistake": "answer_wrong",
                "round_completed": "answer_correct",
                "game_answer_correct": "answer_correct",
            }.get(event_name, event_name)
            dispatch_touch_arm_action(event_name)
            # Keep the existing verbal completion response while preserving
            # Game completion is normalized to a positive result without
            # dispatching another high-five.
            if event_name == "game_completed":
                event_name = "answer_correct"
            if event_name == "difficulty_selected":
                with demo_game_state_lock:
                    if demo_game_state["difficulty_spoken"]:
                        print("[game-event] ignored duplicate difficulty_selected", flush=True)
                        return
                    demo_game_state["difficulty_spoken"] = True
                    demo_game_state["answer_count"] = 0
                    demo_game_state["posture_spoken"] = False
                play_demo_game_phrase(
                    intent="difficulty_selected",
                    text="难度选好了，我们开始第一题。",
                    screen_text="开始第一题",
                    emotion="thinking",
                    source=str(message.get("source") or "demo_game"),
                )
                return
            if event_name in {"answer_correct", "answer_wrong"}:
                with demo_game_state_lock:
                    demo_game_state["answer_count"] += 1
                    answer_index = int(demo_game_state["answer_count"])
                if event_name == "answer_correct":
                    play_demo_game_phrase(
                        intent="answer_correct",
                        text="太棒了，你答对了。",
                        screen_text="答对啦",
                        emotion="happy",
                        source=str(message.get("source") or "demo_game"),
                    )
                else:
                    play_demo_game_phrase(
                        intent="answer_wrong",
                        text="没关系，这一题我们再试一次。",
                        screen_text="再试一次",
                        emotion="encouraging",
                        source=str(message.get("source") or "demo_game"),
                    )
                    if answer_index >= 2:
                        schedule_posture_fallback()
                return
            if is_posture_vision_event(message):
                # This is a safety/health cue, not ordinary queued dialogue.
                # VisionEventAdapter already emits this only on a fresh
                # continuous-too-close episode, and VisionProcessBridge adds
                # a cooldown.  Do not retain a game-session-wide flag here:
                # it would suppress every later valid 5-second episode.
                # A vision reminder is auxiliary audio. It must never cancel
                # an active child conversation; the app gate will still send
                # its screen/action output while dropping the speech.
                preempted = (
                    False
                    if app._conversation_audio_active()
                    else interrupt_active_realtime_playback()
                )
                print(
                    "[vision-audio] face_too_close priority_preempted={}".format(
                        preempted
                    ),
                    flush=True,
                )
                write_vision_log(
                    "voice_reminder_dispatch state=face_too_close priority_preempted={}".format(
                        preempted
                    )
                )
                play_demo_game_phrase(
                    intent="posture_warning",
                    text="小朋友，你离屏幕有点近，稍微坐远一点，也记得喝水哦。",
                    screen_text="注意距离",
                    emotion="thinking",
                    arm_action="shake_head",
                    source=str(message.get("source") or "vision"),
                )
                return
            fixed_demo_events = {
                "answer_correct": {
                    "text": "太棒了，你答对了。",
                    "screen_text": "答对啦",
                    "emotion": "happy",
                },
                "answer_wrong": {
                    "text": "没关系，这一题我们再试一次。",
                    "screen_text": "再试一次",
                    "emotion": "encouraging",
                },
                "game_entered": {
                    "text": "请选择一个游戏。选好以后，再选一个难度。",
                    "screen_text": "选择游戏",
                    "emotion": "smile",
                },
                "difficulty_selected": {
                    "text": "难度选好了，我们开始第一题。",
                    "screen_text": "开始第一题",
                    "emotion": "thinking",
                },
            }
            fixed_demo_events.update(
                {
                    "answer_correct": {
                        "text": "\u592a\u68d2\u4e86\uff0c\u4f60\u7b54\u5bf9\u4e86\u3002",
                        "screen_text": "\u7b54\u5bf9\u5566",
                        "emotion": "happy",
                    },
                    "answer_wrong": {
                        "text": "\u6ca1\u5173\u7cfb\uff0c\u8fd9\u4e00\u9898\u6211\u4eec\u518d\u8bd5\u4e00\u6b21\u3002",
                        "screen_text": "\u518d\u8bd5\u4e00\u6b21",
                        "emotion": "encouraging",
                    },
                    "game_entered": {
                        "text": "\u8bf7\u9009\u62e9\u4e00\u4e2a\u6e38\u620f\uff0c\u518d\u9009\u62e9\u96be\u5ea6\u3002",
                        "screen_text": "\u9009\u62e9\u6e38\u620f",
                        "emotion": "smile",
                    },
                    "difficulty_selected": {
                        "text": "\u96be\u5ea6\u9009\u597d\u4e86\uff0c\u6211\u4eec\u5f00\u59cb\u7b2c\u4e00\u9898\u3002",
                        "screen_text": "\u5f00\u59cb\u7b2c\u4e00\u9898",
                        "emotion": "thinking",
                    },
                }
            )
            if event_name in fixed_demo_events:
                template = fixed_demo_events[event_name]
                message = {
                    "type": "xingbao_expression_request",
                    "source": str(message.get("source") or "demo_game"),
                    "priority": 1,
                    "payload": {
                        "intent": event_name,
                        "text": template["text"],
                        "screen_text": template["screen_text"],
                        "emotion": template["emotion"],
                        "tts": True,
                        "interrupt_policy": "queue",
                        "feedback": {
                            "screen_expression": "smile",
                            "arm_action": "stay_still",
                        },
                    },
                }
            emotion_board_ui_sent = False
            if memory_update is not None and board_ui_client is not None:
                try:
                    scene_id = scene_for_idle_vision_emotion(memory_update.get("recent_mood"))
                    if scene_id:
                        board_ui_client.send_xingbao_scene(scene_id, source="vision_emotion")
                    emotion_plan = app.coordinator.plan_event(message)
                    emotion_board_result = board_ui_client.send_plan(emotion_plan)
                    emotion_board_ui_sent = bool(emotion_board_result.get("ok"))
                    print(
                        "[vision-board] emotion={} sent=true ok={}".format(
                            memory_update.get("recent_mood", ""),
                            emotion_board_ui_sent,
                        ),
                        flush=True,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    print(
                        "[vision-board] sent=false error={}:{}".format(
                            type(exc).__name__,
                            exc,
                        ),
                        flush=True,
                    )
            raw = json.dumps(message, ensure_ascii=False)
            common_kwargs = {
                "apply_output": True,
                "no_tts": False,
                "local_tts_fallback": args.local_tts_fallback,
                "output_device": args.output_device,
                "board_ui_client": None if emotion_board_ui_sent else board_ui_client,
            }
            if str(message.get("type") or "") in {"mini_game_state", "vision_state"}:
                app.run_coordinated_state_json(
                    raw,
                    board_ui_first=str(message.get("type") or "") == "vision_state",
                    **common_kwargs,
                )
            else:
                app.run_coordinated_event_json(raw, **common_kwargs)

        def play_game_speech(text: str, payload: dict[str, object]) -> None:
            if bool(payload.get("pause_conversation", False)):
                stopped = app.request_conversation_stop(silent=True)
                print(
                    "[conversation-stop] source=read_aloud ok={} reason={}".format(
                        bool(stopped.get("ok")), stopped.get("reason", "")
                    ),
                    flush=True,
                )
            if not game_session_registry.observe_speech(payload, "playing"):
                raise RuntimeError("stale_game_state")
            app.speak_game_text(
                text,
                output_device=args.output_device,
                local_tts_fallback=args.local_tts_fallback,
                interrupt=bool(payload.get("interrupt", False)),
                source=str(payload.get("source") or ""),
                scene=str(payload.get("scene") or ""),
                latency_mode=str(payload.get("latency_mode") or ""),
                interrupt_event=payload.get("_interrupt_event"),
                speech_context=payload,
            )

        game_speech_server = GameSpeechServer(
            play_game_speech,
            event_handler=handle_game_event_message,
            interrupt_handler=app.interrupt_game_speech,
            lifecycle_handler=game_session_registry.observe_speech,
            host=args.game_speech_host,
            port=args.game_speech_port,
        ).start()
        atexit.register(game_speech_server.close)
        print(
            "[game-speech] listening on {}:{}".format(*game_speech_server.address),
            flush=True,
        )
        if args.vision_runtime:
            try:
                vision_restart_seconds = float(
                    os.environ.get("XINGBAO_VISION_RESTART_SECONDS", "10")
                )
            except (TypeError, ValueError):
                vision_restart_seconds = 10.0
            try:
                vision_control_port = int(
                    os.environ.get("XINGBAO_VISION_CONTROL_PORT", "8768")
                )
            except (TypeError, ValueError):
                vision_control_port = 8768
            vision_managed = start_managed_vision_runtime(
                event_handler=handle_game_event_message,
                log_handler=write_vision_log,
                restart_delay_seconds=max(0.5, vision_restart_seconds),
                control_port=vision_control_port,
            )
            vision_start = vision_managed["startup"]
            write_vision_log(
                "startup {}".format(
                    json.dumps(vision_start, ensure_ascii=False, sort_keys=True)
                )
            )
            vision_runtime = vision_managed["controller"]
            atexit.register(vision_runtime.close)
            vision_control_server = vision_managed["server"]
            if vision_control_server is not None:
                atexit.register(vision_control_server.close)
            if vision_managed["control_error"]:
                write_vision_log(
                    "vision_control_server_unavailable {}".format(
                        vision_managed["control_error"]
                    )
                )
            # The bridge is intentionally constructed only by the controller:
            # shell management commands act on this same instance and cannot
            # create a second event-producing vision subprocess.
        if args.prewarm_game_tts_cache:
            def prewarm_game_tts_cache() -> None:
                wake_report = app.prepare_wake_ack_cache()
                fixed_demo_report = app.prepare_fixed_demo_tts_cache()
                report = app.prepare_demo_tts_cache(yield_seconds=0.05)
                print(
                    "[game-speech] background cache warmup {}".format(
                        json.dumps(report["counts"], ensure_ascii=False, sort_keys=True)
                    ),
                    flush=True,
                )
                print(
                    "[wake-ack] background cache warmup {}".format(
                        json.dumps(
                            wake_report["counts"],
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                    flush=True,
                )
                print(
                    "[fixed-demo] background cache warmup {}".format(
                        json.dumps(
                            fixed_demo_report["counts"],
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                    flush=True,
                )

            threading.Thread(
                target=prewarm_game_tts_cache,
                name="game-tts-cache-prewarm",
                daemon=True,
            ).start()
    voice_event_handler = build_voice_event_handler(
        show_voice_events=args.show_voice_events,
        board_ui_client=board_ui_client,
    )

    if args.text_demo:
        print(app.run_text_demo())
        return 0

    if args.prompt_preview:
        print(app.build_prompt_preview())
        return 0

    if args.list_devices:
        print(app.list_audio_devices())
        return 0

    if args.list_output_devices:
        print(app.list_output_devices())
        return 0

    if args.test_output_device is not None:
        print(app.test_output_device(args.test_output_device))
        return 0

    if args.test_board_output:
        try:
            print(app.test_board_output())
        except (FileNotFoundError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from None
        return 0

    if args.list_voice_profiles:
        print(app.list_voice_profiles())
        return 0

    if args.send_action:
        if not args.serial_port:
            raise SystemExit("--send-action requires --serial-port")
        print(app.send_action(args.serial_port, args.send_action))
        return 0

    if args.color_block_demo:
        print(app.run_color_block_demo())
        return 0

    if args.color_block_game:
        app.launch_color_block_game(serial_port=args.serial_port or None)
        return 0

    if args.color_block_web:
        print(app.color_block_web_path())
        return 0

    if args.list_kids_visual_tools:
        print(json.dumps(app.list_kids_visual_tools(), ensure_ascii=False, sort_keys=True))
        return 0

    if args.kids_visual_tools or args.kids_visual_tool:
        try:
            result = app.launch_kids_visual_tools(args.kids_visual_tool or None, wait=True)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    coordination_board_kwargs = {"board_ui_client": board_ui_client}

    if args.coordinate_text:
        try:
            output = app.run_coordinated_text(
                args.coordinate_text,
                apply_output=args.coordinate_apply or args.expression_speak,
                launch_tools=args.coordinate_launch,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.coordinate_event_json:
        try:
            output = app.run_coordinated_event_json(
                args.coordinate_event_json,
                apply_output=args.coordinate_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.coordinate_event_file:
        try:
            raw_event_json = Path(args.coordinate_event_file).read_text(encoding="utf-8-sig")
            output = app.run_coordinated_event_json(
                raw_event_json,
                apply_output=args.coordinate_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except OSError as exc:
            raise SystemExit(str(exc)) from None
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.coordinate_state_json:
        try:
            output = app.run_coordinated_state_json(
                args.coordinate_state_json,
                apply_output=args.coordinate_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.coordinate_state_file:
        try:
            raw_state_json = Path(args.coordinate_state_file).read_text(encoding="utf-8-sig")
            output = app.run_coordinated_state_json(
                raw_state_json,
                apply_output=args.coordinate_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except OSError as exc:
            raise SystemExit(str(exc)) from None
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.game_command_json:
        try:
            output = app.run_game_command_json(
                args.game_command_json,
                apply_output=args.coordinate_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.game_command_file:
        try:
            raw_command_json = Path(args.game_command_file).read_text(encoding="utf-8-sig")
            output = app.run_game_command_json(
                raw_command_json,
                apply_output=args.coordinate_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
                **coordination_board_kwargs,
            )
        except OSError as exc:
            raise SystemExit(str(exc)) from None
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.coordinate_color_block_command:
        output = app.run_coordinated_color_block_command(
            args.coordinate_color_block_command,
            apply_output=args.coordinate_apply or args.expression_speak,
            no_tts=not args.expression_speak,
            local_tts_fallback=args.local_tts_fallback,
            output_device=args.output_device,
            **coordination_board_kwargs,
        )
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.expression_demo:
        print(
            app.run_expression_demo(
                apply_output=args.expression_apply or args.expression_speak,
                no_tts=not args.expression_speak,
                local_tts_fallback=args.local_tts_fallback,
                output_device=args.output_device,
            )
        )
        return 0

    if args.expression_event_json:
        try:
            expression_kwargs = {
                "apply_output": args.expression_apply or args.expression_speak,
                "no_tts": not args.expression_speak,
                "local_tts_fallback": args.local_tts_fallback,
                "output_device": args.output_device,
            }
            if args.growth_guidance:
                expression_kwargs["use_growth_guidance"] = True
            output = app.run_expression_event_json(
                args.expression_event_json,
                **expression_kwargs,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.expression_event_file:
        try:
            raw_event_json = Path(args.expression_event_file).read_text(encoding="utf-8-sig")
            expression_kwargs = {
                "apply_output": args.expression_apply or args.expression_speak,
                "no_tts": not args.expression_speak,
                "local_tts_fallback": args.local_tts_fallback,
                "output_device": args.output_device,
            }
            if args.growth_guidance:
                expression_kwargs["use_growth_guidance"] = True
            output = app.run_expression_event_json(
                raw_event_json,
                **expression_kwargs,
            )
        except OSError as exc:
            raise SystemExit(str(exc)) from None
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    if args.test_wake_word:
        try:
            keyword = app.wait_for_wake_word(
                input_device=args.input_device,
                wake_level_interval_seconds=args.wake_rms_interval,
                wake_word_threshold=args.wake_word_threshold,
            )
        except (FileNotFoundError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from None
        print(f"Wake word detected: {keyword}")
        return 0

    if args.test_wake_wav:
        try:
            detected = app.test_wake_wav(args.test_wake_wav)
        except (FileNotFoundError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from None
        print(f"Detected wake words: {detected}")
        return 0

    if args.wake_loop:
        def print_turn(result: object) -> None:
            print(f"User: {result.user_text}")
            print(f"Xingbao: {result.assistant_text}")
            print(f"Action: {result.action}")
            print(f"Audio: {result.audio_path}")

        try:
            app.run_wake_loop(
                no_tts=args.no_tts,
                no_quick_ack=args.no_quick_ack,
                no_wake_ack=args.no_wake_ack,
                local_tts_fallback=args.local_tts_fallback,
                serial_port=args.serial_port or None,
                input_device=args.input_device,
                output_device=args.output_device,
                max_turns=args.max_wake_turns,
                on_turn_complete=print_turn,
                streaming_response=not args.no_streaming_response,
                realtime_tts=args.realtime_tts,
                realtime_asr=args.realtime_asr,
                streaming_asr=args.streaming_asr,
                realtime_asr_model=args.realtime_asr_model,
                show_wake_level=args.show_wake_level,
                wake_level_interval_seconds=args.wake_rms_interval,
                wake_word_threshold=args.wake_word_threshold,
                low_latency_voice=args.low_latency_voice,
                listen_timeout_seconds=args.listen_timeout,
                vad_manual_threshold=args.vad_manual_threshold,
                vad_end_silence_ms=args.vad_end_silence_ms,
                on_voice_event=voice_event_handler,
                board_ui_client=board_ui_client,
            )
        except KeyboardInterrupt:
            print("\nWake loop stopped.")
        except (FileNotFoundError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from None
        return 0

    if args.wake_chat:
        def print_turn(result: object) -> None:
            print(f"User: {result.user_text}")
            print(f"Xingbao: {result.assistant_text}")
            print(f"Action: {result.action}")
            print(f"Audio: {result.audio_path}")

        def print_session(turn_count: int, reason: str) -> None:
            print(f"Conversation window ended after {turn_count} turn(s), reason={reason}.")

        try:
            app.run_wake_chat(
                no_tts=args.no_tts,
                no_quick_ack=args.no_quick_ack,
                no_wake_ack=args.no_wake_ack,
                local_tts_fallback=args.local_tts_fallback,
                serial_port=args.serial_port or None,
                input_device=args.input_device,
                output_device=args.output_device,
                max_sessions=args.max_wake_sessions,
                max_turns_per_session=args.max_chat_turns,
                followup_timeout_seconds=args.follow_up_timeout,
                on_turn_complete=print_turn,
                on_session_complete=print_session,
                streaming_response=not args.no_streaming_response,
                realtime_tts=args.realtime_tts,
                realtime_asr=args.realtime_asr,
                streaming_asr=args.streaming_asr,
                realtime_asr_model=args.realtime_asr_model,
                show_wake_level=args.show_wake_level,
                wake_level_interval_seconds=args.wake_rms_interval,
                wake_word_threshold=args.wake_word_threshold,
                low_latency_voice=args.low_latency_voice,
                listen_timeout_seconds=args.listen_timeout,
                vad_manual_threshold=args.vad_manual_threshold,
                vad_end_silence_ms=args.vad_end_silence_ms,
                on_voice_event=voice_event_handler,
                board_ui_client=board_ui_client,
            )
        except KeyboardInterrupt:
            print("\nWake chat stopped.")
        except (FileNotFoundError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from None
        return 0

    if args.voice_once:
        try:
            result = app.run_voice_once(
                no_tts=args.no_tts,
                no_quick_ack=args.no_quick_ack,
                local_tts_fallback=args.local_tts_fallback,
                serial_port=args.serial_port or None,
                input_device=args.input_device,
                output_device=args.output_device,
                record_sample_rate=args.record_sample_rate,
                streaming_response=not args.no_streaming_response,
                realtime_tts=args.realtime_tts,
                realtime_asr=args.realtime_asr,
                streaming_asr=args.streaming_asr,
                realtime_asr_model=args.realtime_asr_model,
                low_latency_voice=args.low_latency_voice,
                listen_timeout_seconds=args.listen_timeout,
                vad_manual_threshold=args.vad_manual_threshold,
                vad_end_silence_ms=args.vad_end_silence_ms,
                vad_debug_level=args.vad_debug_level,
                on_voice_event=voice_event_handler,
                board_ui_client=board_ui_client,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from None
        print(f"User: {result.user_text}")
        print(f"Xingbao: {result.assistant_text}")
        print(f"Action: {result.action}")
        print(f"Audio: {result.audio_path}")
        return 0

    print("Xingbao Companion is ready. Run with --text-demo or --help.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
