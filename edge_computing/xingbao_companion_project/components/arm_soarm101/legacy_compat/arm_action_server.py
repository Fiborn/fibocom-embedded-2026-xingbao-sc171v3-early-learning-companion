#!/usr/bin/env python
"""机械臂动作服务器 — 接收 TCP NDJSON 消息并执行对应动作组.

高层动作映射:
  nod / encourage       -> group_1 (1->2->1->2->1->2->0, smoothstep)
  shake_head / wave     -> group_2 (3->4->3->4->3->4->0, smoothstep)

协议: TCP 127.0.0.1:8764, UTF-8 NDJSON
接收示例: {"arm_action":"nod"}

外部请求不得直接使用 group_1/group_2 或任何舵机角度。
"""

# The board runtime uses Python 3.8.  Postpone annotations so the modern
# built-in generic annotations below (for example ``dict[int, ...]``) do not
# get evaluated at import time.
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time


# ═══════════════════════════════════════════════════════════════
# 机器人配置
# ═══════════════════════════════════════════════════════════════

ROBOT_PORT = os.environ.get("XINGBAO_ARM_DEVICE", "/dev/ttyCH343USB0")

JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)

# ═══════════════════════════════════════════════════════════════
# 关节姿态（写死，来自 so101_samples.csv）
# ═══════════════════════════════════════════════════════════════

JOINT_POSES: dict[int, dict[str, float]] = {
    0: {
        "shoulder_pan.pos": -2.10989010989011,
        "shoulder_lift.pos": -46.989010989010985,
        "elbow_flex.pos": -12.043956043956044,
        "wrist_flex.pos": -16.88,
        "wrist_roll.pos": 80.3076923076923,
        "gripper.pos": 3.64963503649635,
    },
    1: {
        "shoulder_pan.pos": -2.10989010989011,
        "shoulder_lift.pos": -47.07692307692308,
        "elbow_flex.pos": -12.043956043956044,
        "wrist_flex.pos": 29.67032967032967,
        "wrist_roll.pos": 80.48351648351648,
        "gripper.pos": 3.64963503649635,
    },
    # Keep pose 2 40% closer to neutral pose 0 for the board's current rig.
    2: {
        "shoulder_pan.pos": -2.2153846153846155,
        "shoulder_lift.pos": -46.989010989010985,
        "elbow_flex.pos": -11.99120879120879,
        "wrist_flex.pos": 49.39745054945055,
        "wrist_roll.pos": 80.4131868131868,
        "gripper.pos": 3.64963503649635,
    },
    3: {
        "shoulder_pan.pos": -46.24175824175824,
        "shoulder_lift.pos": -46.989010989010985,
        "elbow_flex.pos": -11.956043956043956,
        "wrist_flex.pos": -16.88,
        "wrist_roll.pos": 80.48351648351648,
        "gripper.pos": 3.64963503649635,
    },
    4: {
        "shoulder_pan.pos": 33.84615384615385,
        "shoulder_lift.pos": -46.989010989010985,
        "elbow_flex.pos": -11.956043956043956,
        "wrist_flex.pos": -16.88,
        "wrist_roll.pos": 80.48351648351648,
        "gripper.pos": 3.64963503649635,
    },
}

# ═══════════════════════════════════════════════════════════════
# 动作组定义 — 合并自 group_1/2/3.py
# ═══════════════════════════════════════════════════════════════

ACTION_GROUPS: dict[str, dict] = {
    "group_1": {
        "steps": 60,
        "delay": 0.03,
        "sequence": [1, 2, 1, 2, 1, 2, 0],
        "smoothstep": True,
    },
    "group_2": {
        "steps": 60,
        "delay": 0.015,
        "sequence": [3, 4, 3, 4, 3, 4, 0],
        "smoothstep": True,
    },
}

# 外部动作名 → 内部组名
ACTION_MAP = {
    "nod": "group_1",
}


# ═══════════════════════════════════════════════════════════════
# 机器人底层控制
# ═══════════════════════════════════════════════════════════════

def get_pose(robot) -> dict[str, float]:
    obs = robot.get_observation()
    return {k: float(obs[k]) for k in JOINT_KEYS}


def build_action(values):
    return dict(zip(JOINT_KEYS, values))


