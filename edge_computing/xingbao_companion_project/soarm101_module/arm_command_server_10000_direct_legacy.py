#!/usr/bin/env python3
"""SO-101 编号动作 TCP 服务器（监听 10000 端口）。

协议：客户端建立 TCP 连接后，发送一个 UTF-8 编号并以换行结尾，例如
``12\n``。服务器只接受 ``11``、``12``、``13``、``21``、``22``、``23``。
不合规编号不会触发任何机械臂动作。每条请求都会得到一行 JSON 回执。

动作规则：
* 启动后立即回到旧 CSV 的初始位置；
* 六个编号依次对应最新配置文件的关键点 1 至 6；
* 收到新的已配置编号时，当前插值会在下一步中断并转向新目标；
* 3.5 秒未收到新的已配置编号时，回到旧 CSV 的初始位置。

所有坐标均硬编码在本文件内；运行时不会读取 CSV。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import socket
import threading
import time
from typing import Any

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig


HOST = "0.0.0.0"
PORT = 10000
DEFAULT_DEVICE = "/dev/ttyCH343USB0"
DEFAULT_ROBOT_ID = "so101_arm_server"
STEPS = 90
STEP_DELAY = 0.04
IDLE_RETURN_SECONDS = 3.5
HAND_CONTROL_HOST = "127.0.0.1"
HAND_CONTROL_PORT = 10001

JOINT_KEYS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)
VALID_COMMANDS = frozenset({"11", "12", "13", "21", "22", "23"})
COMMAND_RE = re.compile(r"^(?:11|12|13|21|22|23)$")

# 旧 CSV：so101_keypoints_20260809_063559.csv / point=initial
OLD_INITIAL = {
    "shoulder_pan.pos": -2.3736263736263736,
    "shoulder_lift.pos": -48.13186813186813,
    "elbow_flex.pos": -3.7362637362637363,
    "wrist_flex.pos": -16.175824175824175,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 3.413654618473896,
}

# 最新 CSV：so101_keypoints_20260809_074848.csv / key_point_1 至 key_point_6。
# 初始位仍使用上方固定的 OLD_INITIAL，不使用最新 CSV 的 initial 行。
LATEST_KEY_POINT_1 = {
    "shoulder_pan.pos": -18.197802197802197,
    "shoulder_lift.pos": -5.142857142857143,
    "elbow_flex.pos": 24.835164835164836,
    "wrist_flex.pos": -138.72527472527472,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 78.714859437751,
}
LATEST_KEY_POINT_2 = {
    "shoulder_pan.pos": 2.7252747252747254,
    "shoulder_lift.pos": -3.208791208791209,
    "elbow_flex.pos": 24.835164835164836,
    "wrist_flex.pos": -139.25274725274724,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 78.6479250334672,
}
LATEST_KEY_POINT_3 = {
    "shoulder_pan.pos": 23.560439560439562,
    "shoulder_lift.pos": -3.3846153846153846,
    "elbow_flex.pos": 23.86813186813187,
    "wrist_flex.pos": -139.34065934065933,
    "wrist_roll.pos": 78.81318681318682,
    "gripper.pos": 78.6479250334672,
}
LATEST_KEY_POINT_4 = {
    "shoulder_pan.pos": -22.24175824175824,
    "shoulder_lift.pos": 24.65934065934066,
    "elbow_flex.pos": 14.373626373626374,
    "wrist_flex.pos": -141.53846153846155,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 69.14323962516734,
}
LATEST_KEY_POINT_5 = {
    "shoulder_pan.pos": -1.934065934065934,
    "shoulder_lift.pos": 12.43956043956044,
    "elbow_flex.pos": 31.78021978021978,
    "wrist_flex.pos": -142.15384615384616,
    "wrist_roll.pos": 78.81318681318682,
    "gripper.pos": 68.20615796519411,
}
LATEST_KEY_POINT_6 = {
    "shoulder_pan.pos": 23.208791208791208,
    "shoulder_lift.pos": 31.252747252747252,
    "elbow_flex.pos": 6.1098901098901095,
    "wrist_flex.pos": -142.06593406593407,
    "wrist_roll.pos": 78.9010989010989,
    "gripper.pos": 68.20615796519411,
}

COMMAND_TARGETS: dict[str, dict[str, float]] = {
    "11": LATEST_KEY_POINT_1,
    "12": LATEST_KEY_POINT_2,
    "13": LATEST_KEY_POINT_3,
    "21": LATEST_KEY_POINT_4,
    "22": LATEST_KEY_POINT_5,
    "23": LATEST_KEY_POINT_6,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SO-101 编号动作 TCP 服务器")
    parser.add_argument("--host", default=HOST, help=f"监听地址（默认：{HOST}）")
    parser.add_argument("--port", type=int, default=PORT, help=f"监听端口（默认：{PORT}）")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help=f"机械臂串口（默认：{DEFAULT_DEVICE}）")
    parser.add_argument("--robot-id", default=DEFAULT_ROBOT_ID, help="机械臂 ID")
    return parser.parse_args()


def get_pose(robot: SO101Follower) -> dict[str, float]:
    observation: dict[str, Any] = robot.get_observation()
    return {joint: float(observation[joint]) for joint in JOINT_KEYS}


def move_to_target(
    robot: SO101Follower,
    target: dict[str, float],
    cancel_event: threading.Event,
) -> bool:
    """以与回放脚本一致的 smoothstep 插值移动；收到新指令即安全中断。"""
    start = get_pose(robot)
    for index in range(1, STEPS + 1):
        if cancel_event.is_set():
            return False
        ratio = index / STEPS
        ratio = ratio * ratio * ratio * (ratio * (ratio * 6 - 15) + 10)
        robot.send_action(
            {
                joint: start[joint] + (target[joint] - start[joint]) * ratio
                for joint in JOINT_KEYS
            }
        )
        if cancel_event.wait(STEP_DELAY):
            return False
    return True


def notify_hand_recognition_disable() -> dict[str, object] | None:
    """Send the documented local 10001 disable command after returning home."""
    try:
        with socket.create_connection((HAND_CONTROL_HOST, HAND_CONTROL_PORT), timeout=0.5) as sock:
            sock.settimeout(0.5)
            sock.sendall(b"disable\n")
            raw = b""
            while b"\n" not in raw:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
        response = json.loads(raw.split(b"\n", 1)[0].decode("utf-8-sig"))
        return response if isinstance(response, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"视觉手部识别 disable 通知失败：{type(error).__name__}: {error}", flush=True)
        return None


class CommandServer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.commands: asyncio.Queue[str] = asyncio.Queue()
        self.robot: SO101Follower | None = None
        self.current_future: asyncio.Future[bool] | None = None
        self.current_cancel: threading.Event | None = None
        self.current_name = ""
        self.last_distinct_command_at = time.monotonic()
        self.active_command: str | None = None
        self.motion_generation = 0

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
            command = raw.decode("utf-8", errors="replace").strip()
            if not COMMAND_RE.fullmatch(command):
                reply = {"ok": False, "error": "invalid_command", "command": command}
            elif COMMAND_TARGETS[command] is None:
                reply = {"ok": True, "executed": False, "command": command, "error": "command_not_configured"}
            elif self._is_duplicate_command(command):
                reply = {"ok": True, "executed": False, "command": command, "ignored": "duplicate_command"}
            else:
                await self.commands.put(command)
                reply = {"ok": True, "executed": True, "command": command}
            writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
            print(f"IPC {peer}: {reply}", flush=True)
        except (asyncio.TimeoutError, ConnectionError, UnicodeError) as error:
            print(f"IPC {peer} 读取失败：{error}", flush=True)
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    def _is_duplicate_command(self, command: str) -> bool:
        return (
            command == self.active_command
            and time.monotonic() - self.last_distinct_command_at < IDLE_RETURN_SECONDS
        )

    async def _stop_current_motion(self) -> None:
        if self.current_cancel is not None:
            self.current_cancel.set()
        if self.current_future is not None:
            await self.current_future
        self.current_future = None
        self.current_cancel = None

    async def _start_motion(self, name: str, target: dict[str, float]) -> None:
        await self._stop_current_motion()
        if self.robot is None:
            raise RuntimeError("机械臂尚未连接")
        self.current_name = name
        self.motion_generation += 1
        self.current_cancel = threading.Event()
        loop = asyncio.get_running_loop()
        self.current_future = loop.run_in_executor(None, move_to_target, self.robot, target, self.current_cancel)
        print(f"开始移动：{name}", flush=True)

    async def _disable_after_home_motion(
        self,
        motion: asyncio.Future[bool],
        generation: int,
    ) -> None:
        try:
            completed = await motion
        except Exception as error:
            print(f"初始位动作失败，未发送 disable：{error}", flush=True)
            return
        if not completed or generation != self.motion_generation or self.active_command is not None:
            return
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, notify_hand_recognition_disable)
        print(f"初始位完成，视觉 disable 回执：{reply}", flush=True)

    async def run_motion_controller(self) -> None:
        """处理最新编号和空闲超时；硬件移动在工作线程内执行。"""
        await self._start_motion("旧 CSV 初始位置（启动复位）", OLD_INITIAL)
        current_is_home = True
        while True:
            try:
                command = await asyncio.wait_for(self.commands.get(), timeout=0.05)
            except asyncio.TimeoutError:
                command = None

            if command is not None:
                target = COMMAND_TARGETS[command]
                if target is not None:
                    if self._is_duplicate_command(command):
                        continue
                    self.last_distinct_command_at = time.monotonic()
                    self.active_command = command
                    await self._start_motion(f"编号 {command}", target)
                    current_is_home = False
                continue

            if not current_is_home and time.monotonic() - self.last_distinct_command_at >= IDLE_RETURN_SECONDS:
                self.active_command = None
                await self._start_motion("旧 CSV 初始位置（空闲复位）", OLD_INITIAL)
                current_is_home = True
                if self.current_future is not None:
                    asyncio.create_task(
                        self._disable_after_home_motion(
                            self.current_future,
                            self.motion_generation,
                        )
                    )

    async def run(self) -> None:
        self.robot = SO101Follower(
            SO101FollowerConfig(
                port=self.args.device,
                id=self.args.robot_id,
                disable_torque_on_disconnect=False,
                use_degrees=True,
            )
        )
        print(f"连接机械臂：{self.args.device}", flush=True)
        self.robot.connect(calibrate=False)
        server = await asyncio.start_server(self.handle_client, self.args.host, self.args.port)
        sockets = ", ".join(str(socket.getsockname()) for socket in server.sockets or [])
        print(f"机械臂服务器已监听 {sockets}", flush=True)
        try:
            async with server:
                await self.run_motion_controller()
        finally:
            await self._stop_current_motion()
            if self.robot.is_connected:
                self.robot.disconnect()
            print("机械臂已断开。", flush=True)


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(CommandServer(args).run())
    except KeyboardInterrupt:
        print("\n服务器已停止。")


if __name__ == "__main__":
    main()
