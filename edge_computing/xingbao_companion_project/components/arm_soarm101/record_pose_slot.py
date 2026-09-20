#!/usr/bin/env python3
"""只读采集一个已命名的机械臂姿态槽位。"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from arm_action_library import BASIC_EXPRESSION_SLOTS, JOINT_KEYS, atomic_write_json, normalize_pose
except ImportError:
    from .arm_action_library import BASIC_EXPRESSION_SLOTS, JOINT_KEYS, atomic_write_json, normalize_pose  # type: ignore


SLOT_LABELS = {
    "reset": "复位",
    "shake_left": "摇头左",
    "shake_right": "摇头右",
    "nod_up": "点头上",
    "nod_down": "点头下",
    "bow_up": "弯腰上",
    "bow_down": "弯腰下",
    "mouth_open": "张嘴",
    "mouth_close": "闭嘴",
    "handshake": "握手",
}

VISION_GRID_POINT_CODES = tuple(
    f"{row}{column}" for row in range(1, 7) for column in range(1, 7)
)
VISION_POINT_KIND = "xingbao_arm_vision_point"


def _service_is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _default_output(slot: str) -> Path:
    return Path(__file__).resolve().with_name("action_drafts") / "pose_slots" / f"{slot}.json"


def vision_point_output_path(point_code: str) -> Path:
    return (
        Path(__file__).resolve().with_name("action_drafts")
        / "vision_points"
        / f"{point_code}.json"
    )


def _reset_pose_path() -> Path:
    return _default_output("reset")


def _vision_point_motion() -> dict[str, Any]:
    return {
        "interpolation": "linear_joint_space",
        "segments": [
            {"from": "reset", "to": "point", "duration_seconds": 3.0},
            {"from": "point", "to": "reset", "duration_seconds": 3.0},
        ],
    }


def _grid_coordinates(point_code: str) -> dict[str, int]:
    if point_code not in VISION_GRID_POINT_CODES:
        raise ValueError(f"未知视觉点位: {point_code}")
    return {"row": int(point_code[0]), "column": int(point_code[1])}


def build_vision_point_record(
    point_code: str,
    reset_pose: object,
    target_pose: object,
    *,
    device: str,
    captured_at_utc: str,
) -> dict[str, Any]:
    """Build an inert 6×6 vision-point record from two complete joint poses."""
    return {
        "schema_version": 1,
        "kind": VISION_POINT_KIND,
        "point_code": point_code,
        "grid": _grid_coordinates(point_code),
        "captured_at_utc": captured_at_utc,
        "device": str(device),
        "reset_pose": normalize_pose(reset_pose, "reset_pose"),
        "target_pose": normalize_pose(target_pose, "target_pose"),
        "motion": _vision_point_motion(),
    }


def _load_reset_pose(path: Path) -> dict[str, float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("kind") != "xingbao_arm_pose_slot" or raw.get("slot") != "reset":
        raise ValueError(f"{path} 不是有效的复位姿态记录")
    return normalize_pose(raw.get("pose"), f"{path}.pose")


def _parse_args(slot: str | None, argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集一个星宝机械臂姿态，不会播放任何动作")
    if slot is None:
        parser.add_argument("slot", choices=BASIC_EXPRESSION_SLOTS)
    parser.add_argument("--device", default=None, help="默认读取 XINGBAO_ARM_DEVICE 或 /dev/ttyCH343USB0")
    parser.add_argument("--service-host", default="127.0.0.1")
    parser.add_argument("--service-port", type=int, default=8764)
    parser.add_argument("--output", type=Path, default=None, help="默认覆盖 action_drafts/pose_slots/<slot>.json")
    args = parser.parse_args(argv)
    if slot is not None:
        args.slot = slot
    return args


def _parse_vision_point_args(point_code: str, argv: list[str] | None) -> argparse.Namespace:
    _grid_coordinates(point_code)
    parser = argparse.ArgumentParser(
        description="采集一个 6×6 视觉点位姿态，不会播放任何动作"
    )
    parser.add_argument("--device", default=None, help="默认读取 XINGBAO_ARM_DEVICE 或 /dev/ttyCH343USB0")
    parser.add_argument("--service-host", default="127.0.0.1")
    parser.add_argument("--service-port", type=int, default=8764)
    parser.add_argument("--output", type=Path, default=None, help="默认写入 action_drafts/vision_points/<坐标>.json")
    parser.add_argument("--reset-pose", type=Path, default=_reset_pose_path(), help="已录制的复位姿态 JSON")
    args = parser.parse_args(argv)
    args.point_code = point_code
    return args


def capture_slot(slot: str, args: argparse.Namespace) -> int:
    if slot not in BASIC_EXPRESSION_SLOTS:
        raise ValueError(f"未知姿态槽位: {slot}")
    if _service_is_listening(args.service_host, args.service_port):
        print(
            "采集被安全拒绝：机械臂动作服务仍在运行。请先停止 arm_action_server_soft_nod.py。",
            file=sys.stderr,
        )
        return 2
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    device = args.device or os.getenv("XINGBAO_ARM_DEVICE", "/dev/ttyCH343USB0")
    output = args.output or _default_output(slot)
    print(f"准备采集【{SLOT_LABELS[slot]}】。本工具不发送动作，只会关闭扭矩并读取当前姿态。")
    print("请托住机械臂、确认周边无障碍；摆好位置后按 Enter。Ctrl+C 会取消且不保存。")
    input("按 Enter 连接并采集…")
    robot: Any = SO101Follower(
        SO101FollowerConfig(
            port=device,
            # 必须复用板卡服务已经验证过的校准 ID；新的 ID 没有校准文件，
            # LeRobot 会拒绝读取姿态并报 “has no calibration registered”。
            id="so101_arm_server",
            disable_torque_on_disconnect=True,
            use_degrees=True,
        )
    )
    try:
        robot.connect(calibrate=False)
        robot.bus.disable_torque()
        input("扭矩已关闭。请最后确认姿态稳定，然后按 Enter 写入该位置…")
        observation = robot.get_observation()
        pose = normalize_pose({key: observation[key] for key in JOINT_KEYS}, f"{slot}.pose")
        record = {
            "schema_version": 1,
            "kind": "xingbao_arm_pose_slot",
            "slot": slot,
            "label": SLOT_LABELS[slot],
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "device": device,
            "pose": pose,
        }
        atomic_write_json(output, record)
        print(f"已记录【{SLOT_LABELS[slot]}】：{output}")
        print("扭矩将保持关闭；可继续手动摆放下一个位置。")
        return 0
    except KeyboardInterrupt:
        print("\n已取消，未覆盖该姿态文件。", file=sys.stderr)
        return 130
    finally:
        try:
            if robot.is_connected:
                robot.bus.disable_torque()
                robot.disconnect()
        except Exception as exc:
            print(f"警告：断开机械臂时出现异常：{exc}", file=sys.stderr)


def capture_vision_point(point_code: str, args: argparse.Namespace) -> int:
    _grid_coordinates(point_code)
    if _service_is_listening(args.service_host, args.service_port):
        print(
            "采集被安全拒绝：机械臂动作服务仍在运行。请先停止 arm_action_server_soft_nod.py。",
            file=sys.stderr,
        )
        return 2
    try:
        reset_pose = _load_reset_pose(args.reset_pose)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"采集被安全拒绝：无法读取复位姿态：{exc}", file=sys.stderr)
        return 2

    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    device = args.device or os.getenv("XINGBAO_ARM_DEVICE", "/dev/ttyCH343USB0")
    output = args.output or vision_point_output_path(point_code)
    print(f"准备采集视觉点位【{point_code}】。本工具不发送动作，只会关闭扭矩并读取当前姿态。")
    print("请托住机械臂、确认周边无障碍；将末端摆到对应格子后按 Enter。Ctrl+C 会取消且不保存。")
    input("按 Enter 连接并采集…")
    robot: Any = SO101Follower(
        SO101FollowerConfig(
            port=device,
            id="so101_arm_server",
            disable_torque_on_disconnect=True,
            use_degrees=True,
        )
    )
    try:
        robot.connect(calibrate=False)
        robot.bus.disable_torque()
        input("扭矩已关闭。请最后确认末端位于目标格，按 Enter 写入该点位…")
        observation = robot.get_observation()
        target_pose = normalize_pose(
            {key: observation[key] for key in JOINT_KEYS}, f"vision_point.{point_code}.target_pose"
        )
        record = build_vision_point_record(
            point_code,
            reset_pose,
            target_pose,
            device=device,
            captured_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        atomic_write_json(output, record)
        print(f"已记录视觉点位【{point_code}】：{output}")
        print("JSON 只保存未来 3 秒去程与 3 秒回程的关节线性规则，不会播放动作。")
        return 0
    except KeyboardInterrupt:
        print("\n已取消，未覆盖该点位文件。", file=sys.stderr)
        return 130
    finally:
        try:
            if robot.is_connected:
                robot.bus.disable_torque()
                robot.disconnect()
        except Exception as exc:
            print(f"警告：断开机械臂时出现异常：{exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(None, argv)
    return capture_slot(args.slot, args)


def main_for_slot(slot: str, argv: list[str] | None = None) -> int:
    args = _parse_args(slot, argv)
    return capture_slot(slot, args)


def main_for_vision_point(point_code: str, argv: list[str] | None = None) -> int:
    args = _parse_vision_point_args(point_code, argv)
    return capture_vision_point(point_code, args)


if __name__ == "__main__":
    raise SystemExit(main())