def move_to_action(
    robot,
    target: dict[str, float],
    steps: int,
    step_delay: float,
    use_smoothstep: bool = False,
    *,
    stop_event: threading.Event | None = None,
    deadline_monotonic: float | None = None,
) -> bool:
    """移动到目标姿态.

    Args:
        robot: SO101Follower 实例.
        target: 目标关节角度字典.
        steps: 插值步数.
        step_delay: 每步间隔 (秒).
        use_smoothstep: True 使用 smoothstep 缓入缓出; False 使用线性插值.
    """
    def should_stop() -> bool:
        if stop_event is not None and stop_event.is_set():
            return True
        return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic

    if should_stop():
        return False
    start = get_pose(robot)
    if should_stop():
        return False

    start_vals = [start[k] for k in JOINT_KEYS]
    target_vals = [target[k] for k in JOINT_KEYS]

    for i in range(1, steps + 1):
        if should_stop():
            return False
        r = i / steps
        if use_smoothstep:
            # smoothstep: 端点零速度和零加速度，消除抖动
            r = r * r * r * (r * (r * 6 - 15) + 10)

        current = [
            s + (t - s) * r
            for s, t in zip(start_vals, target_vals)
        ]

        robot.send_action(build_action(current))
        if stop_event is not None:
            if stop_event.wait(step_delay):
                return False
        else:
            time.sleep(step_delay)
    return not should_stop()


# ═══════════════════════════════════════════════════════════════
# 动作服务器
# ═══════════════════════════════════════════════════════════════

