"""Send one non-audio speech_request to verify the reverse bridge."""

from __future__ import annotations

import argparse
import json
import socket
import uuid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--play", action="store_true", help="Actually synthesize and play the prompt.")
    parser.add_argument("--text", default="游戏语音通道测试成功")
    args = parser.parse_args()
    message = {
        "version": "1.0",
        "message_id": str(uuid.uuid4()),
        "type": "speech_request",
        "source": "smoke_test",
        "target": "central_controller",
        "payload": {
            "text": args.text,
            "page": "smoke_test",
            "request_tts": bool(args.play),
        },
    }
    with socket.create_connection((args.host, args.port), timeout=3.0) as sock:
        sock.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        raw = sock.makefile("rb").readline()
    response = json.loads(raw.decode("utf-8-sig"))
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
