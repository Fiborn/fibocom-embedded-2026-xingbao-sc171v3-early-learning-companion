#!/usr/bin/env python
"""按编号回放采集的 SO101 关键点动作。

动作链：当前姿态 -> 初始位置 -> 目标关键点 -> 初始位置。

使用方法：
    python play_keypoint_action.py
    python play_keypoint_action.py --sample-index 2
    python play_keypoint_action.py --csv samples/so101_keypoints_YYYYMMDD_HHMMSS.csv

未指定 ``--csv`` 或 ``--sample-index`` 时，启动后列出 samples 目录中的采集
文件，可输入编号选择。列表按最新文件在前排序。
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig


DEFAULT_PORT = "/dev/ttyCH343USB0"
DEFAULT_ROBOT_ID = "so101_arm_server"
SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
STEPS = 60
STEP_DELAY = 0.03

JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回放 SO101 采集的关键点动作")
    parser.add_argument("--csv", type=Path, help="要回放的采集 CSV 文件（优先于 --sample-index）")
    parser.add_argument("--sample-index", type=int, help="采集文件编号，按启动时列表中显示的顺序，从 1 开始")
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"机械臂串口（默认：{DEFAULT_PORT}）")
    parser.add_argument("--robot-id", default=DEFAULT_ROBOT_ID, help="机械臂 ID")
    parser.add_argument("--steps", type=int, default=STEPS, help=f"每段插值步数（默认：{STEPS}）")
    parser.add_argument("--step-delay", type=float, default=STEP_DELAY, help=f"每步间隔秒数（默认：{STEP_DELAY}）")
    args = parser.parse_args()
    if args.steps <= 0 or args.step_delay < 0:
        parser.error("--steps 必须大于 0，--step-delay 不能小于 0")
    if args.sample_index is not None and args.sample_index <= 0:
        parser.error("--sample-index 必须大于 0")
    return args


def sample_csv_files() -> list[Path]:
    """返回全部采集文件，最新文件排在最前，便于按编号选择。"""
    files = sorted(
        SAMPLES_DIR.glob("so101_keypoints_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"未找到采集文件，请通过 --csv 指定文件，或先在 {SAMPLES_DIR} 完成采集。")
    return files


def select_csv(files: list[Path], selected_index: int | None = None) -> Path:
    """按编号选择 CSV；编号从 1 开始，输入 q 可以在连接机械臂前退出。"""
    print("可用采集文件（最新在前）：")
    for index, path in enumerate(files, start=1):
        print(f"  [{index}] {path.name}")

    if selected_index is None:
        while True:
            command = input(f"请选择采集文件编号 [1-{len(files)}/q]：").strip().lower()
            if command in {"q", "quit", "exit"}:
                raise KeyboardInterrupt
            try:
                selected_index = int(command)
            except ValueError:
                print("请输入文件编号，或输入 q 退出。")
                continue
            break

    if not 1 <= selected_index <= len(files):
        raise ValueError(f"采集文件编号超出范围：{selected_index}（可选 1-{len(files)}）")
    selected = files[selected_index - 1]
    print(f"已选择 [{selected_index}] {selected.name}\n")
    return selected


def load_poses(csv_file: Path) -> dict[str, dict[str, float]]:
    """加载并校验初始位与 6 个关键点的六关节角度。"""
    if not csv_file.is_file():
        raise FileNotFoundError(f"采集文件不存在：{csv_file}")

    with csv_file.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        required_columns = {"point", *JOINT_KEYS}
        actual_columns = set(reader.fieldnames or [])
        missing_columns = required_columns - actual_columns
        if missing_columns:
            raise ValueError(f"CSV 缺少列：{', '.join(sorted(missing_columns))}")

        poses: dict[str, dict[str, float]] = {}
        for row in reader:
            point = (row.get("point") or "").strip()
            if point in poses:
                raise ValueError(f"CSV 中存在重复点位：{point}")
            try:
                poses[point] = {joint: float(row[joint]) for joint in JOINT_KEYS}
            except (TypeError, ValueError) as error:
                raise ValueError(f"点位 {point or '<空>'} 的关节角度不是有效数字") from error

    expected_points = {"initial", *(f"key_point_{index}" for index in range(1, 7))}
    missing_points = expected_points - set(poses)
    if missing_points:
        raise ValueError(f"CSV 缺少点位：{', '.join(sorted(missing_points))}")
    return poses


def get_pose(robot: SO101Follower) -> dict[str, float]:
    observation: dict[str, Any] = robot.get_observation()
    return {joint: float(observation[joint]) for joint in JOINT_KEYS}


def move_to_action(robot: SO101Follower, target: dict[str, float], steps: int, step_delay: float) -> None:
    """沿用 arm_action_server.py 的 smoothstep 插补方式移动至目标关节姿态。"""
    start = get_pose(robot)
    for index in range(1, steps + 1):
        ratio = index / steps
        ratio = ratio * ratio * ratio * (ratio * (ratio * 6 - 15) + 10)  # smoothstep
        action = {
            joint: start[joint] + (target[joint] - start[joint]) * ratio
            for joint in JOINT_KEYS
        }
        robot.send_action(action)
        time.sleep(step_delay)


def execute_action(robot: SO101Follower, initial: dict[str, float], target: dict[str, float], action_no: int, steps: int, step_delay: float) -> None:
    print("  1/3：移动到初始位置...")
    move_to_action(robot, initial, steps, step_delay)
    print(f"  2/3：移动到目标位置（关键点 {action_no}）...")
    move_to_action(robot, target, steps, step_delay)
    print("  3/3：移动回初始位置...")
    move_to_action(robot, initial, steps, step_delay)
    print("动作完成。\n")


def main() -> None:
    args = parse_args()
    try:
        csv_file = args.csv or select_csv(sample_csv_files(), args.sample_index)
        poses = load_poses(csv_file)
    except KeyboardInterrupt:
        print("已取消，未连接机械臂。")
        return
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(f"错误：{error}") from error

    robot = SO101Follower(
        SO101FollowerConfig(
            port=args.port,
            id=args.robot_id,
            disable_torque_on_disconnect=False,
            use_degrees=True,
        )
    )
    try:
        print(f"使用采集文件：{csv_file}")
        print(f"连接机械臂：{args.port}")
        robot.connect(calibrate=False)
        print("\n可选动作：1-6（对应 key_point_1 至 key_point_6），输入 q 退出。")
        while True:
            command = input("请输入动作编号 [1-6/q]：").strip().lower()
            if command in {"q", "quit", "exit"}:
                break
            if command not in {str(number) for number in range(1, 7)}:
                print("请输入 1 到 6 的动作编号，或输入 q 退出。\n")
                continue

            action_no = int(command)
            execute_action(
                robot,
                poses["initial"],
                poses[f"key_point_{action_no}"],
                action_no,
                args.steps,
                args.step_delay,
            )
    except KeyboardInterrupt:
        print("\n已中断动作。")
    finally:
        if getattr(robot, "is_connected", False):
            robot.disconnect()
        print("机械臂已断开。")


if __name__ == "__main__":
    main()
