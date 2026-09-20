#!/usr/bin/env python3
"""把九个独立姿态记录合成为不可执行的基础表意动作草稿。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from arm_action_library import BASIC_EXPRESSION_SLOTS, ActionValidationError, atomic_write_json, build_basic_expression_bundle, normalize_pose
except ImportError:
    from .arm_action_library import BASIC_EXPRESSION_SLOTS, ActionValidationError, atomic_write_json, build_basic_expression_bundle, normalize_pose  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合成摇头、点头、弯腰、嘴巴、握手的录制草稿")
    parser.add_argument("--poses-dir", type=Path, default=Path(__file__).resolve().with_name("action_drafts") / "pose_slots")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    captured = {}
    try:
        for slot in BASIC_EXPRESSION_SLOTS:
            source = args.poses_dir / f"{slot}.json"
            record = json.loads(source.read_text(encoding="utf-8"))
            if record.get("kind") != "xingbao_arm_pose_slot" or record.get("slot") != slot:
                raise ActionValidationError(f"{source} 不是【{slot}】的有效姿态记录")
            captured[slot] = normalize_pose(record.get("pose"), f"{source}.pose")
        bundle = build_basic_expression_bundle(captured)
    except (OSError, json.JSONDecodeError, ActionValidationError) as exc:
        print(f"无法合成草稿：{exc}", file=sys.stderr)
        return 2
    output = args.output or (
        Path(__file__).resolve().with_name("action_drafts")
        / f"basic_expressions_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    bundle["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
    bundle["source_pose_dir"] = str(args.poses_dir)
    atomic_write_json(output, bundle)
    print(f"已合成动作草稿：{output}")
    print("草稿尚未启用：摇头/点头/嘴巴均使用两个来回，弯腰下→上→复位，握手回位很慢。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
