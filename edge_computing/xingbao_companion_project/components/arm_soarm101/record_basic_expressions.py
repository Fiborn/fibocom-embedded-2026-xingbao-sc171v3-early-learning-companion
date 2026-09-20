#!/usr/bin/env python3
"""交互式采集星宝的九个基础姿态，写入不可执行的草稿 JSON。

本工具不会发送任何 Goal_Position。它只会在机械臂动作服务停止后连接串口、
关闭扭矩、读取当前位置。草稿不能被 TCP 服务直接执行，必须由
``promote_basic_expressions.py`` 审核并显式启用。
"""

from __future__ import annotations

import argparse
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # 支持 ``python hardware/soarm101/record_basic_expressions.py``。
    from arm_action_library import (
        BASIC_EXPRESSION_SLOTS,
        JOINT_KEYS,
        atomic_write_json,
        build_basic_expression_bundle,
        normalize_pose,
    )
except ImportError:  # 支持模块化测试。
    from .arm_action_library import (  # type: ignore
        BASIC_EXPRESSION_SLOTS,
        JOINT_KEYS,
        atomic_write_json,
        build_basic_expression_bundle,
        normalize_pose,
    )


SLOT_INSTRUCTIONS = {
    "reset": "复位：机械臂自然、稳定、无遮挡的中立姿态",
    "shake_left": "摇头左：表达“不/不同意”时的左侧姿态",
    "shake_right": "摇头右：表达“不/不同意”时的右侧姿态",
    "nod_up": "点头上：点头动作的上方姿态",
    "nod_down": "点头下：点头动作的下方姿态",
    "bow_up": "弯腰上：弯腰恢复前的上方姿态",
    "bow_down": "弯腰下：弯腰表达时的下方姿态",
}


def _service_is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _read_pose(robot: Any) -> dict[str, float]:
    observation = robot.get_observation()
    return normalize_pose({key: observation[key] for key in JOINT_KEYS}, "captured_pose")


def _print_pose(pose: dict[str, float]) -> None:
    print("  " + ", ".join(f"{key.removesuffix('.pos')}={pose[key]:.1f}" for key in JOINT_KEYS))


def _default_output() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(__file__).resolve().with_name("action_drafts") / f"basic_expressions_{timestamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集星宝摇头、点头、弯腰和爪子的九个姿态草稿")
    parser.add_argument("--device", default=None, help="机械臂串口；默认读取 XINGBAO_ARM_DEVICE 或 /dev/ttyCH343USB0")
    parser.add_argument("--service-host", default="127.0.0.1")
    parser.add_argument("--service-port", type=int, default=8764)
    parser.add_argument("--output", type=Path, default=None, help="草稿输出路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if _service_is_listening(args.service_host, args.service_port):
        print(
            "录制被安全拒绝：机械臂动作服务仍在运行。\n"
            "请先停止 arm_action_server_soft_nod.py；录制期间不要让语音服务发送机械臂动作。",
            file=sys.stderr,
        )
        return 2

    import os
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    device = args.device or os.getenv("XINGBAO_ARM_DEVICE", "/dev/ttyCH343USB0")
    output = args.output or _default_output()
    print("即将进入只读录制模式：工具不播放动作，扭矩会关闭，机械臂可由人工缓慢摆动。")
    print("请始终托住机械臂，避开线缆、屏幕与儿童活动区域。按 Ctrl+C 可中止且不会写入草稿。")
    input("确认周围安全后按 Enter 连接机械臂…")

    robot = SO101Follower(
        SO101FollowerConfig(
            port=device,
            id="so101_arm_server",
            disable_torque_on_disconnect=True,
            use_degrees=True,
        )
    )
    captured: dict[str, dict[str, float]] = {}
    try:
        robot.connect(calibrate=False)
        robot.bus.disable_torque()
        print("已关闭扭矩。现在请逐个手动摆姿态；每个姿态稳定后按 Enter 采集。")
        for index, slot in enumerate(BASIC_EXPRESSION_SLOTS, start=1):
            input(f"[{index}/{len(BASIC_EXPRESSION_SLOTS)}] {SLOT_INSTRUCTIONS[slot]}。摆好后按 Enter 采集…")
            pose = _read_pose(robot)
            captured[slot] = pose
            print(f"已采集 {slot}：")
            _print_pose(pose)
        bundle = build_basic_expression_bundle(captured)
        bundle["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
        bundle["device"] = device
        atomic_write_json(output, bundle)
        print(f"草稿已保存：{output}")
        print("草稿尚未启用，也不会被机械臂服务执行。请先目视复核姿态，再运行审核启用工具。")
        return 0
    except KeyboardInterrupt:
        print("\n录制已中止，未写入动作草稿。", file=sys.stderr)
        return 130
    finally:
        try:
            if robot.is_connected:
                robot.bus.disable_torque()
                robot.disconnect()
        except Exception as exc:  # 不能因清理日志失败掩盖录制结果。
            print(f"警告：断开机械臂时出现异常：{exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
