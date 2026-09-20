#!/usr/bin/env python
"""采集 SO101 初始位和 6 个关键点位的六关节角度。

使用方法：
    python collect_keypoints.py

启动后将机械臂放到初始位并按 Enter；随后每移动到一个关键点位按一次
Enter。全部完成后，程序会在 ``samples`` 目录生成一份 CSV 文件。
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig


DEFAULT_PORT = "/dev/ttyCH343USB0"
DEFAULT_ROBOT_ID = "so101_arm_server"

JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)

POINT_NAMES = ("initial", *(f"key_point_{index}" for index in range(1, 7)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集 SO101 的初始位和 6 个关键点位")
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"机械臂串口（默认：{DEFAULT_PORT}）")
    parser.add_argument("--robot-id", default=DEFAULT_ROBOT_ID, help="机械臂 ID")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "samples",
        help="采集文件保存目录（默认：脚本同级 samples 目录）",
    )
    return parser.parse_args()


def read_pose(robot: SO101Follower) -> dict[str, float]:
    """读取当前六个关节的角度（单位：度）。"""
    observation: dict[str, Any] = robot.get_observation()
    try:
        return {joint: float(observation[joint]) for joint in JOINT_KEYS}
    except KeyError as error:
        raise RuntimeError(f"未读取到关节数据：{error.args[0]}") from error


def save_samples(samples: list[dict[str, Any]], output_dir: Path) -> Path:
    """将完整的一组采集结果写入 CSV，避免中途退出产生不完整文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"so101_keypoints_{timestamp}.csv"
    fieldnames = ("point", "captured_at", *JOINT_KEYS)

    with output_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)

    return output_file


def main() -> None:
    args = parse_args()
    robot = SO101Follower(
        SO101FollowerConfig(
            port=args.port,
            id=args.robot_id,
            # 采集时需要人工摆放关节，断开后也必须保持无扭矩，避免机械臂
            # 因上一次采集退出而仍被锁住。
            disable_torque_on_disconnect=True,
            use_degrees=True,
        )
    )
    samples: list[dict[str, Any]] = []

    try:
        print(f"连接机械臂：{args.port}")
        robot.connect(calibrate=False)
        # SO101Follower.connect() 会配置电机并可能重新使能扭矩；必须在连接后
        # 显式关闭，之后的 get_observation() 仍可读取当前关节角度。
        robot.bus.disable_torque()
        print("舵机扭矩已关闭，采集过程中机械臂不会锁定。")
        print("\n请手动将机械臂移动到目标姿态。")
        print("启动采集：初始坐标就位后按 Enter。按 Ctrl+C 可取消本组采集。\n")

        for index, point_name in enumerate(POINT_NAMES):
            if index == 0:
                input("[初始坐标] 就位后按 Enter 采集：")
            else:
                input(f"[关键点 {index}/6] 就位后按 Enter 采集：")

            pose = read_pose(robot)
            captured_at = datetime.now().isoformat(timespec="seconds")
            samples.append({"point": point_name, "captured_at": captured_at, **pose})
            values = ", ".join(f"{joint[:-4]}={pose[joint]:.2f}" for joint in JOINT_KEYS)
            print(f"已采集 {point_name}: {values}\n")

        output_file = save_samples(samples, args.output_dir)
        print(f"采集完成，共 {len(samples)} 个点位。")
        print(f"文件已保存：{output_file}")
    except KeyboardInterrupt:
        print("\n已取消采集，未生成采集文件。")
    finally:
        if getattr(robot, "is_connected", False):
            try:
                # 采集退出、异常或 Ctrl+C 时同样保持可手动移动。
                robot.bus.disable_torque()
            finally:
                robot.disconnect()
        print("机械臂已断开，舵机扭矩保持关闭。")


if __name__ == "__main__":
    main()
