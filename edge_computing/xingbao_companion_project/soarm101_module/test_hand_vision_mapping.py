#!/usr/bin/env python3
"""人工验收：验证摄像头手部 2x3 网格到 SO-101 编号动作的映射。

本程序不会主动向 10000 发送动作。它只向 10001 发送 enable/disable；
测试人员把手放到摄像头对应网格，观察机械臂是否由视觉模块自动发送正确编号。
"""

from __future__ import annotations

import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.hand_control_client import send_hand_control_command


CASES = (
    ("11", "左上", "把手放在画面左上区域"),
    ("12", "上中", "把手放在画面上方中间区域"),
    ("13", "右上", "把手放在画面右上区域"),
    ("21", "左下", "把手放在画面左下区域"),
    ("22", "下中", "把手放在画面下方中间区域"),
    ("23", "右下", "把手放在画面右下区域"),
)


def assert_port_open(port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return
    except OSError as exc:
        raise SystemExit(f"无法连接本机 {port} 端口：{exc}") from exc


def main() -> int:
    print("星宝手部视觉 → 机械臂人工映射验收")
    print("请先确保机械臂周围无人、无遮挡，摄像头能看清手部。")
    input("确认安全后按 Enter 开始，输入 Ctrl+C 可取消：")
    assert_port_open(10000)
    response = send_hand_control_command("enable")
    if not response.get("ok") or not response.get("hand_recognition_enabled"):
        raise SystemExit(f"无法启用手部识别：{response}")
    print("手部识别已启用。每个位置需保持约 2 秒；同一位置只应触发一次。\n")

    results: list[dict[str, object]] = []
    try:
        for command, label, instruction in CASES:
            print(f"[{command} / {label}] {instruction}")
            outcome = input("观察机械臂后输入 y=正确、n=错误、s=跳过、q=结束：").strip().lower()
            if outcome in {"q", "quit", "exit"}:
                break
            results.append(
                {
                    "expected_command": command,
                    "position": label,
                    "result": {"y": "pass", "n": "fail", "s": "skipped"}.get(outcome, "invalid"),
                }
            )
            input("请先把手完全移出画面，等待机械臂回初始位后按 Enter 继续：")
    finally:
        disable = send_hand_control_command("disable")
        print(f"已关闭手部识别：{disable}")

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "passed": sum(item["result"] == "pass" for item in results),
        "failed": sum(item["result"] == "fail" for item in results),
    }
    report_path = Path(__file__).with_name(
        f"hand_vision_mapping_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"验收记录已保存：{report_path}")
    return 0 if report["failed"] == 0 and len(results) == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
