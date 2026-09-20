"""Read-only SC171V3 connectivity and source-manifest audit helper."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_USER = "fibo"
DEFAULT_ROOTS = (
    "/home/fibo/xingbao_releases/current",
    "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge",
    "/home/fibo/arm_luojiefu/xingbao/xingbao/"
    "xingbao_competition_fix_20260721_r5/project/hardware/soarm101",
)


REMOTE_MANIFEST_SCRIPT = r'''from __future__ import print_function
import hashlib
import json
import os
import sys

ROOTS = sys.argv[1:]
EXCLUDED_DIRS = {
    '.git', '.venv', 'venv', '__pycache__', 'cache', 'data', 'logs', 'saves',
    'screenshots', 'recordings', 'artworks', 'memory_shots', 'work', 'tmp',
}
EXCLUDED_NAMES = {
    '.env', 'runtime.env', 'child_profile.json', 'memory.json',
    'conversation_history.json', 'parent_summaries.json',
}
ALLOWED_SUFFIXES = {
    '.py', '.json', '.html', '.css', '.js', '.sh', '.service', '.md', '.txt',
    '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.xml', '.svg', '.tex',
}

def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            value.update(chunk)
    return value.hexdigest()

result = {'schema_version': 1, 'roots': [], 'files': [], 'errors': []}
for root in ROOTS:
    root = os.path.realpath(root)
    result['roots'].append(root)
    if not os.path.isdir(root):
        result['errors'].append({'root': root, 'error': 'missing_directory'})
        continue
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(
            item for item in dirs
            if item not in EXCLUDED_DIRS and not item.startswith('.')
        )
        for name in sorted(files):
            if name in EXCLUDED_NAMES or name.startswith('.'):
                continue
            suffix = os.path.splitext(name)[1].lower()
            if suffix not in ALLOWED_SUFFIXES:
                continue
            path = os.path.join(current, name)
            if os.path.islink(path):
                continue
            try:
                stat = os.stat(path)
                result['files'].append({
                    'root': root,
                    'path': os.path.relpath(path, root).replace(os.sep, '/'),
                    'size': int(stat.st_size),
                    'sha256': digest(path),
                })
            except Exception as exc:
                result['errors'].append({
                    'root': root,
                    'path': os.path.relpath(path, root).replace(os.sep, '/'),
                    'error': type(exc).__name__,
                })
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
'''


class AuditError(RuntimeError):
    """The read-only board audit could not complete safely."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def probe_port(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe(host: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "host": host,
        "checked_at": now_iso(),
        "ports": {
            "ssh_22": probe_port(host, 22),
            "adb_5555": probe_port(host, 5555),
        },
        "board_files_read": False,
        "board_files_modified": False,
    }


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    files = data.get("files")
    if data.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    if not isinstance(files, list):
        return errors + ["files 必须是列表"]
    forbidden_names = {
        ".env",
        "runtime.env",
        "child_profile.json",
        "memory.json",
        "conversation_history.json",
        "parent_summaries.json",
    }
    forbidden_parts = {"data", "logs", "saves", "cache", "recordings", "artworks"}
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            errors.append(f"files[{index}] 必须是对象")
            continue
        path = str(item.get("path", ""))
        parts = {part.lower() for part in Path(path).parts}
        if Path(path).name.lower() in forbidden_names or parts.intersection(forbidden_parts):
            errors.append(f"清单包含禁止路径：{path}")
        sha256 = str(item.get("sha256", ""))
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            errors.append(f"清单哈希无效：{path}")
    return errors


def capture_manifest(
    *,
    host: str,
    user: str,
    roots: list[str],
    output: Path,
    timeout: float = 120.0,
) -> dict[str, Any]:
    if not probe_port(host, 22):
        raise AuditError(f"{host}:22 不可达；没有读取或修改板卡文件")
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=8",
        f"{user}@{host}",
        "python3",
        "-",
        *roots,
    ]
    try:
        result = subprocess.run(
            command,
            input=REMOTE_MANIFEST_SCRIPT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AuditError("板卡只读清单生成超时") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise AuditError(f"板卡只读清单失败：{message}")
    try:
        remote = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AuditError("板卡返回了无效的清单 JSON") from exc
    if not isinstance(remote, dict):
        raise AuditError("板卡清单顶层必须是对象")
    errors = validate_manifest(remote)
    if errors:
        raise AuditError("板卡清单安全校验失败：\n- " + "\n- ".join(errors))
    manifest = {
        "schema_version": 1,
        "host": host,
        "user": user,
        "captured_at": now_iso(),
        "read_only": True,
        "board_files_modified": False,
        "remote": remote,
    }
    atomic_write_json(output, manifest)
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--host",
        default=os.environ.get("XINGBAO_BOARD_HOST", "").strip(),
        help="当前网络下的板卡 IP 或主机名；也可设置 XINGBAO_BOARD_HOST",
    )
    result.add_argument("--user", default=DEFAULT_USER)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("probe")
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--root", action="append", default=[])
    manifest.add_argument("--output", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not args.host:
            raise AuditError(
                "未提供板卡地址；换网后先确认当前地址，再使用 --host 或 "
                "XINGBAO_BOARD_HOST"
            )
        if args.command == "probe":
            result = probe(args.host)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ports"]["ssh_22"] else 2
        roots = args.root or list(DEFAULT_ROOTS)
        result = capture_manifest(
            host=args.host,
            user=args.user,
            roots=roots,
            output=args.output.resolve(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AuditError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
