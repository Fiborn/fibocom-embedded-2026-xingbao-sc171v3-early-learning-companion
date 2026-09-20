#!/usr/bin/env python3
"""审核并显式启用基础表意动作草稿。

默认只做校验和预览；只有同时传入 ``--approve`` 与固定确认短语才会原子替换
动作库。此工具不连接、也不移动机械臂；启用后仍需要重启动作服务才会生效。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from arm_action_library import (
        DEFAULT_REGISTRY_PATH,
        ActionValidationError,
        atomic_write_json,
        load_registry,
        registry_from_basic_expression_bundle,
    )
except ImportError:
    from .arm_action_library import (  # type: ignore
        DEFAULT_REGISTRY_PATH,
        ActionValidationError,
        atomic_write_json,
        load_registry,
        registry_from_basic_expression_bundle,
    )


CONFIRMATION = "ENABLE_BASIC_EXPRESSIONS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审核并启用摇头、点头、弯腰、嘴巴、握手录制草稿")
    parser.add_argument("draft", type=Path, help="record_basic_expressions.py 生成的草稿 JSON")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--approve", action="store_true", help="通过安全校验后写入动作库")
    parser.add_argument("--confirm", default="", help=f"启用时必须精确填写：{CONFIRMATION}")
    return parser.parse_args()


def _summarize(candidate: dict) -> None:
    print("安全校验通过。候选动作：")
    for name, action in candidate["actions"].items():
        print(
            f"- {name}: {action['description']}｜序列={action['sequence']}｜"
            f"估算={action['estimated_duration_seconds'] * 1000:.0f}ms"
        )


def main() -> int:
    args = parse_args()
    try:
        bundle = json.loads(args.draft.read_text(encoding="utf-8"))
        current = load_registry(args.registry)
        candidate = registry_from_basic_expression_bundle(bundle, current)
    except (OSError, json.JSONDecodeError, ActionValidationError) as exc:
        print(f"审核失败：{exc}", file=sys.stderr)
        return 2
    _summarize(candidate)
    if not args.approve:
        print("仅预览，尚未启用。确认机械臂周边安全且姿态正确后，再使用 --approve。")
        return 0
    if args.confirm != CONFIRMATION:
        print(f"拒绝启用：--confirm 必须精确为 {CONFIRMATION}", file=sys.stderr)
        return 2
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.registry.with_name(f"{args.registry.stem}.{timestamp}.backup.json")
    shutil.copy2(args.registry, backup)
    atomic_write_json(args.registry, candidate)
    print(f"已启用动作库：{args.registry}")
    print(f"原动作库备份：{backup}")
    print("请在无人靠近机械臂时重启动作服务；未重启前，当前服务仍保持原动作库。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
