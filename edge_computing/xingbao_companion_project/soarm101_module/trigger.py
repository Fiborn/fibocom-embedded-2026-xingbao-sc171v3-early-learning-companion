#!/usr/bin/env python
"""机械臂动作触发程序 — 向 arm_action_server.py 发送指令."""

import json
import socket
import uuid


HOST = "127.0.0.1"
PORT = 8764

ACTIONS = [
    ("1", "nod",         "点头 (group_1)"),
    ("2", "shake_head",  "摇头 (group_2)"),
    ("3", "bow",         "鞠躬 (group_3)"),
    ("4", "stay_still",  "空操作"),
]


def send_action(action: str) -> dict | None:
    """发送 arm_action 并读取响应."""
    msg = {"arm_action": action, "request_id": str(uuid.uuid4())[:8]}

    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
        sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        fp = sock.makefile("r", encoding="utf-8")
        line = fp.readline()
        sock.close()
        if line:
            return json.loads(line)
    except ConnectionRefusedError:
        print(f"错误: 无法连接到 {HOST}:{PORT}，arm_action_server.py 是否已启动？")
    except socket.timeout:
        print("错误: 连接超时")
    return None


def main() -> None:
    print("=" * 40)
    print("  机械臂动作触发程序")
    print("=" * 40)

    while True:
        print()
        for key, name, desc in ACTIONS:
            print(f"  [{key}] {desc}")
        print("  [q] 退出")
        print()

        choice = input("选择 > ").strip()

        if choice.lower() == "q":
            print("退出.")
            break

        match = next((a for a in ACTIONS if a[0] == choice), None)
        if not match:
            print(f"无效选项 '{choice}'")
            continue

        _, action, desc = match
        print(f"发送: {action} ({desc})")
        result = send_action(action)

        if result:
            fb = result.get("hardware_feedback", {})
            status = "✓ 成功" if fb.get("ok") else "✗ 失败"
            print(f"响应: {status}")
            print(f"  arm_action: {fb.get('arm_action')}")
            print(f"  implemented: {fb.get('implemented')}")
            if fb.get("error"):
                print(f"  error: {fb.get('error')}")


if __name__ == "__main__":
    main()
