#!/usr/bin/env python3
"""向 arm_command_server_10000.py 发送编号动作触发消息。"""

from __future__ import annotations

import argparse
import json
import socket
import sys


HOST = "127.0.0.1"
PORT = 10000
COMMANDS = (
    ("11", "最新 CSV 的关键点 1"),
    ("12", "最新 CSV 的关键点 2"),
    ("13", "最新 CSV 的关键点 3"),
    ("21", "最新 CSV 的关键点 4"),
    ("22", "最新 CSV 的关键点 5"),
    ("23", "最新 CSV 的关键点 6"),
)
VALID_COMMANDS = frozenset(code for code, _ in COMMANDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="机械臂 10000 端口编号触发器")
    parser.add_argument("--host", default=HOST, help=f"服务器地址（默认：{HOST}）")
    parser.add_argument("--port", type=int, default=PORT, help=f"服务器端口（默认：{PORT}）")
    return parser.parse_args()


def send_command(command: str, host: str, port: int) -> dict[str, object] | None:
    """发送一条纯文本编号并读取服务器的单行 JSON 回执。"""
    try:
        with socket.create_connection((host, port), timeout=3.0) as sock:
            sock.sendall(f"{command}\n".encode("utf-8"))
            with sock.makefile("r", encoding="utf-8") as response_file:
                response = response_file.readline()
        if not response:
            print("错误：服务器未返回回执。", file=sys.stderr)
            return None
        return json.loads(response)
    except ConnectionRefusedError:
        print(f"错误：无法连接到 {host}:{port}，请先启动 arm_command_server_10000.py。", file=sys.stderr)
    except socket.timeout:
        print("错误：连接或读取超时。", file=sys.stderr)
    except (OSError, json.JSONDecodeError) as error:
        print(f"错误：触发失败：{error}", file=sys.stderr)
    return None


def trigger(command: str, host: str, port: int) -> None:
    result = send_command(command, host, port)
    if result is None:
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def interactive(host: str, port: int) -> None:
    print("机械臂编号触发器（端口 10000）")
    print("输入 11、12、13、21、22 或 23 触发；输入 q 退出。")
    while True:
        choice = input("请输入编号 > ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return
        if choice not in VALID_COMMANDS:
            print("无效编号，请输入 11、12、13、21、22、23 或 q。")
            continue
        trigger(choice, host, port)


def main() -> None:
    args = parse_args()
    interactive(args.host, args.port)


if __name__ == "__main__":
    main()
