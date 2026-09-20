#!/usr/bin/env python
"""按固定顺序回放旧、新 CSV 的关键点 2。

动作顺序：
    当前姿态 -> 旧 CSV 初始位 -> 旧 CSV 关键点 2 ->
    新 CSV 关键点 2 -> 旧 CSV 初始位

坐标已从下列采集文件固化到本程序，运行时不会读取 CSV：
    - 旧：so101_keypoints_20260809_063559.csv
    - 新：so101_keypoints_20260809_063726.csv

执行前请确认机械臂周边无人、无障碍物，且没有其他动作服务占用串口。
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig


DEFAULT_PORT = "/dev/ttyCH343USB0"
DEFAULT_ROBOT_ID = "so101_arm_server"
# 每段约 3.6 秒：相比原回放默认的 1.8 秒更平缓，降低关节切换速度。
STEPS = 90
STEP_DELAY = 0.04

JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)

# 旧 CSV：so101_keypoints_20260809_063559.csv / point=initial
OLD_INITIAL = {
    "shoulder_pan.pos": -2.3736263736263736,
    "shoulder_lift.pos": -48.13186813186813,
    "elbow_flex.pos": -3.7362637362637363,
    "wrist_flex.pos": -16.175824175824175,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 3.413654618473896,
}

# 旧 CSV：so101_keypoints_20260809_063559.csv / point=key_point_2
OLD_KEY_POINT_2 = {
    "shoulder_pan.pos": -2.021978021978022,
    "shoulder_lift.pos": 21.318681318681318,
    "elbow_flex.pos": -57.45054945054945,
    "wrist_flex.pos": -42.989010989010985,
    "wrist_roll.pos": 78.98901098901099,
    "gripper.pos": 54.81927710843374,
}

# 新 CSV：so101_keypoints_20260809_063726.csv / point=key_point_2
NEW_KEY_POINT_2 = {
    "shoulder_pan.pos": -2.021978021978022,
    "shoulder_lift.pos": 8.131868131868131,
    "elbow_flex.pos": 45.142857142857146,
    "wrist_flex.pos": -147.69230769230768,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 54.41767068273092,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按固定顺序回放旧、新 CSV 的关键点 2")
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"机械臂串口（默认：{DEFAULT_PORT}）")
    parser.add_argument("--robot-id", default=DEFAULT_ROBOT_ID, help="机械臂 ID")
    parser.add_argument("--steps", type=int, default=STEPS, help=f"每段插值步数（默认：{STEPS}）")
    parser.add_argument("--step-delay", type=float, default=STEP_DELAY, help=f"每步间隔秒数（默认：{STEP_DELAY}）")
    args = parser.parse_args()
    if args.steps <= 0 or args.step_delay < 0:
        parser.error("--steps 必须大于 0，--step-delay 不能小于 0")
    return args


def get_pose(robot: SO101Follower) -> dict[str, float]:
    observation: dict[str, Any] = robot.get_observation()
    return {joint: float(observation[joint]) for joint in JOINT_KEYS}


def move_to_action(robot: SO101Follower, target: dict[str, float], steps: int, step_delay: float) -> None:
    """沿用 play_keypoint_action.py 的 smoothstep 平滑插值。"""
    start = get_pose(robot)
    for index in range(1, steps + 1):
        ratio = index / steps
        ratio = ratio * ratio * ratio * (ratio * (ratio * 6 - 15) + 10)
        action = {
            joint: start[joint] + (target[joint] - start[joint]) * ratio
            for joint in JOINT_KEYS
        }
        robot.send_action(action)
        time.sleep(step_delay)


def run_sequence(robot: SO101Follower, steps: int, step_delay: float) -> None:
    sequence = (
        ("旧 CSV 初始坐标", OLD_INITIAL),
        ("旧 CSV 的 2 坐标", OLD_KEY_POINT_2),
        ("新 CSV 的 2 坐标", NEW_KEY_POINT_2),
        ("旧 CSV 初始坐标（回位）", OLD_INITIAL),
    )
    for index, (label, target) in enumerate(sequence, start=1):
        print(f"  {index}/4：移动到{label}…")
        move_to_action(robot, target, steps, step_delay)
    print("动作完成。")


def main() -> None:
    args = parse_args()
    robot = SO101Follower(
        SO101FollowerConfig(
            port=args.port,
            id=args.robot_id,
            disable_torque_on_disconnect=False,
            use_degrees=True,
        )
    )
    try:
        print(f"连接机械臂：{args.port}")
        robot.connect(calibrate=False)
        run_sequence(robot, args.steps, args.step_delay)
    except KeyboardInterrupt:
        print("\n已中断动作，机械臂保持当前位置。")
    finally:
        if getattr(robot, "is_connected", False):
            robot.disconnect()
        print("机械臂已断开。")


if __name__ == "__main__":
    main()
