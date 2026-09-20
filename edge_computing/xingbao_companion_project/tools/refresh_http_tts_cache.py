#!/usr/bin/env python3
"""Rebuild all fixed Xingbao TTS caches with the regular HTTP TTS client.

Run from the project root (the script also supports being started elsewhere):

    set -a; . /home/fibo/.config/xingbao/runtime.env; set +a
    /usr/bin/python3 tools/refresh_http_tts_cache.py --direct

The script overwrites every authored game and fixed-prompt cache entry.  It
does not touch microphone captures, conversation reply files, or other
runtime-only WAVs whose source text is not a fixed prompt.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use regular HTTP TTS to fully rebuild fixed local WAV caches."
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Bypass the configured HTTP proxy for this cache refresh.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # Import after argument parsing so ``--help`` is usable even on a Python
    # environment that is not the board's runtime interpreter.
    from app import DEMO_TTS_CACHE_FILES, XingbaoApp
    from core.settings import AppSettings

    settings = AppSettings.load()
    if args.direct:
        settings = replace(settings, proxy_mode="none")
    app = XingbaoApp(settings=settings)

    targets: list[tuple[str, Path, str]] = []
    for entry in app.game_speech_cache.entries:
        targets.append(
            (
                entry.text,
                app.game_speech_cache.resolve_path(entry.text, app.voice_profile.id),
                f"game:{entry.entry_id}",
            )
        )
    for text, filename in DEMO_TTS_CACHE_FILES.items():
        targets.append((text, PROJECT_ROOT / "work" / "cache" / filename, "fixed"))

    # One text/path can appear in more than one fixed cache group.
    deduplicated: list[tuple[str, Path, str]] = []
    seen_paths: set[Path] = set()
    for text, path, group in targets:
        resolved = path.resolve()
        if resolved not in seen_paths:
            seen_paths.add(resolved)
            deduplicated.append((text, path, group))

    total = len(deduplicated)
    created = 0
    failures: list[dict[str, str]] = []
    print(
        json.dumps(
            {
                "event": "http_tts_cache_refresh_started",
                "total": total,
                "proxy_mode": settings.proxy_mode,
                "voice_profile": app.voice_profile.id,
                "model": app.voice_profile.model,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    for index, (text, path, group) in enumerate(deduplicated, start=1):
        try:
            app._synthesize_cache_atomic(text, path, tts_client=app.tts_client)
            if not app.game_speech_cache.is_valid(path):
                raise RuntimeError("post-write WAV validation failed")
            created += 1
            status = "created"
        except Exception as exc:  # keep processing so the final report is complete
            status = "failed"
            failures.append(
                {
                    "index": str(index),
                    "group": group,
                    "text": text,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(
            json.dumps(
                {
                    "event": "http_tts_cache_item",
                    "index": index,
                    "total": total,
                    "status": status,
                    "group": group,
                    "path": str(path),
                    "text": text,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    report = {
        "event": "http_tts_cache_refresh_finished",
        "ok": not failures,
        "created": created,
        "failed": len(failures),
        "total": total,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
