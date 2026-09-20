"""成人本地视觉点位试验的纯数据与执行边界。"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from arm_action_library import JOINT_KEYS, atomic_write_json, normalize_pose
except ImportError:
    from .arm_action_library import JOINT_KEYS, atomic_write_json, normalize_pose  # type: ignore


POINT_CODE = "22"
EXPECTED_GRID = {"row": 2, "column": 2}
SEGMENT_DURATION_SECONDS = 3.0
SEGMENT_STEPS = 90
POSE_TOLERANCE_DEGREES = 5.0
EXPECTED_MOTION = {
    "interpolation": "linear_joint_space",
    "segments": [
        {"from": "reset", "to": "point", "duration_seconds": 3.0},
        {"from": "point", "to": "reset", "duration_seconds": 3.0},
    ],
}


class TrialSafetyError(RuntimeError):
    """A point record or a requested physical trial violates its safety contract."""


class TrialExecutionError(RuntimeError):
    """A started trial could not safely finish its currently active segment."""


def load_point_22_record(path: Path) -> dict[str, object]:
    """Load only a complete, inert, adult-recorded point-22 pose record."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrialSafetyError(f"无法读取点位文件：{exc}") from exc
    if not isinstance(raw, dict):
        raise TrialSafetyError("点位文件必须是对象")
    if raw.get("schema_version") != 1:
        raise TrialSafetyError("点位 schema_version 无效")
    if raw.get("kind") != "xingbao_arm_vision_point":
        raise TrialSafetyError("点位 kind 无效")
    if raw.get("point_code") != POINT_CODE or raw.get("grid") != EXPECTED_GRID:
        raise TrialSafetyError("点位 grid 或编号无效")
    if raw.get("motion") != EXPECTED_MOTION:
        raise TrialSafetyError("点位 motion 无效")
    try:
        reset_pose = normalize_pose(raw.get("reset_pose"), "reset_pose")
        target_pose = normalize_pose(raw.get("target_pose"), "target_pose")
    except ValueError as exc:
        raise TrialSafetyError(f"点位姿态无效：{exc}") from exc
    return {
        "schema_version": 1,
        "kind": "xingbao_arm_vision_point",
        "point_code": POINT_CODE,
        "grid": dict(EXPECTED_GRID),
        "reset_pose": reset_pose,
        "target_pose": target_pose,
        "motion": json.loads(json.dumps(EXPECTED_MOTION)),
    }


def pose_errors(actual: Mapping[str, float], expected: Mapping[str, float]) -> dict[str, float]:
    """Return absolute per-joint error in degrees for the fixed SO-101 joint set."""
    return {key: abs(float(actual[key]) - float(expected[key])) for key in JOINT_KEYS}


def within_tolerance(errors: Mapping[str, float], tolerance_degrees: float = POSE_TOLERANCE_DEGREES) -> bool:
    """Return whether every required joint error is within the conservative limit."""
    return all(float(errors[key]) <= float(tolerance_degrees) for key in JOINT_KEYS)


def _service_is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _read_pose(robot: Any, label: str) -> dict[str, float]:
    observation = robot.get_observation()
    return normalize_pose({key: observation[key] for key in JOINT_KEYS}, label)


def default_robot_factory(device: str) -> Any:
    """Construct the already-calibrated follower only when physical execution is requested."""
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    return SO101Follower(
        SO101FollowerConfig(
            port=device,
            id="so101_arm_server",
            disable_torque_on_disconnect=False,
            use_degrees=True,
        )
    )


def move_linear_segment(
    robot: Any,
    target: Mapping[str, float],
    *,
    duration_seconds: float,
    steps: int,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    stop_requested: Callable[[], bool],
) -> dict[str, object]:
    """Send one uniformly timed joint-space segment and return its measured duration."""
    start = _read_pose(robot, "segment_start")
    started_at = clock()
    deadline = started_at + duration_seconds
    for index in range(1, steps + 1):
        if stop_requested():
            raise TrialExecutionError("interrupted")
        if clock() > deadline + 0.5:
            raise TrialExecutionError("duration_exceeded")
        ratio = index / steps
        robot.send_action(
            {
                key: start[key] + (float(target[key]) - start[key]) * ratio
                for key in JOINT_KEYS
            }
        )
        remaining = started_at + index * duration_seconds / steps - clock()
        if remaining > 0:
            sleep(remaining)
    if stop_requested():
        raise TrialExecutionError("interrupted")
    return {
        "completed": True,
        "steps": steps,
        "duration_seconds": clock() - started_at,
    }


def _failed_report(record: Mapping[str, object], error: str) -> dict[str, object]:
    return {
        "status": "executed",
        "point_code": POINT_CODE,
        "passed": False,
        "error": error,
        "record": dict(record),
    }


def write_trial_report(
    report: Mapping[str, object], output_dir: Path, captured_at_utc: str
) -> Path:
    """Atomically persist a physical-trial receipt under a safe UTC filename."""
    timestamp = captured_at_utc.replace(":", "-")
    return atomic_write_json(output_dir / f"{POINT_CODE}-{timestamp}.json", dict(report))


def _adult_confirmation(prompt: str) -> bool:
    """Require the exact adult acknowledgement for each physical action gate."""
    try:
        answer = input(f"{prompt}\n输入 EXECUTE-22 确认：")
    except EOFError:
        return False
    return answer.strip() == "EXECUTE-22"


