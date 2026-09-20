"""Enter-driven scripted demo flow for Xingbao's board presentation."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app import XingbaoApp
from core.arm_action_bridge import ARM_ACTION_HOST, ARM_ACTION_PORT, send_arm_action_ndjson
from core.board_ui_client import BoardUIClient
from multimodal.audio_io import BOARD_APLAY_OUTPUT_DEVICE, generate_chime_wav, play_wav


SCREEN_EXPRESSIONS = {
    "neutral",
    "smile",
    "thinking",
    "curious",
    "sad",
    "surprised",
    "sleepy",
}
LED_MODES = {
    "off",
    "blue_breath",
    "warm_breath",
    "yellow_blink",
    "rainbow",
    "red_flash",
}
ARM_ACTIONS = {
    "stay_still",
    "wave_hand",
    "nod",
    "shake_head",
    "point_left",
    "point_right",
    "small_dance",
    "bow",
}

SHAPE_ID_LABELS = {
    "circle": "圆形",
    "square": "正方形",
    "triangle": "三角形",
    "star": "星形",
    "heart": "爱心",
    "rectangle": "长方形",
    "ellipse": "椭圆形",
}


@dataclass(frozen=True)
class DemoStep:
    key: str
    title: str
    assumed_input: str
    source: str
    intent: str
    speak_text: str
    screen_text: str
    emotion: str = "smile"
    screen_expression: str = "smile"
    led_mode: str = "warm_breath"
    arm_action: str = "stay_still"
    ui_command: dict[str, Any] | None = None
    tts: bool = True
    priority: int = 1
    duration_ms: int = 4000
    event_payload: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Xingbao's demo flow one Enter press at a time."
    )
    parser.add_argument(
        "--answer-result",
        choices=("correct", "wrong", "both"),
        default="both",
        help="Choose which game-answer branch to demonstrate.",
    )
    parser.add_argument(
        "--shape-question-label",
        default="三角形",
        help="Shape label used by the demo read-question step, such as 长方形, 星形, 爱心, 椭圆.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run without waiting for Enter; useful for quick smoke tests.",
    )
    parser.add_argument(
        "--auto-delay",
        type=float,
        default=1.0,
        help="Seconds between steps when --auto is enabled.",
    )
    parser.add_argument(
        "--start-at",
        default="",
        help="Start from a step key. Use --list-steps to see keys.",
    )
    parser.add_argument(
        "--list-steps",
        action="store_true",
        help="Print the scripted step keys and exit.",
    )
    parser.add_argument(
        "--no-board-ui",
        action="store_true",
        help="Do not send assistant_output to the touch desktop bridge.",
    )
    parser.add_argument(
        "--board-ui-host",
        default="127.0.0.1",
        help="Touch desktop NDJSON bridge host.",
    )
    parser.add_argument(
        "--board-ui-port",
        type=int,
        default=8765,
        help="Touch desktop NDJSON bridge port.",
    )
    parser.add_argument(
        "--board-ui-timeout",
        type=float,
        default=6.0,
        help="Socket timeout for each touch desktop bridge message.",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Apply states but skip real TTS playback.",
    )
    parser.add_argument(
        "--no-input-ack",
        action="store_true",
        help="Do not play the short recognition chime before scripted voice responses.",
    )
    parser.add_argument(
        "--local-tts-fallback",
        action="store_true",
        help="Use local system TTS if cloud TTS fails.",
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
        help="Use board ALSA playback for TTS.",
    )
    parser.add_argument(
        "--no-auto-board-audio",
        action="store_true",
        help="Do not auto-select the board ALSA playback backend when a lahaina card is present.",
    )
    parser.add_argument(
        "--prepare-demo-tts-cache",
        action="store_true",
        help="Pre-synthesize fixed demo utterances before starting.",
    )
    parser.add_argument(
        "--no-arm",
        action="store_true",
        help="Replace scripted arm actions with stay_still.",
    )
    parser.add_argument(
        "--no-direct-arm",
        action="store_true",
        help="Do not send the extra direct shake_head message to the arm IPC endpoint.",
    )
    parser.add_argument(
        "--direct-arm-host",
        default=ARM_ACTION_HOST,
        help="Host for the direct high-level arm IPC endpoint.",
    )
    parser.add_argument(
        "--direct-arm-port",
        type=int,
        default=ARM_ACTION_PORT,
        help="Port for the direct high-level arm IPC endpoint.",
    )
    parser.add_argument(
        "--direct-arm-timeout",
        type=float,
        default=1.0,
        help="Socket timeout for the direct high-level arm IPC endpoint.",
    )
    parser.add_argument(
        "--direct-arm-steps",
        default="greeting,open_game",
        help="Comma-separated step keys that should send an extra direct shake_head.",
    )
    parser.add_argument(
        "--require-direct-arm",
        action="store_true",
        help="Fail when the direct arm IPC endpoint is not available.",
    )
    parser.add_argument(
        "--no-auto-start-arm-service",
        action="store_true",
        help="Do not try to start the local high-level arm action service when 8764 is closed.",
    )
    parser.add_argument(
        "--arm-service-dir",
        default=os.environ.get(
            "XINGBAO_ARM_SERVICE_DIR",
            "/home/fibo/xingbao_project/soarm101_module",
        ),
        help="Directory containing arm_action_server.py on the board.",
    )
    parser.add_argument(
        "--arm-service-script",
        default=os.environ.get("XINGBAO_ARM_SERVICE_SCRIPT", "arm_action_server.py"),
        help="High-level arm action service script name.",
    )
    parser.add_argument(
        "--arm-service-python",
        default=os.environ.get("XINGBAO_ARM_SERVICE_PYTHON", ""),
        help="Python interpreter for the arm action service.",
    )
    parser.add_argument(
        "--arm-service-log",
        default=os.environ.get(
            "XINGBAO_ARM_SERVICE_LOG",
            "/tmp/xingbao_arm_action_server.log",
        ),
        help="Log file for the auto-started arm action service.",
    )
    parser.add_argument(
        "--arm-service-start-timeout",
        type=float,
        default=12.0,
        help="Seconds to wait for the arm action service to open its IPC port.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop when TTS or touch desktop delivery fails.",
    )
    return parser.parse_args()


def build_steps(answer_result: str, shape_question_label: str = "三角形") -> list[DemoStep]:
    shape_label = shape_question_label.strip() or "三角形"
    shape_question_text = f"请找到{shape_label}在哪里。"
    steps = [
        DemoStep(
            key="wake",
            title="唤醒星宝",
            assumed_input="星宝你好（唤醒词）",
            source="demo_wake",
            intent="wake_detected",
            speak_text="hi",
            screen_text="我听到你啦",
            emotion="listening",
            screen_expression="curious",
            led_mode="blue_breath",
            duration_ms=1800,
        ),
        DemoStep(
            key="greeting",
            title="问候回复",
            assumed_input="星宝你好",
            source="demo_dialogue",
            intent="greeting",
            speak_text="我在呢，今天也一起玩一会儿吧。",
            screen_text="星宝已唤醒",
            emotion="happy",
            screen_expression="smile",
            led_mode="warm_breath",
            arm_action="shake_head",
        ),
        DemoStep(
            key="desktop_title_read",
            title="桌面标题朗读",
            assumed_input="点击/演示：星宝学习桌面",
            source="demo_desktop_read_aloud",
            intent="desktop_read_aloud",
            speak_text="星宝学习桌面。",
            screen_text="星宝学习桌面",
            emotion="smile",
            screen_expression="smile",
            led_mode="warm_breath",
            duration_ms=900,
        ),
        DemoStep(
            key="desktop_prompt_read",
            title="桌面引导朗读",
            assumed_input="点击/演示：今天想和星宝聊什么？",
            source="demo_desktop_read_aloud",
            intent="desktop_read_aloud",
            speak_text="今天想和星宝聊什么？",
            screen_text="今天想和星宝聊什么？",
            emotion="curious",
            screen_expression="curious",
            led_mode="blue_breath",
            duration_ms=900,
        ),
        DemoStep(
            key="desktop_features_intro",
            title="介绍桌面功能",
            assumed_input="星宝，你有什么功能？",
            source="demo_dialogue",
            intent="desktop_features_intro",
            speak_text="我可以陪你聊天，玩小游戏，画画，专心学习，也会提醒你休息和喝水。",
            screen_text="星宝功能介绍",
            emotion="smile",
            screen_expression="smile",
            led_mode="warm_breath",
            duration_ms=1800,
        ),
        DemoStep(
            key="open_game",
            title="进入游戏中心",
            assumed_input="星宝，我要玩游戏。",
            source="demo_dialogue",
            intent="open_game_center",
            speak_text="进入游戏啦，请选择一个游戏，再选择难度。",
            screen_text="选择游戏",
            emotion="smile",
            screen_expression="smile",
            led_mode="warm_breath",
            arm_action="shake_head",
            ui_command={"name": "open_game_center", "params": {}},
        ),
        DemoStep(
            key="start_game",
            title="选择游戏和难度",
            assumed_input="触控选择：认形状游戏 / 简单难度",
            source="demo_touch",
            intent="difficulty_selected",
            speak_text="难度选好了，我们开始第一题。",
            screen_text="开始第一题",
            emotion="thinking",
            screen_expression="thinking",
            led_mode="blue_breath",
            ui_command={
                "name": "start_game",
                "params": {"game_id": "shape_game", "difficulty": 1},
            },
            event_payload={"game_id": "shape_game", "difficulty": 1},
        ),
        DemoStep(
            key="read_shape_question",
            title="读题：形状识别",
            assumed_input="游戏界面：自动读题",
            source="demo_game",
            intent="read_question",
            speak_text=shape_question_text,
            screen_text=f"请找到{shape_label}",
            emotion="thinking",
            screen_expression="thinking",
            led_mode="blue_breath",
            duration_ms=1200,
            event_payload={
                "type": "game_question",
                "game_id": "shape_game",
                "intent": "read_question",
                "state": {"target_label": shape_label},
            },
        ),
    ]

    if answer_result in {"wrong", "both"}:
        steps.append(
            DemoStep(
                key="answer_wrong",
                title="游戏反馈：答错鼓励",
                assumed_input="触控选择：错误答案",
                source="demo_game",
                intent="answer_wrong",
                speak_text="没关系，这一题我们再试一次。",
                screen_text="再试一次",
                emotion="encouraging",
                screen_expression="smile",
                led_mode="warm_breath",
                event_payload={
                    "type": "game_response",
                    "ok": False,
                    "game_id": "shape_game",
                    "intent": "answer_result",
                    "state": {"last_result": "wrong"},
                },
            )
        )

    if answer_result in {"correct", "both"}:
        steps.append(
            DemoStep(
                key="answer_correct",
                title="游戏反馈：答对祝贺",
                assumed_input="触控选择：正确答案",
                source="demo_game",
                intent="answer_correct",
                speak_text="太棒了，你答对了。",
                screen_text="答对啦",
                emotion="happy",
                screen_expression="smile",
                led_mode="rainbow",
                event_payload={
                    "type": "game_response",
                    "ok": True,
                    "game_id": "shape_game",
                    "intent": "answer_result",
                    "state": {"last_result": "correct", "stars": 1},
                },
            )
        )

    steps.append(
        DemoStep(
            key="posture_warning",
            title="姿态检测提醒",
            assumed_input="视觉事件：头部靠近屏幕",
            source="demo_vision",
            intent="face_too_close",
            speak_text="小朋友，你离屏幕有点近，稍微坐远一点，也记得喝水哦。",
            screen_text="注意距离",
            emotion="caring",
            screen_expression="thinking",
            led_mode="blue_breath",
            priority=3,
            event_payload={
                "type": "vision_state",
                "payload": {
                    "state": "face_too_close",
                    "confidence": 1.0,
                    "duration_seconds": 3,
                    "zone": "center",
                    "simulated": True,
                },
            },
        )
    )
    return steps


def expression_event(step: DemoStep, *, disable_arm: bool = False) -> dict[str, Any]:
    payload = {
        "intent": step.intent,
        "text": step.speak_text,
        "screen_text": step.screen_text,
        "emotion": step.emotion,
        "tts": step.tts,
        "interrupt_policy": "queue",
        "feedback": {
            "screen_expression": safe_screen_expression(step.screen_expression),
            "led_mode": safe_led_mode(step.led_mode),
            "arm_action": "stay_still" if disable_arm else safe_arm_action(step.arm_action),
        },
    }
    if step.event_payload:
        payload["demo_event"] = step.event_payload
    return {
        "type": "xingbao_expression_request",
        "source": step.source,
        "priority": step.priority,
        "payload": payload,
    }


def assistant_output_message(
    step: DemoStep,
    *,
    disable_arm: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "speech": {
            "text": "",
            "request_tts": False,
            "interrupt": False,
        },
        "screen_text": step.screen_text,
        "screen_expression": {
            "name": safe_screen_expression(step.screen_expression),
            "duration_ms": max(200, min(30000, int(step.duration_ms))),
        },
        "arm_action": "stay_still" if disable_arm else safe_arm_action(step.arm_action),
        "led": {
            "mode": safe_led_mode(step.led_mode),
            "duration_ms": max(200, min(30000, int(step.duration_ms))),
        },
        "ui_command": step.ui_command,
    }
    return {
        "version": "1.0",
        "request_id": f"enter-demo-{step.key}-{uuid.uuid4()}",
        "type": "assistant_output",
        "source": "enter_demo_flow",
        "target": "desktop_ui",
        "payload": payload,
    }


def safe_screen_expression(value: str) -> str:
    return value if value in SCREEN_EXPRESSIONS else "neutral"


def safe_led_mode(value: str) -> str:
    return value if value in LED_MODES else "off"


def safe_arm_action(value: str) -> str:
    return value if value in ARM_ACTIONS else "stay_still"


def parse_step_keys(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in str(value or "").split(",") if part.strip())


def should_play_input_ack(step: DemoStep) -> bool:
    return step.source in {"demo_wake", "demo_dialogue"}


def resolve_output_device(args: argparse.Namespace) -> tuple[int | None, str]:
    if args.board_audio_output:
        return BOARD_APLAY_OUTPUT_DEVICE, "board_aplay_explicit"
    if args.output_device is not None:
        return args.output_device, "sounddevice_explicit"
    if not args.no_auto_board_audio and has_lahaina_audio_card():
        return BOARD_APLAY_OUTPUT_DEVICE, "board_aplay_auto"
    return None, "sounddevice_default"


def has_lahaina_audio_card() -> bool:
    cards_path = Path("/proc/asound/cards")
    try:
        content = cards_path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "lahaina-yupikiot" in content or "lahainayupikiot" in content


def same_endpoint(host_a: str, port_a: int, host_b: str, port_b: int) -> bool:
    if int(port_a) != int(port_b):
        return False
    return normalize_loopback_host(host_a) == normalize_loopback_host(host_b)


def normalize_loopback_host(host: str) -> str:
    value = str(host or "").strip().lower()
    if value in {"localhost", "127.0.0.1", "::1"}:
        return "loopback"
    return value


def tcp_endpoint_available(host: str, port: int, *, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, timeout)):
            return True
    except OSError:
        return False


def default_arm_service_python() -> str:
    board_python = Path("/usr/bin/python3")
    if board_python.exists():
        return str(board_python)
    return sys.executable


def start_arm_action_service(
    args: argparse.Namespace,
    *,
    host: str,
    port: int,
) -> dict[str, Any]:
    service_dir = Path(args.arm_service_dir).expanduser()
    service_script = service_dir / str(args.arm_service_script)
    if not service_script.exists():
        return {
            "ok": False,
            "started": False,
            "error": "arm_service_script_missing",
            "path": str(service_script),
        }

    python_bin = args.arm_service_python or default_arm_service_python()
    log_path = Path(args.arm_service_log)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("ab")
    except OSError as exc:
        return {
            "ok": False,
            "started": False,
            "error": "arm_service_log_unavailable",
            "message": str(exc),
            "path": str(log_path),
        }

    with log_file:
        try:
            subprocess.Popen(
                [python_bin, str(service_script.name)],
                cwd=str(service_dir),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            return {
                "ok": False,
                "started": False,
                "error": "arm_service_start_failed",
                "message": str(exc),
                "python": python_bin,
                "path": str(service_script),
            }

    deadline = time.monotonic() + max(0.0, float(args.arm_service_start_timeout))
    while time.monotonic() < deadline:
        if tcp_endpoint_available(host, port, timeout=0.2):
            return {
                "ok": True,
                "started": True,
                "host": host,
                "port": int(port),
                "python": python_bin,
                "path": str(service_script),
                "log": str(log_path),
            }
        time.sleep(0.3)
    return {
        "ok": False,
        "started": True,
        "error": "arm_service_port_not_ready",
        "host": host,
        "port": int(port),
        "path": str(service_script),
        "log": str(log_path),
    }


def select_start_index(steps: list[DemoStep], key: str) -> int:
    if not key:
        return 0
    for index, step in enumerate(steps):
        if step.key == key:
            return index
    valid = ", ".join(step.key for step in steps)
    raise SystemExit(f"Unknown --start-at step: {key}. Valid steps: {valid}")


def wait_for_next(step: DemoStep, index: int, total: int, *, auto: bool, delay: float) -> None:
    print()
    print(f"[{index}/{total}] {step.title}")
    print(f"假定输入：{step.assumed_input}")
    if auto:
        time.sleep(max(0.0, delay))
        return
    input("按 Enter 执行这一步...")


def resolve_read_question_step(
    board_ui_client: BoardUIClient | None,
    step: DemoStep,
) -> tuple[DemoStep, dict[str, Any] | None]:
    if step.key != "read_shape_question" or board_ui_client is None:
        return step, None
    command = {
        "type": "game_command",
        "game_id": "current_game",
        "intent": "repeat_prompt",
        "context": {"source": "enter_demo_flow"},
    }
    try:
        result = board_ui_client.send_game_command(command)
    except Exception as exc:
        return step, {
            "ok": False,
            "source": "game_status",
            "error": type(exc).__name__,
            "message": str(exc),
            "fallback_text": step.speak_text,
        }

    game_response = result.get("game_response")
    if not isinstance(game_response, dict):
        return step, {
            "ok": False,
            "source": "game_status",
            "error": "missing_game_response",
            "response": result.get("response"),
            "fallback_text": step.speak_text,
        }
    if not game_response.get("ok", False):
        return step, {
            "ok": False,
            "source": "game_status",
            "error": "game_response_not_ok",
            "game_response": game_response,
            "fallback_text": step.speak_text,
        }

    label = shape_label_from_game_response(game_response)
    if not label:
        return step, {
            "ok": False,
            "source": "game_status",
            "error": "missing_target_label",
            "game_response": game_response,
            "fallback_text": step.speak_text,
        }

    speak_text = f"请找到{label}在哪里。"
    payload = dict(step.event_payload or {})
    state = dict(payload.get("state") or {})
    state.update({
        "target_label": label,
        "game_status_source": "repeat_prompt",
        "current_goal": game_response.get("message", ""),
    })
    payload["state"] = state
    resolved = replace(
        step,
        assumed_input=f"游戏状态识别：当前题目是{label}",
        speak_text=speak_text,
        screen_text=f"请找到{label}",
        event_payload=payload,
    )
    return resolved, {
        "ok": True,
        "source": "game_status",
        "target_label": label,
        "speak_text": speak_text,
        "game_response": game_response,
    }


def shape_label_from_game_response(game_response: dict[str, Any]) -> str:
    state = game_response.get("state")
    if not isinstance(state, dict):
        state = {}
    for key in (
        "target_label",
        "target_shape_label",
        "current_target_label",
        "shape_label",
        "target_name",
    ):
        label = clean_shape_label(state.get(key))
        if label:
            return label
    target_shape = str(state.get("target_shape") or "").strip()
    if target_shape in SHAPE_ID_LABELS:
        return SHAPE_ID_LABELS[target_shape]
    for key in ("message", "current_goal"):
        label = clean_shape_label(game_response.get(key) or state.get(key))
        if label:
            return label
    return ""


def clean_shape_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for prefix in ("请找到", "请找出", "找到", "找出"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    for suffix in ("在哪里。", "在哪里?", "在哪里？", "在哪里", "能量", "。", "！", "!", "？", "?"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def run_step(
    app: XingbaoApp,
    board_ui_client: BoardUIClient | None,
    step: DemoStep,
    *,
    no_tts: bool,
    input_ack: bool,
    local_tts_fallback: bool,
    output_device: int | None,
    disable_arm: bool,
    direct_arm: bool,
    direct_arm_steps: frozenset[str],
    direct_arm_host: str,
    direct_arm_port: int,
    direct_arm_timeout: float,
    direct_arm_skip_reason: str = "",
) -> dict[str, Any]:
    step, game_status_query = resolve_read_question_step(board_ui_client, step)
    event = expression_event(step, disable_arm=disable_arm)
    plan = app.coordinator.plan_event(event)
    message = assistant_output_message(step, disable_arm=disable_arm)
    results: dict[str, Any] = {
        "step": step.key,
        "event": event,
        "assistant_output": message,
    }
    if game_status_query is not None:
        results["game_status_query"] = game_status_query

    def apply_voice_and_state() -> dict[str, Any]:
        input_ack_result: dict[str, Any] | None = None
        if input_ack and should_play_input_ack(step):
            try:
                play_wav(generate_chime_wav(), output_device=output_device)
                input_ack_result = {"ok": True, "played": True}
            except Exception as exc:
                input_ack_result = {
                    "ok": False,
                    "played": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
        applied = app.apply_expression_output(
            plan.expression_output,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
        )
        result = applied.as_dict()
        if input_ack_result is not None:
            result["input_ack"] = input_ack_result
        return result

    def send_board_ui() -> dict[str, Any]:
        if board_ui_client is None:
            return {"ok": True, "skipped": True, "reason": "board_ui_disabled"}
        attempts = 2 if step.ui_command else 1
        last_error: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = board_ui_client.send_assistant_output(message)
                if response.get("ok") or attempt == attempts:
                    return {
                        "ok": bool(response.get("ok")),
                        "response": response,
                        "attempts": attempt,
                    }
                last_error = {"response": response}
            except Exception as exc:
                last_error = {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "attempts": attempt,
                }
                if attempt == attempts:
                    return last_error
            time.sleep(0.8)
        return {"ok": False, "error": "board_ui_retry_failed", "detail": last_error}

    def trigger_direct_arm() -> dict[str, Any]:
        if disable_arm or not direct_arm or step.key not in direct_arm_steps:
            return {
                "ok": True,
                "skipped": True,
                "reason": direct_arm_skip_reason or "direct_arm_disabled",
            }
        action = "shake_head"
        try:
            send_arm_action_ndjson(
                action,
                host=direct_arm_host,
                port=direct_arm_port,
                timeout=direct_arm_timeout,
            )
            return {
                "ok": True,
                "arm_action": action,
                "sent": True,
                "host": direct_arm_host,
                "port": int(direct_arm_port),
            }
        except Exception as exc:
            return {
                "ok": False,
                "arm_action": action,
                "error": type(exc).__name__,
                "message": str(exc),
                "host": direct_arm_host,
                "port": int(direct_arm_port),
            }

    tasks = {
        "voice_state": apply_voice_and_state,
        "board_ui": send_board_ui,
        "direct_arm": trigger_direct_arm,
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_map = {
            name: executor.submit(function)
            for name, function in tasks.items()
        }
        for name, future in future_map.items():
            try:
                results[name] = future.result()
            except Exception as exc:  # keep demo control in the presenter's hand
                results[name] = {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
    return results


def print_step_result(result: dict[str, Any]) -> None:
    voice = result.get("voice_state", {})
    board = result.get("board_ui", {})
    direct_arm = result.get("direct_arm", {})
    game_status = result.get("game_status_query")
    voice_ok = not isinstance(voice, dict) or not voice.get("error")
    board_ok = bool(board.get("ok", False)) if isinstance(board, dict) else False
    direct_arm_ok = bool(direct_arm.get("ok", False)) if isinstance(direct_arm, dict) else False
    game_status_part = ""
    if isinstance(game_status, dict):
        game_status_part = "; game_status={}".format(
            "ok" if game_status.get("ok") else "fallback"
        )
    print(
        f"执行结果：voice/state={'ok' if voice_ok else 'failed'}; "
        f"board_ui={'ok' if board_ok else 'failed'}; "
        f"direct_arm={'ok' if direct_arm_ok else 'failed'}"
        f"{game_status_part}"
    )
    if isinstance(game_status, dict):
        if game_status.get("ok"):
            print(f"  识别题目：{game_status.get('speak_text', '')}")
        else:
            detail = game_status.get("error") or game_status.get("message") or game_status
            print(f"  game_status fallback: {detail}")
    if isinstance(voice, dict) and voice.get("error"):
        print(f"  voice/state error: {voice.get('error')} {voice.get('message', '')}")
    if isinstance(voice, dict):
        input_ack = voice.get("input_ack")
        if isinstance(input_ack, dict) and not input_ack.get("ok", False):
            detail = input_ack.get("error") or input_ack.get("message") or input_ack
            print(f"  input_ack detail: {detail}")
    if isinstance(board, dict) and not board_ok and not board.get("skipped"):
        response = board.get("response", {})
        if isinstance(response, dict):
            detail = response.get("error") or response.get("message") or response
        else:
            detail = board.get("message", "")
        print(f"  board_ui detail: {detail}")
    if isinstance(direct_arm, dict) and not direct_arm_ok and not direct_arm.get("skipped"):
        detail = direct_arm.get("error") or direct_arm.get("message") or direct_arm
        print(f"  direct_arm detail: {detail}")


def main() -> int:
    args = parse_args()
    steps = build_steps(args.answer_result, args.shape_question_label)
    if args.list_steps:
        for index, step in enumerate(steps, start=1):
            print(f"{index}. {step.key} - {step.title}")
        return 0

    start_index = select_start_index(steps, args.start_at)
    active_steps = steps[start_index:]

    app = XingbaoApp()
    if args.prepare_demo_tts_cache and not args.no_tts:
        print("正在准备固定演示语音缓存...")
        print(json.dumps(app.prepare_demo_tts_cache(), ensure_ascii=False, sort_keys=True))

    board_ui_client = None
    if not args.no_board_ui:
        board_ui_client = BoardUIClient(
            host=args.board_ui_host,
            port=args.board_ui_port,
            timeout=args.board_ui_timeout,
        )
    output_device, audio_backend = resolve_output_device(args)

    print("星宝 Enter 演示流程已就绪。")
    print("终端会显示假定的语音/触控/视觉输入；每按一次 Enter，就并行触发真实输出链路。")
    if args.no_tts:
        print("当前已开启 --no-tts，只更新状态和触控桌面，不播放语音。")
    if args.no_board_ui:
        print("当前已开启 --no-board-ui，不发送触控桌面指令。")

    if not args.no_tts:
        print(f"Audio backend: {audio_backend}")

    failures: list[dict[str, Any]] = []
    direct_arm_steps = parse_step_keys(args.direct_arm_steps)
    direct_arm_enabled = not args.no_direct_arm
    direct_arm_skip_reason = ""
    if direct_arm_enabled and not args.no_board_ui and same_endpoint(
        args.board_ui_host,
        args.board_ui_port,
        args.direct_arm_host,
        args.direct_arm_port,
    ):
        direct_arm_enabled = False
        direct_arm_skip_reason = "direct_arm_endpoint_shared_with_board_ui"
        print(
            "检测到 direct_arm 与 board_ui 使用同一端口，"
            "已跳过额外直连机械臂补发，避免端口冲突。"
        )
    if direct_arm_enabled:
        direct_arm_ready = tcp_endpoint_available(
            args.direct_arm_host,
            args.direct_arm_port,
            timeout=min(max(float(args.direct_arm_timeout), 0.05), 0.3),
        )
        if not direct_arm_ready and not args.no_auto_start_arm_service:
            print("未检测到机械臂接收服务，正在尝试启动 8764 高层动作服务...")
            service_result = start_arm_action_service(
                args,
                host=args.direct_arm_host,
                port=args.direct_arm_port,
            )
            if service_result.get("ok"):
                direct_arm_ready = True
                print(f"机械臂接收服务已启动：{args.direct_arm_host}:{args.direct_arm_port}")
            else:
                detail = service_result.get("error") or service_result
                print(f"机械臂接收服务未就绪：{detail}")
                if service_result.get("log"):
                    print(f"  log: {service_result.get('log')}")
        if not direct_arm_ready:
            if args.require_direct_arm:
                print(
                    "严格要求机械臂，但 8764 高层动作服务不可用；"
                    "请先检查机械臂进程、串口和 /tmp/xingbao_arm_action_server.log。"
                )
                return 1
            direct_arm_enabled = False
            direct_arm_skip_reason = "direct_arm_endpoint_unavailable"
            print(
                "未检测到独立机械臂接收服务，已跳过额外直连机械臂补发；"
                "如需强制检查，请加 --require-direct-arm。"
            )

    total = len(active_steps)
    for offset, step in enumerate(active_steps, start=1):
        wait_for_next(
            step,
            offset,
            total,
            auto=args.auto,
            delay=args.auto_delay,
        )
        result = run_step(
            app,
            board_ui_client,
            step,
            no_tts=args.no_tts,
            input_ack=not args.no_input_ack and not args.no_tts,
            local_tts_fallback=args.local_tts_fallback,
            output_device=output_device,
            disable_arm=args.no_arm,
            direct_arm=direct_arm_enabled,
            direct_arm_steps=direct_arm_steps,
            direct_arm_host=args.direct_arm_host,
            direct_arm_port=args.direct_arm_port,
            direct_arm_timeout=args.direct_arm_timeout,
            direct_arm_skip_reason=direct_arm_skip_reason,
        )
        print_step_result(result)
        voice_failed = isinstance(result.get("voice_state"), dict) and result["voice_state"].get("error")
        board_failed = (
            isinstance(result.get("board_ui"), dict)
            and not result["board_ui"].get("ok", False)
            and not result["board_ui"].get("skipped")
        )
        direct_arm_failed = (
            isinstance(result.get("direct_arm"), dict)
            and not result["direct_arm"].get("ok", False)
            and not result["direct_arm"].get("skipped")
        )
        if voice_failed or board_failed or direct_arm_failed:
            failures.append(result)
            if args.strict:
                print("严格模式已停止。")
                return 1

    if failures:
        print(f"演示流程跑完，但有 {len(failures)} 步输出失败；通常是 TTS 或触控桌面桥接未启动。")
        return 2 if args.strict else 0

    print("演示流程已完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
