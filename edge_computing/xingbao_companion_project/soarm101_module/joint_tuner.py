#!/usr/bin/env python
"""机械臂关节角度快速调整工具.

命令:
  <编号> <角度>      绝对移动: 0 45.0
  <编号> +<值>       相对增加: 1 +10  (向上10单位)
  <编号> -<值>       相对减少: 1 -10  (向下10单位)
  s                 刷新角度
  q                 退出
"""

import time

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig


ROBOT_PORT = "/dev/ttyCH343USB0"
ROBOT_ID = "so101_arm_server"

JOINTS = [
    ("shoulder_pan",   "肩部旋转"),
    ("shoulder_lift",  "肩部抬升"),
    ("elbow_flex",     "肘部弯曲"),
    ("wrist_flex",     "腕部弯曲"),
    ("wrist_roll",     "腕部旋转"),
    ("gripper",        "夹爪"),
]

STEPS = 60
STEP_DELAY = 0.015


def main() -> None:
    robot = SO101Follower(
        SO101FollowerConfig(
            port=ROBOT_PORT,
            id=ROBOT_ID,
            disable_torque_on_disconnect=False,
            use_degrees=True,
        )
    )

    try:
        print(f"连接机器人: {ROBOT_PORT}")
        robot.connect(calibrate=False)

        print("\n" + "=" * 55)
        print("  机械臂关节角度调整工具")
        print("=" * 55)
        print("命令:")
        print("  <编号> <角度>    绝对移动  例: 0 45.0")
        print("  <编号> +<值>     相对增加  例: 1 +10")
        print("  <编号> -<值>     相对减少  例: 1 -10")
        print("  s                刷新角度")
        print("  q                退出")
        print()

        while True:
            obs = robot.get_observation()
            print("当前角度:")
            for i, (key, name) in enumerate(JOINTS):
                full = key + ".pos"
                print(f"  [{i}] {key:15s} ({name}): {obs[full]:8.2f}")

            cmd = input("\n> ").strip()
            if not cmd:
                continue

            if cmd.lower() == "q":
                print("退出.")
                break

            if cmd.lower() == "s":
                continue

            # 解析: <编号> <值>  或  <编号> +<值>  或  <编号> -<值>
            parts = cmd.split()
            if len(parts) < 2:
                print("格式: <编号> <角度/相对值>  例: 0 45.0  或  1 +10")
                continue

            try:
                idx = int(parts[0])
            except ValueError:
                print("编号必须是数字")
                continue

            if idx < 0 or idx >= len(JOINTS):
                print(f"编号范围 0-{len(JOINTS)-1}")
                continue

            raw = parts[1]
            relative = raw.startswith("+") or raw.startswith("-")
            try:
                delta = float(raw)
            except ValueError:
                print("值必须是数字")
                continue

            key, name = JOINTS[idx]
            full_key = key + ".pos"
            current_all = {k + ".pos": float(obs[k + ".pos"]) for k, _ in JOINTS}

            if relative:
                target_angle = current_all[full_key] + delta
                print(f"移动 {name}: {current_all[full_key]:.2f} -> {target_angle:.2f} ({delta:+.1f}) ...")
            else:
                target_angle = delta
                print(f"移动 {name}: {current_all[full_key]:.2f} -> {target_angle:.2f} ...")

            target = dict(current_all)
            target[full_key] = target_angle

            for i in range(1, STEPS + 1):
                r = i / STEPS
                r = r * r * r * (r * (r * 6 - 15) + 10)  # smoothstep
                action = {
                    k: current_all[k] + (target[k] - current_all[k]) * r
                    for k in current_all
                }
                robot.send_action(action)
                time.sleep(STEP_DELAY)

            print("到位.")

    except KeyboardInterrupt:
        print("\n中断.")
    finally:
        if getattr(robot, "is_connected", False):
            robot.disconnect()
        print("已断开.")


if __name__ == "__main__":
    main()