class ArmActionServer:
    """机械臂动作 TCP 服务器.

    在 127.0.0.1:8764 监听 NDJSON 消息，解析 arm_action 并执行对应动作组.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or os.environ.get("XINGBAO_ARM_ACTION_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("XINGBAO_ARM_ACTION_PORT", "8764"))
        self.robot = None
        self.actions: dict[int, dict[str, float]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()  # 用于中断死循环动作组

    # ── 初始化 ──────────────────────────────────────────────

    def init_robot(self) -> None:
        """连接机器人并使用写死的关节姿态."""
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        # 直接使用模块级 JOINT_POSES，无需 CSV 加载
        self.actions = JOINT_POSES

        print("已加载动作 (写死):")
        for idx in sorted(self.actions):
            action = self.actions[idx]
            print(
                f"  #{idx}:",
                ", ".join(
                    f"{k.removesuffix('.pos')}={v:.2f}"
                    for k, v in action.items()
                ),
            )

        self.robot = SO101Follower(
            SO101FollowerConfig(
                port=ROBOT_PORT,
                id="so101_arm_server",
                disable_torque_on_disconnect=False,
                use_degrees=True,
            )
        )
        print(f"连接机器人: {ROBOT_PORT}")
        self.robot.connect(calibrate=True)
        print("机器人就绪.")

    # ── 动作执行（同步，运行在线程池中）─────────────────────

    def execute_group(self, group_name: str) -> dict:
        """执行一个动作组的完整序列（线程安全，非阻塞锁）."""
        if not self._lock.acquire(blocking=False):
            return {
                "ok": False,
                "error": "robot_busy",
                "message": "机械臂正在执行其他动作，请稍后重试",
            }

        try:
            cfg = ACTION_GROUPS[group_name]
            steps = cfg["steps"]
            delay = cfg["delay"]
            smooth = cfg["smoothstep"]

            # 死循环模式 (loop_pair)
            if "loop_pair" in cfg:
                a, b = cfg["loop_pair"]
                print(
                    f"[{group_name}] 开始死循环: "
                    f"#{a} <-> #{b} (收到新指令时停止)"
                )
                idx = 0
                pair = [a, b]
                self._stop_event.clear()
                while not self._stop_event.is_set():
                    order = pair[idx]
                    print(f"[{group_name}] 移动到 #{order} ...")
                    move_to_action(
                        self.robot,
                        self.actions[order],
                        steps=steps,
                        step_delay=delay,
                        use_smoothstep=smooth,
                    )
                    idx ^= 1  # 0->1, 1->0

                print(f"[{group_name}] 死循环已停止.")
                return {
                    "ok": True,
                    "implemented": True,
                    "group": group_name,
                    "message": "loop_stopped",
                }

            # 序列模式 (sequence)
            sequence = cfg["sequence"]
            print(
                f"[{group_name}] 开始执行序列: "
                f"{' -> '.join(f'#{x}' for x in sequence)}"
            )

            for i, order in enumerate(sequence):
                print(
                    f"[{group_name}] [{i+1}/{len(sequence)}] "
                    f"移动到 #{order} ..."
                )
                move_to_action(
                    self.robot,
                    self.actions[order],
                    steps=steps,
                    step_delay=delay,
                    use_smoothstep=smooth,
                )

            print(f"[{group_name}] 序列执行完成.")
            return {
                "ok": True,
                "implemented": True,
                "group": group_name,
                "message": "sequence_completed",
            }
        except Exception as e:
            print(f"[{group_name}] 执行失败: {e}")
            return {
                "ok": False,
                "implemented": False,
                "group": group_name,
                "error": str(e),
            }
        finally:
            self._lock.release()

    def handle_action_sync(self, action_name: str, request_id: str = "") -> dict:
        """同步处理动作请求：映射 → 校验 → 执行.

        在 executor 线程中调用，快速返回 busy 或提交执行.
        """
        # 0. stay_still — 停止当前循环 + 空操作
        if action_name == "stay_still":
            print(f"[收到] stay_still (停止当前动作)")
            self._stop_event.set()
            return {
                "type": "command_result",
                "request_id": request_id,
                "ok": True,
                "results": [],
                "hardware_feedback": {
                    "ok": True,
                    "implemented_by": "board_hardware_team",
                    "arm_action": "stay_still",
                    "implemented": True,
                    "error": None,
                },
            }

        # 1. 只接受高层白名单动作，禁止外部直接调用 group_1/group_2。
        if action_name not in ACTION_MAP:
            print(f"未知动作 '{action_name}'，降级为 stay_still")
            return {
                "type": "command_result",
                "request_id": request_id,
                "ok": True,
                "results": [],
                "hardware_feedback": {
                    "ok": True,
                    "implemented_by": "board_hardware_team",
                    "arm_action": "stay_still",
                    "implemented": False,
                    "error": f"unknown_action: {action_name}",
                },
            }

        # 2. 映射外部高层动作名到隔离的内部动作组。
        group = ACTION_MAP[action_name]

        # 3. 停止当前死循环（如果有的话），等锁释放
        self._stop_event.set()
        for _ in range(50):  # 最多等 0.5 秒
            if self._lock.acquire(blocking=False):
                self._lock.release()
                break
            time.sleep(0.01)
        self._stop_event.clear()

        # 4. 执行
        result = self.execute_group(group)

        return {
            "type": "command_result",
            "request_id": request_id,
            "ok": result["ok"],
            "results": [],
                "hardware_feedback": {
                    "ok": result["ok"],
                    "implemented_by": "board_hardware_team",
                    "arm_action": action_name,
                    "hardware_group": group,
                    "implemented": result.get("implemented", False),
                    "error": result.get("error"),
            },
        }

    # ── TCP 服务（asyncio）─────────────────────────────────

    async def handle_client(self, reader, writer):
        """处理单个 TCP 客户端连接."""
        addr = writer.get_extra_info("peername")
        print(f"[连接] {addr}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                text = line.decode("utf-8").strip()
                if not text:
                    continue

                # 解析 NDJSON
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError as e:
                    print(f"[解析错误] {e}: {text[:120]}")
                    continue

                # 提取 arm_action（支持顶层和 payload 嵌套两种格式）
                arm_action = None
                request_id = msg.get("request_id", "")

                if "arm_action" in msg:
                    arm_action = msg["arm_action"]
                elif "payload" in msg and isinstance(msg["payload"], dict):
                    arm_action = msg["payload"].get("arm_action")

                if not isinstance(arm_action, str) or not arm_action.strip():
                    print(f"[跳过] 无法提取 arm_action: {text[:120]}")
                    continue
                arm_action = arm_action.strip()
                if len(arm_action) > 32:
                    print(f"[跳过] arm_action 过长: {arm_action[:32]}")
                    continue

                print(f"[收到] arm_action={arm_action} request_id={request_id}")

                # 在线程池中执行同步动作代码
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self.handle_action_sync,
                    arm_action,
                    request_id,
                )

                # 返回 NDJSON 响应
                response = json.dumps(result, ensure_ascii=False) + "\n"
                writer.write(response.encode("utf-8"))
                await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[客户端错误] {addr}: {e}")
        finally:
            print(f"[断开] {addr}")
            writer.close()
            await writer.wait_closed()

    async def run(self):
        """启动 TCP 服务器."""
        loop = asyncio.get_event_loop()

        # 机器人初始化（同步阻塞，放到 executor）
        await loop.run_in_executor(None, self.init_robot)

        # 设置 SO_REUSEADDR 防止重启时端口被占用
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port,
            reuse_address=True,
            limit=4096,
        )

        addr = server.sockets[0].getsockname()
        print(f"机械臂动作服务器已启动: tcp://{addr[0]}:{addr[1]}")
        print(f"动作映射: {json.dumps(ACTION_MAP, ensure_ascii=False)}")
        print("等待指令...")

        async with server:
            await server.serve_forever()

    def shutdown(self):
        """断开机器人连接."""
        if self.robot and getattr(self.robot, "is_connected", False):
            self.robot.disconnect()
            print("机器人已断开.")


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    server = ArmActionServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
