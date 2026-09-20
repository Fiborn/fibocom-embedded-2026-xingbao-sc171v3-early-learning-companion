"""Patch a touch-game demo copy so choices emit central demo events."""

from __future__ import annotations

import argparse
from pathlib import Path


def _replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch marker not found: {old[:80]!r}")
    return text.replace(old, new, 1)


def patch_app_py(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original

    if "import socket\n" not in text:
        text = _replace_once(
            text,
            "import math\nfrom datetime import datetime\n",
            "import json\nimport math\nimport os\nimport socket\nimport uuid\nfrom datetime import datetime\n",
        )

    if "self.demo_event_enabled" not in text:
        text = _replace_once(
            text,
            "        self.on_speech_request = on_speech_request\n",
            (
                "        self.on_speech_request = on_speech_request\n"
                "        self.demo_event_enabled = os.environ.get(\"XINGBAO_DEMO_EVENTS\", \"1\") != \"0\"\n"
                "        self.demo_disable_game_speech = os.environ.get(\"XINGBAO_DEMO_DISABLE_GAME_SPEECH\", \"1\") != \"0\"\n"
                "        self.demo_force_answer_sequence = os.environ.get(\"XINGBAO_DEMO_FORCE_ANSWER_SEQUENCE\", \"0\") != \"0\"\n"
                "        self.demo_answer_count = 0\n"
                "        self.demo_event_host = os.environ.get(\"XINGBAO_DEMO_EVENT_HOST\", \"127.0.0.1\")\n"
                "        self.demo_event_port = int(os.environ.get(\"XINGBAO_DEMO_EVENT_PORT\", \"8766\"))\n"
            ),
        )

    if "and not self.demo_disable_game_speech" not in text:
        text = _replace_once(
            text,
            "        if self.on_speech_request:\n",
            "        if self.on_speech_request and not self.demo_disable_game_speech:\n",
        )

    if "def _submit_demo_event" not in text:
        helper = '''
    def _submit_demo_event(self, event_name, payload=None):
        if not self.demo_event_enabled:
            return
        body = dict(payload or {})
        body["event"] = event_name
        message = {
            "version": "1.0",
            "message_id": str(uuid.uuid4()),
            "type": "game_event",
            "source": "touch_game_demo",
            "target": "central_controller",
            "payload": body,
        }
        try:
            encoded = (json.dumps(message, ensure_ascii=False) + "\\n").encode("utf-8")
            with socket.create_connection(
                (self.demo_event_host, self.demo_event_port),
                timeout=0.25,
            ) as sock:
                sock.sendall(encoded)
                print(f"[demo-event] sent {event_name} {body}", flush=True)
                try:
                    sock.settimeout(0.25)
                    sock.recv(4096)
                except OSError:
                    pass
        except OSError as exc:
            print(f"[demo-event] failed {event_name}: {exc}", flush=True)

'''
        text = _replace_once(text, "    def show_state(self, mood, page=None):\n", helper + "    def show_state(self, mood, page=None):\n")

    if "demo_force_answer_sequence" in text and "actual_correct" not in text:
        text = _replace_once(
            text,
            "        self.log(evt[self.game.game_id], page=\"game_running\", payload=payload)\n",
            (
                "        self.log(evt[self.game.game_id], page=\"game_running\", payload=payload)\n"
                "        self.demo_answer_count += 1\n"
                "        self._submit_demo_event(\"answer_result\", {\n"
                "            \"game_id\": self.game.game_id,\n"
                "            \"selected\": selected,\n"
                "            \"target\": target,\n"
                "            \"correct\": bool(result.correct),\n"
                "            \"actual_correct\": bool(result.correct),\n"
                "            \"message\": result.message,\n"
                "            \"demo_answer_index\": self.demo_answer_count,\n"
                "        })\n"
            ),
        )

    if "\"answer_result\"" not in text and "actual_correct" in text:
        text = _replace_once(
            text,
            "        if self.demo_force_answer_sequence:\n"
            "            demo_event = \"answer_correct\" if self.demo_answer_count == 1 else \"answer_wrong\"\n"
            "        else:\n"
            "            demo_event = \"answer_correct\" if result.correct else \"answer_wrong\"\n"
            "        self._submit_demo_event(demo_event, {\n"
            "            \"game_id\": self.game.game_id,\n"
            "            \"selected\": selected,\n"
            "            \"target\": target,\n"
            "            \"actual_correct\": bool(result.correct),\n"
            "            \"demo_answer_index\": self.demo_answer_count,\n"
            "        })\n",
            "        self._submit_demo_event(\"answer_result\", {\n"
            "            \"game_id\": self.game.game_id,\n"
            "            \"selected\": selected,\n"
            "            \"target\": target,\n"
            "            \"correct\": bool(result.correct),\n"
            "            \"actual_correct\": bool(result.correct),\n"
            "            \"message\": result.message,\n"
            "            \"demo_answer_index\": self.demo_answer_count,\n"
            "        })\n",
        )

    if "difficulty_selected" not in text:
        text = _replace_once(
            text,
            "        elif key.startswith(\"difficulty:\") and self.pending_game_id:\n"
            "            self.start_game(self.pending_game_id, int(key.split(\":\", 1)[1]))\n",
            "        elif key.startswith(\"difficulty:\") and self.pending_game_id:\n"
            "            difficulty = int(key.split(\":\", 1)[1])\n"
            "            game_id = self.pending_game_id\n"
            "            self.start_game(game_id, difficulty)\n"
            "            self.demo_answer_count = 0\n"
            "            self._submit_demo_event(\"difficulty_selected\", {\"game_id\": game_id, \"difficulty\": difficulty})\n",
        )

    if (
        "self._submit_demo_event(\"difficulty_selected\"" in text
        and "self.demo_answer_count = 0\n            self._submit_demo_event(\"difficulty_selected\"" not in text
    ):
        text = _replace_once(
            text,
            "            self.start_game(game_id, difficulty)\n"
            "            self._submit_demo_event(\"difficulty_selected\", {\"game_id\": game_id, \"difficulty\": difficulty})\n",
            "            self.start_game(game_id, difficulty)\n"
            "            self.demo_answer_count = 0\n"
            "            self._submit_demo_event(\"difficulty_selected\", {\"game_id\": game_id, \"difficulty\": difficulty})\n",
        )

    if "[demo-event] sent" not in text:
        text = _replace_once(
            text,
            "                sock.sendall(encoded)\n"
            "                try:\n",
            "                sock.sendall(encoded)\n"
            "                print(f\"[demo-event] sent {event_name} {body}\", flush=True)\n"
            "                try:\n",
        )

    if "[demo-event] failed" not in text:
        text = _replace_once(
            text,
            "        except OSError:\n"
            "            pass\n",
            "        except OSError as exc:\n"
            "            print(f\"[demo-event] failed {event_name}: {exc}\", flush=True)\n",
        )

    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install touch-game demo event hooks.")
    parser.add_argument(
        "project_dir",
        nargs="?",
        default=".",
        help="Touch game project directory containing src/app.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_dir).resolve()
    app_py = root / "src" / "app.py"
    if not app_py.exists():
        raise SystemExit(f"Cannot find {app_py}")
    changed = patch_app_py(app_py)
    print(f"patched={changed} file={app_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
