"""受审核的星宝机械臂表意动作库。

这个模块只处理本地、人工录制后审核过的姿态数据。网络侧始终只能发送
``nod``、``shake_head``、``bow`` 等高层动作名，不能传入关节角度、轨迹或
内部动作组名称。
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)
VISION_HIGH_FIVE_ACTION_NAMES = frozenset(
    {
        "vision_high_five_11",
        "vision_high_five_12",
        "vision_high_five_13",
        "vision_high_five_21",
        "vision_high_five_22",
        "vision_high_five_23",
    }
)
ALLOWED_ACTION_NAMES = frozenset({"nod", "shake_head", "bow", "mouth", "high_five"}) | VISION_HIGH_FIVE_ACTION_NAMES
ACTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().with_name("action_registry.json")
BUNDLE_KIND = "xingbao_basic_expression_bundle"
BASIC_EXPRESSION_SLOTS = (
    "reset",
    "shake_left",
    "shake_right",
    "nod_up",
    "nod_down",
    "bow_up",
    "bow_down",
    "mouth_open",
    "mouth_close",
    "handshake",
)
BASIC_EXPRESSION_ACTION_NAMES = frozenset({"nod", "shake_head", "bow", "mouth", "high_five"})


class ActionValidationError(ValueError):
    """录制草稿或动作库不满足安全边界。"""


def _pose(**values: float) -> dict[str, float]:
    return {key: float(values[key]) for key in JOINT_KEYS}


DEFAULT_NEUTRAL_POSE = _pose(
    **{
        "shoulder_pan.pos": -2.10989010989011,
        "shoulder_lift.pos": -46.989010989010985,
        "elbow_flex.pos": -12.043956043956044,
        "wrist_flex.pos": -16.88,
        "wrist_roll.pos": 80.3076923076923,
        "gripper.pos": 3.64963503649635,
    }
)

DEFAULT_SAFETY = {
    "max_duration_seconds": 1.0,
    "cooldown_seconds": 1.5,
    "min_steps": 3,
    "max_steps": 10,
    "min_delay_seconds": 0.01,
    "max_delay_seconds": 0.08,
    "max_pose_count": 3,
    "max_sequence_length": 5,
    "neutral_tolerance_degrees": 5.0,
    "min_expression_delta_degrees": 1.0,
    "min_pose_separation_degrees": 2.0,
    # 相对于复位姿态的保守限制；录制超出范围只能保留在草稿中，不能启用。
    "max_delta_degrees": {
        "shoulder_pan.pos": 55.0,
        "shoulder_lift.pos": 30.0,
        "elbow_flex.pos": 35.0,
        "wrist_flex.pos": 70.0,
        "wrist_roll.pos": 45.0,
        "gripper.pos": 35.0,
    },
}

# 所有表意动作都以固定的 2.5 倍慢速执行；这是服务端常量，草稿 JSON 和
# 网络请求均不能放宽。慢速只作用于运动插值，击掌的停留仍固定为 4 秒。
MOTION_SLOWDOWN_FACTOR = 2.5
NOD_CORE_JOINT = "wrist_flex.pos"
BOW_AMPLITUDE_SCALE = 0.5
SIMPLE_EXPRESSION_SAFETY_OVERRIDE = {
    # 高频小步不会扩大动作幅度，只减少低频阶梯感。摇头最长约 3.2 秒，
    # 仍由这个硬件服务端上限约束，调用方无法延长。
    "max_duration_seconds": 3.5,
    "max_steps": 24,
}

# The wider side-to-side sweep benefits from extra interpolation and a lower
# angular velocity. This exception is local to the approved shake action;
# callers still cannot provide movement timings or joint coordinates.
SHAKE_HEAD_SAFETY_OVERRIDE = {
    "max_duration_seconds": 5.2,
    "max_steps": 24,
}

# 只有已人工录制、单独审核的击掌允许更大的伸手幅度、停留时间和慢速回位。
# The recorded legacy handshake pose is now the child-facing high-five pose.
# The pose itself remains local and reviewed; callers only ever request the
# high-level ``high_five`` action.
HIGH_FIVE_SAFETY_OVERRIDE = {
    "max_duration_seconds": 9.0,
    "max_hold_seconds": 4.0,
    "cooldown_seconds": 6.0,
    # 仅击掌允许更多插值点，以 30Hz 左右的频率平滑匀速运动；外部草稿
    # 和网络请求都不能修改此上限。
    "max_steps": 60,
    "max_delay_seconds": 0.20,
    "max_delta_degrees": {
        "shoulder_pan.pos": 55.0,
        "shoulder_lift.pos": 55.0,
        "elbow_flex.pos": 35.0,
        "wrist_flex.pos": 70.0,
        "wrist_roll.pos": 45.0,
        "gripper.pos": 60.0,
    },
}

# Six manually recorded table-grid poses used only by the local hand-vision
# runtime.  The values are never accepted from the network or an LLM.
VISION_HIGH_FIVE_TARGETS = {
    "vision_high_five_11": {
        "shoulder_pan.pos": -18.197802197802197,
        "shoulder_lift.pos": -5.142857142857143,
        "elbow_flex.pos": 24.835164835164836,
        "wrist_flex.pos": -138.72527472527472,
        "wrist_roll.pos": 78.9010989010989,
        "gripper.pos": 78.714859437751,
    },
    "vision_high_five_12": {
        "shoulder_pan.pos": 2.7252747252747254,
        "shoulder_lift.pos": -3.208791208791209,
        "elbow_flex.pos": 24.835164835164836,
        "wrist_flex.pos": -139.25274725274724,
        "wrist_roll.pos": 78.9010989010989,
        "gripper.pos": 78.6479250334672,
    },
    "vision_high_five_13": {
        "shoulder_pan.pos": 23.560439560439562,
        "shoulder_lift.pos": -3.3846153846153846,
        "elbow_flex.pos": 23.86813186813187,
        "wrist_flex.pos": -139.34065934065933,
        "wrist_roll.pos": 78.81318681318682,
        "gripper.pos": 78.6479250334672,
    },
    "vision_high_five_21": {
        "shoulder_pan.pos": -22.24175824175824,
        "shoulder_lift.pos": 24.65934065934066,
        "elbow_flex.pos": 14.373626373626374,
        "wrist_flex.pos": -141.53846153846155,
        "wrist_roll.pos": 78.9010989010989,
        "gripper.pos": 69.14323962516734,
    },
    "vision_high_five_22": {
        "shoulder_pan.pos": -1.934065934065934,
        "shoulder_lift.pos": 12.43956043956044,
        "elbow_flex.pos": 31.78021978021978,
        "wrist_flex.pos": -142.15384615384616,
        "wrist_roll.pos": 78.81318681318682,
        "gripper.pos": 68.20615796519411,
    },
    "vision_high_five_23": {
        "shoulder_pan.pos": 23.208791208791208,
        "shoulder_lift.pos": 31.252747252747252,
        "elbow_flex.pos": 6.1098901098901095,
        "wrist_flex.pos": -142.06593406593407,
        "wrist_roll.pos": 78.9010989010989,
        "gripper.pos": 68.20615796519411,
    },
}
VISION_HIGH_FIVE_SAFETY_OVERRIDE = {
# Six-point motion remains bounded by the same approved poses and a twelve
# second watchdog.  The point-to-point legs below use a slightly shorter
# smoothstep profile so a child's deliberate grid change visibly redirects
# without a long linear-motion lag.
    "max_duration_seconds": 12.0,
    "max_hold_seconds": 3.5,
    "cooldown_seconds": 1.0,
    "max_steps": 90,
    "max_delay_seconds": 0.05,
    "max_delta_degrees": {
        "shoulder_pan.pos": 30.0,
        "shoulder_lift.pos": 80.0,
        "elbow_flex.pos": 45.0,
        "wrist_flex.pos": 130.0,
        "wrist_roll.pos": 45.0,
        "gripper.pos": 80.0,
    },
}

# A follow session remains entirely inside the reviewed arm service.  Vision
# can name one of the six positions, but can never supply a joint value,
# velocity, or arbitrary trajectory.  The bounds below cap how long an arm
# stays in this special interaction state even if the camera keeps reporting
# changing hands.
VISION_HIGH_FIVE_FOLLOW_IDLE_SECONDS = 3.5
VISION_HIGH_FIVE_FOLLOW_MAX_REDIRECTS = 16
VISION_HIGH_FIVE_FOLLOW_MAX_DURATION_SECONDS = 24.0

BOW_SAFETY_OVERRIDE = {
    "max_delta_degrees": {
        "shoulder_pan.pos": 55.0,
        "shoulder_lift.pos": 30.0,
        "elbow_flex.pos": 52.0,
        "wrist_flex.pos": 70.0,
        "wrist_roll.pos": 45.0,
        "gripper.pos": 35.0,
    },
}


def default_registry() -> dict[str, Any]:
    """返回当前已实际验证过的短点头动作，供缺省配置和单元测试使用。"""
    neutral = deepcopy(DEFAULT_NEUTRAL_POSE)
    up = deepcopy(neutral)
    up["shoulder_lift.pos"] = -47.07692307692308
    up["wrist_flex.pos"] = 29.67032967032967
    down = deepcopy(neutral)
    down["shoulder_pan.pos"] = -2.2153846153846155
    down["elbow_flex.pos"] = -11.99120879120879
    down["wrist_flex.pos"] = 49.39745054945055
    down["wrist_roll.pos"] = 80.4131868131868
    return {
        "schema_version": SCHEMA_VERSION,
        "neutral_pose": neutral,
        "safety": deepcopy(DEFAULT_SAFETY),
        "actions": {
            "nod": {
                "status": "approved",
                "description": "已验证的轻柔点头",
                "poses": [neutral, up, down],
                "sequence": [1, 2, 0],
                "steps": 8,
                "delay_seconds": 0.02,
                "smoothstep": True,
            }
        },
    }


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActionValidationError(f"{label} 必须是对象")
    return dict(value)


def normalize_pose(value: object, label: str = "pose") -> dict[str, float]:
    raw = _require_mapping(value, label)
    keys = set(raw)
    expected = set(JOINT_KEYS)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ActionValidationError(f"{label} 关节字段不匹配，缺少={missing}，多余={extra}")
    result: dict[str, float] = {}
    for key in JOINT_KEYS:
        try:
            number = float(raw[key])
        except (TypeError, ValueError) as exc:
            raise ActionValidationError(f"{label}.{key} 不是数值") from exc
        if not math.isfinite(number):
            raise ActionValidationError(f"{label}.{key} 不是有限数值")
        result[key] = number
    return result


def _number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ActionValidationError(f"{label} 不是数值") from exc
    if not math.isfinite(number):
        raise ActionValidationError(f"{label} 不是有限数值")
    return number


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ActionValidationError(f"{label} 必须是整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ActionValidationError(f"{label} 必须是整数") from exc
    if result != value:
        raise ActionValidationError(f"{label} 必须是整数")
    return result


def _merge_safety(raw_safety: object) -> dict[str, Any]:
    raw = _require_mapping(raw_safety, "safety")
    safety = deepcopy(DEFAULT_SAFETY)
    safety.update({key: value for key, value in raw.items() if key != "max_delta_degrees"})
    limits = _require_mapping(raw.get("max_delta_degrees", safety["max_delta_degrees"]), "safety.max_delta_degrees")
    if set(limits) != set(JOINT_KEYS):
        raise ActionValidationError("safety.max_delta_degrees 必须覆盖全部关节")
    safety["max_delta_degrees"] = {
        key: _number(limits[key], f"safety.max_delta_degrees.{key}")
        for key in JOINT_KEYS
    }
    for key in (
        "max_duration_seconds",
        "cooldown_seconds",
        "min_delay_seconds",
        "max_delay_seconds",
        "neutral_tolerance_degrees",
        "min_expression_delta_degrees",
        "min_pose_separation_degrees",
    ):
        safety[key] = _number(safety[key], f"safety.{key}")
    for key in ("min_steps", "max_steps", "max_pose_count", "max_sequence_length"):
        safety[key] = _integer(safety[key], f"safety.{key}")
    if safety["max_duration_seconds"] <= 0 or safety["max_duration_seconds"] > 1.0:
        raise ActionValidationError("safety.max_duration_seconds 必须在 (0, 1] 内")
    if safety["cooldown_seconds"] < 0:
        raise ActionValidationError("safety.cooldown_seconds 不能为负数")
    if safety["min_steps"] < 1 or safety["min_steps"] > safety["max_steps"]:
        raise ActionValidationError("safety 的 steps 范围无效")
    if safety["min_delay_seconds"] <= 0 or safety["min_delay_seconds"] > safety["max_delay_seconds"]:
        raise ActionValidationError("safety 的 delay 范围无效")
    if safety["max_pose_count"] < 2 or safety["max_sequence_length"] < 2:
        raise ActionValidationError("safety 的姿态或序列上限过小")
    if safety["neutral_tolerance_degrees"] <= 0:
        raise ActionValidationError("safety.neutral_tolerance_degrees 必须大于 0")
    if safety["min_expression_delta_degrees"] <= 0 or safety["min_pose_separation_degrees"] <= 0:
        raise ActionValidationError("safety 的最小表意姿态阈值必须大于 0")
    if any(limit <= 0 for limit in safety["max_delta_degrees"].values()):
        raise ActionValidationError("每个关节的安全位移必须大于 0")
    return safety


def _pose_matches_neutral(pose: dict[str, float], neutral: dict[str, float], tolerance: float) -> bool:
    return all(abs(pose[key] - neutral[key]) <= tolerance for key in JOINT_KEYS)


def _action_safety(name: str, safety: dict[str, Any]) -> dict[str, Any]:
    """返回动作专属的不可由外部草稿放宽的安全边界。"""
    result = {
        "max_duration_seconds": safety["max_duration_seconds"],
        "max_hold_seconds": 0.0,
        "max_steps": safety["max_steps"],
        "max_delay_seconds": safety["max_delay_seconds"],
        "cooldown_seconds": safety["cooldown_seconds"],
        "max_delta_degrees": dict(safety["max_delta_degrees"]),
    }
    if name in {"nod", "mouth", "bow"}:
        result.update(SIMPLE_EXPRESSION_SAFETY_OVERRIDE)
    elif name == "shake_head":
        result.update(SHAKE_HEAD_SAFETY_OVERRIDE)
    if name == "high_five":
        result.update(HIGH_FIVE_SAFETY_OVERRIDE)
        result["max_delta_degrees"] = dict(HIGH_FIVE_SAFETY_OVERRIDE["max_delta_degrees"])
    elif name in VISION_HIGH_FIVE_ACTION_NAMES:
        result.update(VISION_HIGH_FIVE_SAFETY_OVERRIDE)
        result["max_delta_degrees"] = dict(VISION_HIGH_FIVE_SAFETY_OVERRIDE["max_delta_degrees"])
    elif name == "bow":
        result["max_delta_degrees"] = dict(BOW_SAFETY_OVERRIDE["max_delta_degrees"])
    return result


def _validate_action(
    name: str,
    raw_action: object,
    neutral: dict[str, float],
    safety: dict[str, Any],
) -> dict[str, Any]:
    if not ACTION_NAME_RE.fullmatch(name) or name not in ALLOWED_ACTION_NAMES:
        raise ActionValidationError(f"不允许的高层动作名: {name}")
    raw = _require_mapping(raw_action, f"actions.{name}")
    if raw.get("status") != "approved":
        raise ActionValidationError(f"actions.{name} 未处于 approved 状态")
    action_safety = _action_safety(name, safety)
    poses_value = raw.get("poses")
    if not isinstance(poses_value, list) or not (2 <= len(poses_value) <= safety["max_pose_count"]):
        raise ActionValidationError(f"actions.{name}.poses 数量不在安全范围内")
    poses = [normalize_pose(pose, f"actions.{name}.poses[{index}]") for index, pose in enumerate(poses_value)]
    if not _pose_matches_neutral(poses[0], neutral, tolerance=0.01):
        raise ActionValidationError(f"actions.{name}.poses[0] 必须是复位姿态")
    for pose_index, pose in enumerate(poses[1:], start=1):
        max_delta = 0.0
        for key in JOINT_KEYS:
            delta = abs(pose[key] - neutral[key])
            max_delta = max(max_delta, delta)
            if delta > action_safety["max_delta_degrees"][key]:
                raise ActionValidationError(
                    f"actions.{name}.poses[{pose_index}].{key} 超出复位姿态的安全位移 "
                    f"({delta:.2f} > {action_safety['max_delta_degrees'][key]:.2f})"
                )
        if max_delta < safety["min_expression_delta_degrees"]:
            raise ActionValidationError(f"actions.{name}.poses[{pose_index}] 与复位姿态过于接近")
    for left_index in range(1, len(poses)):
        for right_index in range(left_index + 1, len(poses)):
            separation = max(abs(poses[left_index][key] - poses[right_index][key]) for key in JOINT_KEYS)
            if separation < safety["min_pose_separation_degrees"]:
                raise ActionValidationError(f"actions.{name} 的两个表意姿态过于接近")
    sequence_value = raw.get("sequence")
    if not isinstance(sequence_value, list) or not (2 <= len(sequence_value) <= safety["max_sequence_length"]):
        raise ActionValidationError(f"actions.{name}.sequence 长度不在安全范围内")
    sequence = [_integer(item, f"actions.{name}.sequence") for item in sequence_value]
    if sequence[-1] != 0:
        raise ActionValidationError(f"actions.{name}.sequence 必须以复位姿态 0 结束")
    if any(index < 0 or index >= len(poses) for index in sequence):
        raise ActionValidationError(f"actions.{name}.sequence 含有不存在的姿态索引")
    if not any(index != 0 for index in sequence):
        raise ActionValidationError(f"actions.{name}.sequence 没有表意姿态")
    steps = _integer(raw.get("steps"), f"actions.{name}.steps")
    delay_seconds = _number(raw.get("delay_seconds"), f"actions.{name}.delay_seconds")
    if not safety["min_steps"] <= steps <= action_safety["max_steps"]:
        raise ActionValidationError(f"actions.{name}.steps 超出安全范围")
    if not safety["min_delay_seconds"] <= delay_seconds <= action_safety["max_delay_seconds"]:
        raise ActionValidationError(f"actions.{name}.delay_seconds 超出安全范围")
    estimated_duration = len(sequence) * steps * delay_seconds
    if estimated_duration > action_safety["max_duration_seconds"]:
        raise ActionValidationError(
            f"actions.{name} 估算时长 {estimated_duration:.3f}s 超过 "
            f"{action_safety['max_duration_seconds']:.3f}s"
        )
    if not isinstance(raw.get("smoothstep"), bool):
        raise ActionValidationError(f"actions.{name}.smoothstep 必须是布尔值")
    raw_segments = raw.get("segment_profiles")
    if raw_segments is None:
        segment_profiles = [
            {
                "steps": steps,
                "delay_seconds": delay_seconds,
                "smoothstep": bool(raw["smoothstep"]),
                "hold_after_seconds": 0.0,
            }
            for _ in sequence
        ]
    else:
        if not isinstance(raw_segments, list) or len(raw_segments) != len(sequence):
            raise ActionValidationError(f"actions.{name}.segment_profiles 必须与 sequence 等长")
        segment_profiles = []
        for index, raw_segment in enumerate(raw_segments):
            segment = _require_mapping(raw_segment, f"actions.{name}.segment_profiles[{index}]")
            segment_steps = _integer(segment.get("steps"), f"actions.{name}.segment_profiles[{index}].steps")
            segment_delay = _number(
                segment.get("delay_seconds"),
                f"actions.{name}.segment_profiles[{index}].delay_seconds",
            )
            if not safety["min_steps"] <= segment_steps <= action_safety["max_steps"]:
                raise ActionValidationError(f"actions.{name}.segment_profiles[{index}].steps 超出安全范围")
            if not safety["min_delay_seconds"] <= segment_delay <= action_safety["max_delay_seconds"]:
                raise ActionValidationError(f"actions.{name}.segment_profiles[{index}].delay_seconds 超出安全范围")
            smoothstep = segment.get("smoothstep", raw["smoothstep"])
            if not isinstance(smoothstep, bool):
                raise ActionValidationError(f"actions.{name}.segment_profiles[{index}].smoothstep 必须是布尔值")
            hold_after_seconds = _number(
                segment.get("hold_after_seconds", 0.0),
                f"actions.{name}.segment_profiles[{index}].hold_after_seconds",
            )
            if hold_after_seconds < 0 or hold_after_seconds > action_safety["max_hold_seconds"]:
                raise ActionValidationError(f"actions.{name}.segment_profiles[{index}].hold_after_seconds 超出安全范围")
            segment_profiles.append(
                {
                    "steps": segment_steps,
                    "delay_seconds": segment_delay,
                    "smoothstep": smoothstep,
                    "hold_after_seconds": hold_after_seconds,
                }
            )
    estimated_duration = sum(
        profile["steps"] * profile["delay_seconds"] + profile["hold_after_seconds"]
        for profile in segment_profiles
    )
    if estimated_duration > action_safety["max_duration_seconds"]:
        raise ActionValidationError(
            f"actions.{name} 估算时长 {estimated_duration:.3f}s 超过 "
            f"{action_safety['max_duration_seconds']:.3f}s"
        )
    description = str(raw.get("description", "")).strip()
    return {
        "status": "approved",
        "description": description,
        "poses": poses,
        "sequence": sequence,
        "steps": steps,
        "delay_seconds": delay_seconds,
        "smoothstep": bool(raw["smoothstep"]),
        "segment_profiles": segment_profiles,
        "estimated_duration_seconds": estimated_duration,
        "max_duration_seconds": action_safety["max_duration_seconds"],
        "cooldown_seconds": action_safety["cooldown_seconds"],
    }


def validate_registry(value: object) -> dict[str, Any]:
    raw = _require_mapping(value, "registry")
    if _integer(raw.get("schema_version"), "schema_version") != SCHEMA_VERSION:
        raise ActionValidationError("不支持的动作库 schema_version")
    neutral = normalize_pose(raw.get("neutral_pose"), "neutral_pose")
    safety = _merge_safety(raw.get("safety", {}))
    raw_actions = _require_mapping(raw.get("actions"), "actions")
    if not raw_actions:
        raise ActionValidationError("动作库至少需要一个已审核动作")
    actions: dict[str, dict[str, Any]] = {}
    for name, action in raw_actions.items():
        if not isinstance(name, str):
            raise ActionValidationError("动作名必须是字符串")
        actions[name] = _validate_action(name, action, neutral, safety)
    return {
        "schema_version": SCHEMA_VERSION,
        "neutral_pose": neutral,
        "safety": safety,
        "actions": actions,
    }


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ActionValidationError(f"动作库不存在: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ActionValidationError(f"动作库 JSON 无法解析: {target}: {exc}") from exc
    if not isinstance(raw, dict):
        return validate_registry(raw)
    actions = raw.get("actions")
    if not isinstance(actions, dict):
        return validate_registry(raw)
    # A release assembled before this hotfix may still carry the legacy key.
    # Migrate only in memory so the runtime never exposes ``handshake`` again.
    if "high_five" not in actions and isinstance(actions.get("handshake"), dict):
        actions["high_five"] = dict(actions.pop("handshake"))
        actions["high_five"]["description"] = "击掌：复位、击掌、慢速复位"
    neutral = raw.get("neutral_pose")
    if isinstance(neutral, dict):
        for action_name, target in VISION_HIGH_FIVE_TARGETS.items():
            actions.setdefault(
                action_name,
                {
                    "status": "approved",
                    "description": f"视觉击掌点位 {action_name[-2:]}",
                    "poses": [dict(neutral), dict(target)],
                    "sequence": [0, 1, 0],
                    "steps": 90,
                    "delay_seconds": 0.04,
                    "smoothstep": False,
                    "segment_profiles": [
                        {"steps": 3, "delay_seconds": 0.04, "smoothstep": True, "hold_after_seconds": 0.0},
                        {"steps": 64, "delay_seconds": 0.03, "smoothstep": True, "hold_after_seconds": 3.5},
                        {"steps": 64, "delay_seconds": 0.03, "smoothstep": True, "hold_after_seconds": 0.0},
                    ],
                },
            )
    return validate_registry(raw)


def compile_registry(registry: object) -> dict[str, Any]:
    """将本地动作库转换为旧 SO-101 驱动私有的数字姿态和动作组。"""
    checked = validate_registry(registry)
    runtime_poses: dict[int, dict[str, float]] = {}
    runtime_groups: dict[str, dict[str, Any]] = {}
    action_to_group: dict[str, str] = {}
    action_cooldowns: dict[str, float] = {}
    action_segments: dict[str, list[dict[str, Any]]] = {}
    action_max_durations: dict[str, float] = {}
    pose_id = 0
    for action_name, action in checked["actions"].items():
        local_to_runtime: dict[int, int] = {}
        for index, pose in enumerate(action["poses"]):
            local_to_runtime[index] = pose_id
            runtime_poses[pose_id] = dict(pose)
            pose_id += 1
        group_name = f"xingbao_{action_name}"
        runtime_groups[group_name] = {
            "steps": action["steps"],
            "delay": action["delay_seconds"],
            "sequence": [local_to_runtime[index] for index in action["sequence"]],
            "smoothstep": action["smoothstep"],
        }
        action_to_group[action_name] = group_name
        action_cooldowns[action_name] = action["cooldown_seconds"]
        action_segments[action_name] = [dict(profile) for profile in action["segment_profiles"]]
        action_max_durations[action_name] = action["max_duration_seconds"]
    return {
        "registry": checked,
        "poses": runtime_poses,
        "groups": runtime_groups,
        "action_to_group": action_to_group,
        "action_cooldowns": action_cooldowns,
        "action_segments": action_segments,
        "action_max_durations": action_max_durations,
    }


def build_basic_expression_bundle(captured_poses: object) -> dict[str, Any]:
    """把十个手工采集姿态整理为尚未启用的表意动作草稿。

    摇头和点头固定为两个来回，弯腰为下、上、复位。所有草稿都必须经过
    :func:`registry_from_basic_expression_bundle` 的安全校验后才能写入动作库。
    """
    raw = _require_mapping(captured_poses, "captured_poses")
    if set(raw) != set(BASIC_EXPRESSION_SLOTS):
        raise ActionValidationError("采集姿态必须且只能包含九个固定槽位")
    poses = {slot: normalize_pose(raw[slot], f"captured_poses.{slot}") for slot in BASIC_EXPRESSION_SLOTS}
    reset = poses["reset"]

    def expression_action(description: str, labels: list[str]) -> dict[str, Any]:
        action_poses = [reset] + [poses[label] for label in labels if label != "reset"]
        return {
            "status": "draft",
            "description": description,
            "poses": action_poses,
            "steps": 8,
            "delay_seconds": 0.02 * MOTION_SLOWDOWN_FACTOR,
            "smoothstep": True,
        }

    def scaled_pose_from_reset(label: str, scale: float) -> dict[str, float]:
        """Reduce a recorded pose's displacement without changing its direction."""
        captured = poses[label]
        return {
            key: reset[key] + (captured[key] - reset[key]) * scale
            for key in JOINT_KEYS
        }

    shake = expression_action("摇头：左、右各两次，再复位", ["shake_left", "shake_right"])
    shake["sequence"] = [1, 2, 1, 2, 0]
    # 原先每段仅 8 个插值点、约 0.4 秒，肩关节转向时既显得急又有阶梯感。
    # 改为 25Hz 的 16 个小步和缓入缓出；幅度不变，总时长约 3.2 秒。
    shake["segment_profiles"] = [
        {"steps": 22, "delay_seconds": 0.041, "smoothstep": True, "hold_after_seconds": 0.0},
        {"steps": 22, "delay_seconds": 0.04, "smoothstep": True, "hold_after_seconds": 0.0},
        {"steps": 22, "delay_seconds": 0.04, "smoothstep": True, "hold_after_seconds": 0.0},
        {"steps": 22, "delay_seconds": 0.04, "smoothstep": True, "hold_after_seconds": 0.0},
        # 最后一段回中立位略放慢，且显式进入服务端的分段执行路径。
        {"steps": 22, "delay_seconds": 0.04, "smoothstep": True, "hold_after_seconds": 0.0},
    ]
    nod = expression_action("点头：上、下各两次，再复位", ["nod_up", "nod_down"])
    # 点头只使用腕部俯仰这一颗表达核心舵机；录制过程中的其他关节微小变化
    # 不会混入动作，避免整个手臂跟随点头。
    nod_up = deepcopy(reset)
    nod_up[NOD_CORE_JOINT] = poses["nod_up"][NOD_CORE_JOINT]
    nod_down = deepcopy(reset)
    nod_down[NOD_CORE_JOINT] = poses["nod_down"][NOD_CORE_JOINT]
    nod["poses"] = [reset, nod_up, nod_down]
    nod["sequence"] = [1, 2, 1, 2, 0]
    bow = expression_action("弯腰：下、上、复位", ["bow_down", "bow_up"])
    # 弯腰保留录入方向，但统一缩小相对复位的幅度，减少前探和肘部摆幅。
    bow["poses"] = [
        reset,
        scaled_pose_from_reset("bow_down", BOW_AMPLITUDE_SCALE),
        scaled_pose_from_reset("bow_up", BOW_AMPLITUDE_SCALE),
    ]
    bow["sequence"] = [1, 2, 0]
    # 弯腰保留 50% 幅度。三段改为约 30Hz 的高频小步并保持缓入缓出，
    # 总时长约 2.4 秒，消除 10 个大步造成的卡顿感。
    bow["segment_profiles"] = [
        {"steps": 24, "delay_seconds": 1.0 / 30.0, "smoothstep": True, "hold_after_seconds": 0.0},
        {"steps": 24, "delay_seconds": 1.0 / 30.0, "smoothstep": True, "hold_after_seconds": 0.0},
        # 回到复位位时多留极小的缓冲，避免被服务误判为通用低频动作。
        {"steps": 24, "delay_seconds": 0.034, "smoothstep": True, "hold_after_seconds": 0.0},
    ]
    # “嘴巴”只使用录制到的夹爪开合值，保持其余关节复位，避免采集时带入
    # 上一个动作残留的手臂姿态。
    mouth_open = deepcopy(reset)
    mouth_open["gripper.pos"] = poses["mouth_open"]["gripper.pos"]
    mouth_close = deepcopy(reset)
    mouth_close["gripper.pos"] = poses["mouth_close"]["gripper.pos"]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": BUNDLE_KIND,
        "status": "draft",
        "neutral_pose": reset,
        "captured_poses": poses,
        "actions": {
            "shake_head": shake,
            "nod": nod,
            "bow": bow,
            "mouth": {
                "status": "draft",
                "description": "嘴巴：张嘴、闭嘴各两次，再复位",
                "poses": [reset, mouth_open, mouth_close],
                "sequence": [1, 2, 1, 2, 0],
                "steps": 8,
                "delay_seconds": 0.02 * MOTION_SLOWDOWN_FACTOR,
                "smoothstep": True,
            },
            "high_five": {
                "status": "draft",
                "description": "击掌：复位、击掌、很慢复位",
                "poses": [reset, poses["handshake"]],
                "sequence": [0, 1, 0],
                "steps": 5,
                "delay_seconds": 0.02,
                "smoothstep": True,
                # 先完成一次短复位确认；随后以约 30Hz 的高频小步匀速伸手 2 秒、
                # 停住 4 秒，再以相同频率匀速收回 2 秒。这样不会出现低频阶梯感。
                "segment_profiles": [
                    {"steps": 3, "delay_seconds": 0.01 * MOTION_SLOWDOWN_FACTOR, "smoothstep": True, "hold_after_seconds": 0.0},
                    {"steps": 60, "delay_seconds": 1.0 / 30.0, "smoothstep": False, "hold_after_seconds": 4.0},
                    {"steps": 60, "delay_seconds": 1.0 / 30.0, "smoothstep": False, "hold_after_seconds": 0.0},
                ],
            },
        },
    }


