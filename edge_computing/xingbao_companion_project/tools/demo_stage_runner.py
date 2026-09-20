"""Run a short scripted demo flow for the Xingbao board presentation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import XingbaoApp
from core.board_ui_client import BoardUIClient
from multimodal.audio_io import BOARD_APLAY_OUTPUT_DEVICE


STAGE_ORDER = (
    "open_game",
    "pick_game",
    "pick_difficulty",
    "answer_correct",
    "answer_wrong",
    "face_too_close",
    "drink_water",
)


def _expression_event(
    text: str,
    *,
    screen_text: str,
    emotion: str = "smile",
) -> dict[str, Any]:
    return {
        "type": "xingbao_expression_request",
        "source": "demo_script",
        "priority": 1,
        "payload": {
            "intent": "demo_script",
            "text": text,
            "screen_text": screen_text,
            "emotion": emotion,
            "tts": True,
            "interrupt_policy": "queue",
        },
    }


def _stage_payload(stage: str) -> dict[str, Any] | None:
    if stage == "pick_game":
        return _expression_event(
            "请选择一个游戏。",
            screen_text="请选择一个游戏",
            emotion="smile",
        )
    if stage == "pick_difficulty":
        return _expression_event(
            "请选择一个难度。",
            screen_text="请选择一个难度",
            emotion="thinking",
        )
    if stage == "answer_correct":
        return _expression_event(
            "太棒了，你答对了。",
            screen_text="答对啦",
            emotion="happy",
        )
    if stage == "answer_wrong":
        return _expression_event(
            "没关系，这一题我们再试一次。",
            screen_text="再试一次",
            emotion="encouraging",
        )
    if stage == "face_too_close":
        return _expression_event(
            "你离屏幕有点近啦，往后坐一点吧。",
            screen_text="往后坐一点",
            emotion="caring",
        )
    if stage == "drink_water":
        return _expression_event(
            "你平时也要注意喝水哦。",
            screen_text="记得喝水哦",
            emotion="caring",
        )
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a board demo stage or full sequence.")
    parser.add_argument(
        "--stage",
        choices=STAGE_ORDER,
        default="open_game",
        help="Run one demo stage.",
    )
    parser.add_argument(
        "--sequence",
        action="store_true",
        help="Run the full scripted sequence instead of a single stage.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=10.0,
        help="Delay between scripted stages when --sequence is enabled.",
    )
    parser.add_argument(
        "--board-ui-host",
        default="127.0.0.1",
        help="Board UI bridge host.",
    )
    parser.add_argument(
        "--board-ui-port",
        type=int,
        default=8765,
        help="Board UI bridge port.",
    )
    parser.add_argument(
        "--board-ui-timeout",
        type=float,
        default=3.0,
        help="Board UI bridge timeout.",
    )
    parser.add_argument(
        "--board-audio-output",
        action="store_true",
        help="Play TTS through board ALSA output.",
    )
    parser.add_argument(
        "--no-speak",
        action="store_true",
        help="Update the screen only and skip TTS.",
    )
    parser.add_argument(
        "--local-tts-fallback",
        action="store_true",
        help="Allow local TTS fallback when cloud TTS fails.",
    )
    return parser.parse_args()


def _run_stage(
    app: XingbaoApp,
    board_ui_client: BoardUIClient,
    stage: str,
    *,
    no_tts: bool,
    local_tts_fallback: bool,
    output_device: int | None,
) -> dict[str, Any]:
    if stage == "open_game":
        return app.run_coordinated_text(
            "星宝我要玩游戏啦",
            apply_output=True,
            no_tts=no_tts,
            local_tts_fallback=local_tts_fallback,
            output_device=output_device,
            board_ui_client=board_ui_client,
        )

    payload = _stage_payload(stage)
    if payload is None:
        raise ValueError(f"Unsupported stage: {stage}")
    return app.run_coordinated_event_json(
        json.dumps(payload, ensure_ascii=False),
        apply_output=True,
        no_tts=no_tts,
        local_tts_fallback=local_tts_fallback,
        output_device=output_device,
        board_ui_client=board_ui_client,
    )


def main() -> int:
    args = parse_args()
    app = XingbaoApp()
    board_ui_client = BoardUIClient(
        host=args.board_ui_host,
        port=args.board_ui_port,
        timeout=args.board_ui_timeout,
    )
    output_device = BOARD_APLAY_OUTPUT_DEVICE if args.board_audio_output else None

    if args.sequence:
        results: list[dict[str, Any]] = []
        for index, stage in enumerate(STAGE_ORDER):
            results.append(
                {
                    "stage": stage,
                    "result": _run_stage(
                        app,
                        board_ui_client,
                        stage,
                        no_tts=args.no_speak,
                        local_tts_fallback=args.local_tts_fallback,
                        output_device=output_device,
                    ),
                }
            )
            if index < len(STAGE_ORDER) - 1:
                time.sleep(max(0.0, args.delay_seconds))
        print(json.dumps({"ok": True, "sequence": results}, ensure_ascii=False, sort_keys=True))
        return 0

    result = _run_stage(
        app,
        board_ui_client,
        args.stage,
        no_tts=args.no_speak,
        local_tts_fallback=args.local_tts_fallback,
        output_device=output_device,
    )
    print(json.dumps({"ok": True, "stage": args.stage, "result": result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
