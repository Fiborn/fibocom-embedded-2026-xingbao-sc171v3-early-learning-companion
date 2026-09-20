#!/usr/bin/env python3
"""Prepare the fixed Xingbao vision reminder WAV cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app import VISION_TTS_CACHE_FILES, XingbaoApp


def cache_report(app: XingbaoApp) -> dict[str, object]:
    items = []
    ready = 0
    for text, filename in VISION_TTS_CACHE_FILES.items():
        path = Path("work/cache") / filename
        status = "ready" if app.game_speech_cache.is_valid(path) else "missing"
        ready += status == "ready"
        items.append({"text": text, "path": str(path), "status": status})
    return {
        "ok": ready == len(items),
        "voice_id": app.voice_profile.id,
        "counts": {"total": len(items), "ready": ready, "missing": len(items) - ready},
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cache fixed Xingbao vision reminder speech.")
    parser.add_argument("--check", action="store_true", help="Only report cache status; do not call TTS.")
    args = parser.parse_args()

    app = XingbaoApp()
    report = cache_report(app) if args.check else app.prepare_vision_tts_cache()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