def registry_from_basic_expression_bundle(bundle: object, base_registry: object) -> dict[str, Any]:
    """审核草稿并生成可由机械臂服务加载的动作库候选。

    不会写文件，也不会控制机械臂；调用方必须显式确认后才可原子替换动作库。
    """
    raw_bundle = _require_mapping(bundle, "bundle")
    if _integer(raw_bundle.get("schema_version"), "bundle.schema_version") != SCHEMA_VERSION:
        raise ActionValidationError("草稿 schema_version 不受支持")
    if raw_bundle.get("kind") != BUNDLE_KIND:
        raise ActionValidationError("不是基础表意动作录制草稿")
    base = validate_registry(base_registry)
    captured = _require_mapping(raw_bundle.get("captured_poses"), "bundle.captured_poses")
    if set(captured) != set(BASIC_EXPRESSION_SLOTS):
        raise ActionValidationError("草稿必须包含九个固定采集姿态")
    for slot in BASIC_EXPRESSION_SLOTS:
        normalize_pose(captured[slot], f"bundle.captured_poses.{slot}")
    captured_neutral = normalize_pose(raw_bundle.get("neutral_pose"), "bundle.neutral_pose")
    tolerance = base["safety"]["neutral_tolerance_degrees"]
    if not _pose_matches_neutral(captured_neutral, base["neutral_pose"], tolerance):
        raise ActionValidationError(
            "录制时的复位姿态与当前已审核复位姿态相差过大；请先把机械臂摆回复位姿态后重新录制"
        )
    raw_actions = _require_mapping(raw_bundle.get("actions"), "bundle.actions")
    if set(raw_actions) != BASIC_EXPRESSION_ACTION_NAMES:
        raise ActionValidationError("草稿必须同时包含 nod、shake_head、bow、mouth、high_five 五个动作")
    candidate = deepcopy(base)
    # 本轮录制的 reset 已在旧复位位 5° 容差内通过审核。把它设为候选库的
    # 唯一复位基准，确保所有动作的序列 0 精确回到这次实际记录的中立位。
    candidate["neutral_pose"] = captured_neutral
    candidate_actions: dict[str, Any] = {}
    for name in sorted(ALLOWED_ACTION_NAMES):
        action = _require_mapping(raw_actions[name], f"bundle.actions.{name}")
        action["status"] = "approved"
        candidate_actions[name] = action
    candidate["actions"] = candidate_actions
    return validate_registry(candidate)


def atomic_write_json(path: Path | str, value: object) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return target