def _default_point_file() -> Path:
    return Path(__file__).resolve().with_name("action_drafts") / "vision_points" / "22.json"


def _default_report_dir() -> Path:
    return Path(__file__).resolve().with_name("action_drafts") / "vision_points" / "test_reports"


def _print_report(report: Mapping[str, object]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def run_point_22_trial(
    point_path: Path,
    *,
    execute: bool,
    device: str | None = None,
    service_host: str = "127.0.0.1",
    service_port: int = 8764,
    service_is_listening: Callable[[str, int], bool] | None = None,
    confirm: Callable[[str], bool] | None = None,
    robot_factory: Callable[[], object] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, object]:
    """Run one adult-supervised point-22 trial after all explicit safety gates pass."""
    record = load_point_22_record(point_path)
    if not execute:
        return {
            "status": "dry_run",
            "passed": None,
            "point_code": POINT_CODE,
            "record": record,
        }
    listening = service_is_listening or _service_is_listening
    if listening(service_host, service_port):
        raise TrialSafetyError("机械臂动作服务仍在运行")
    if confirm is None or not confirm("确认现场无人且可以连接机械臂？"):
        raise TrialSafetyError("成人未确认连接机械臂")

    selected_device = device or os.getenv("XINGBAO_ARM_DEVICE", "/dev/ttyCH343USB0")
    robot = (robot_factory or (lambda: default_robot_factory(selected_device)))()
    connected = False
    try:
        robot.connect(calibrate=False)
        connected = True
        current_pose = _read_pose(robot, "current_pose")
        reset_pose = record["reset_pose"]
        target_pose = record["target_pose"]
        if not isinstance(reset_pose, dict) or not isinstance(target_pose, dict):
            raise TrialSafetyError("已校验点位姿态缺失")
        start_errors = pose_errors(current_pose, reset_pose)
        if not within_tolerance(start_errors):
            raise TrialSafetyError("当前姿态不在复位安全范围内")
        if confirm is None or not confirm("确认从复位位执行 22 点往返试验？"):
            raise TrialSafetyError("成人未确认发送动作")

        current_clock = clock or time.monotonic
        current_sleep = sleep or time.sleep
        first_segment = move_linear_segment(
            robot,
            target_pose,
            duration_seconds=SEGMENT_DURATION_SECONDS,
            steps=SEGMENT_STEPS,
            clock=current_clock,
            sleep=current_sleep,
            stop_requested=lambda: False,
        )
        target_actual = _read_pose(robot, "target_pose_actual")
        target_errors = pose_errors(target_actual, target_pose)
        second_segment = move_linear_segment(
            robot,
            reset_pose,
            duration_seconds=SEGMENT_DURATION_SECONDS,
            steps=SEGMENT_STEPS,
            clock=current_clock,
            sleep=current_sleep,
            stop_requested=lambda: False,
        )
        reset_actual = _read_pose(robot, "reset_pose_actual")
        reset_errors = pose_errors(reset_actual, reset_pose)
        return {
            "status": "executed",
            "point_code": POINT_CODE,
            "passed": within_tolerance(target_errors) and within_tolerance(reset_errors),
            "start_errors": start_errors,
            "target_errors": target_errors,
            "reset_errors": reset_errors,
            "segments": [first_segment, second_segment],
            "record": record,
        }
    except TrialSafetyError:
        raise
    except KeyboardInterrupt:
        return _failed_report(record, "interrupted")
    except TrialExecutionError as exc:
        return _failed_report(record, str(exc))
    except Exception:
        return _failed_report(record, "send_failed")
    finally:
        if connected:
            robot.disconnect()


def main_for_point_22(argv: list[str] | None = None) -> int:
    """Run the adult-only point-22 checker or guarded physical trial command."""
    parser = argparse.ArgumentParser(
        description="成人本地 22 点机械臂往返试验；默认只校验 JSON，不连接机械臂。"
    )
    parser.add_argument("--execute", action="store_true", help="经双重确认后执行一次实体试验")
    parser.add_argument("--device", help="机械臂串口；默认读取 XINGBAO_ARM_DEVICE 或标准端口")
    parser.add_argument("--point-file", type=Path, default=_default_point_file())
    parser.add_argument("--service-host", default="127.0.0.1")
    parser.add_argument("--service-port", type=int, default=8764)
    args = parser.parse_args(argv)

    try:
        report = run_point_22_trial(
            args.point_file,
            execute=args.execute,
            device=args.device,
            service_host=args.service_host,
            service_port=args.service_port,
            confirm=_adult_confirmation if args.execute else None,
        )
    except TrialSafetyError as exc:
        refusal: dict[str, object] = {
            "status": "refused",
            "point_code": POINT_CODE,
            "passed": False,
            "error": str(exc),
            "point_file": str(args.point_file),
        }
        if args.execute:
            captured_at_utc = datetime.now(timezone.utc).isoformat()
            refusal["captured_at_utc"] = captured_at_utc
            refusal["report_file"] = str(
                write_trial_report(refusal, _default_report_dir(), captured_at_utc)
            )
        _print_report(refusal)
        return 2

    report["point_file"] = str(args.point_file)
    if args.execute:
        captured_at_utc = datetime.now(timezone.utc).isoformat()
        report["captured_at_utc"] = captured_at_utc
        report["report_file"] = str(
            write_trial_report(report, _default_report_dir(), captured_at_utc)
        )
    _print_report(report)
    return 0 if report["passed"] in (True, None) else 1
