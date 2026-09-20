"""Strict cross-computer coordination gates for the Xingbao project."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROTOCOL_VERSION = "1.0.0"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]{8}-[0-9]{3,}$")
RELEASE_IMPACTS = {"none", "candidate", "required"}
BOARD_DEPLOYMENT_STATES = {
    "not_deployed",
    "deployed_unverified",
    "deployed_verified",
}


class CoordinationError(RuntimeError):
    """A coordination rule was not satisfied."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def coordination_root(repo: Path) -> Path:
    return repo / "coordination"


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CoordinationError(f"缺少文件：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CoordinationError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CoordinationError(f"JSON 顶层必须是对象：{path}")
    return data


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(str(temporary), str(path))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: float = 15.0,
) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CoordinationError(f"git {' '.join(args)} 超时") from exc
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise CoordinationError(f"git {' '.join(args)} 失败：{message}")
    return result.stdout.strip()


def read_protocol_version(repo: Path) -> str:
    path = coordination_root(repo) / "PROTOCOL_VERSION"
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise CoordinationError(f"无法读取协议版本：{path}") from exc


def current_state(repo: Path) -> dict[str, Any]:
    return load_json(coordination_root(repo) / "state" / "current-state.json")


def git_observation(repo: Path) -> dict[str, Any]:
    status = run_git(repo, "status", "--short", "--untracked-files=all")
    remotes = run_git(repo, "remote", check=False).splitlines()
    return {
        "branch": run_git(repo, "branch", "--show-current") or "(detached HEAD)",
        "head": run_git(repo, "rev-parse", "HEAD"),
        "dirty": bool(status),
        "changed_path_count": len(status.splitlines()) if status else 0,
        "board_remote_configured": "board" in remotes,
    }


def doctor(repo: Path, device_id: str, *, check_remote: bool = True) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    version = read_protocol_version(repo)
    state = current_state(repo)
    observation = git_observation(repo)

    if version != PROTOCOL_VERSION:
        blockers.append(
            f"工具协议版本 {PROTOCOL_VERSION} 与仓库版本 {version} 不一致"
        )
    if state.get("protocol_version") != version:
        blockers.append("current-state.json 的协议版本不一致")

    baseline = state.get("baseline")
    if not isinstance(baseline, dict) or baseline.get("status") != "verified":
        blockers.append("板卡比赛基线尚未验证")
    else:
        source_commit = resolve_baseline_commit(repo, baseline)
        if not valid_commit(source_commit):
            blockers.append("已验证基线缺少可解析的 source_commit 或不可变 tag")
        else:
            try:
                run_git(
                    repo,
                    "merge-base",
                    "--is-ancestor",
                    source_commit,
                    observation["head"],
                )
            except CoordinationError:
                blockers.append("本地 HEAD 不是已验证板卡基线的后代")

    if observation["dirty"]:
        blockers.append(
            f"工作区存在 {observation['changed_path_count']} 项未提交变化"
        )
    if not observation["board_remote_configured"]:
        blockers.append("未配置名为 board 的 Git 远程")
    elif check_remote:
        try:
            run_git(repo, "ls-remote", "--exit-code", "board", timeout=10.0)
        except CoordinationError as exc:
            blockers.append(f"board 远程不可读：{exc}")

    sync = state.get("sync")
    if isinstance(sync, dict) and not sync.get("offsite_backup_configured"):
        warnings.append("尚未配置板卡之外的异地备份")

    return {
        "schema_version": 1,
        "protocol_version": version,
        "device_id": device_id.strip(),
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "local": observation,
        "baseline": baseline if isinstance(baseline, dict) else {},
    }


def valid_commit(value: object) -> bool:
    text = str(value or "").strip().lower()
    return bool(COMMIT_RE.fullmatch(text)) and set(text) != {"0"}


def resolve_baseline_commit(repo: Path, baseline: dict[str, Any]) -> str:
    source_commit = str(baseline.get("source_commit", "")).strip().lower()
    if valid_commit(source_commit):
        return source_commit
    tag = str(baseline.get("tag", "")).strip()
    if not tag:
        return ""
    try:
        return run_git(
            repo,
            "rev-parse",
            "--verify",
            f"refs/tags/{tag}^{{commit}}",
        ).lower()
    except CoordinationError:
        return ""


def require_nonempty_string(data: dict[str, Any], key: str, errors: list[str]) -> None:
    if not isinstance(data.get(key), str) or not str(data.get(key)).strip():
        errors.append(f"{key} 必须是非空字符串")


def require_nonempty_list(data: dict[str, Any], key: str, errors: list[str]) -> None:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        errors.append(f"{key} 必须是非空列表")


def require_string_list(data: dict[str, Any], key: str, errors: list[str]) -> None:
    value = data.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        errors.append(f"{key} 必须是字符串列表")


def validate_age_impact(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["age_4_6_impact 必须是对象"]
    errors: list[str] = []
    if value.get("suitable") is not True:
        errors.append("age_4_6_impact.suitable 必须明确为 true")
    for key in (
        "language_change",
        "touch_fallback",
        "confusion_risk",
        "verification_case",
    ):
        if not isinstance(value.get(key), str) or not str(value.get(key)).strip():
            errors.append(f"age_4_6_impact.{key} 必须填写")
    return errors


def validate_task(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        errors.append(f"protocol_version 必须为 {PROTOCOL_VERSION}")
    task_id = str(data.get("task_id", "")).strip()
    if not TASK_ID_RE.fullmatch(task_id):
        errors.append("task_id 格式应为 XB-YYYYMMDD-001")
    for key in ("title", "owner_device", "developer", "goal"):
        require_nonempty_string(data, key, errors)
    if data.get("status") != "active":
        errors.append("新认领任务的 status 必须为 active")
    if not valid_commit(data.get("base_commit")):
        errors.append("base_commit 必须是非零 40 位 Git commit")
    expected_branch = (
        f"codex/{str(data.get('owner_device', '')).strip()}/{task_id}"
    )
    if data.get("branch") != expected_branch:
        errors.append(f"branch 必须为 {expected_branch}")
    require_string_list(data, "non_goals", errors)
    for key in ("planned_direction", "planned_files"):
        require_nonempty_list(data, key, errors)
        require_string_list(data, key, errors)
    for key in ("interfaces_affected", "dependencies"):
        require_string_list(data, key, errors)
    errors.extend(validate_age_impact(data.get("age_4_6_impact")))
    if data.get("release_impact") not in RELEASE_IMPACTS:
        errors.append("release_impact 必须是 none/candidate/required")
    return errors


def validate_checkpoint(data: dict[str, Any], task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    if data.get("task_id") != task.get("task_id"):
        errors.append("checkpoint.task_id 与活动任务不一致")
    if data.get("owner_device") != task.get("owner_device"):
        errors.append("checkpoint.owner_device 与活动任务不一致")
    if not valid_commit(data.get("current_commit")):
        errors.append("current_commit 必须是非零 40 位 Git commit")
    for key in ("completed", "next", "decisions", "changed_files", "verification_so_far", "risks"):
        require_string_list(data, key, errors)
    require_nonempty_list(data, "completed", errors)
    require_nonempty_list(data, "next", errors)
    if data.get("board_deployment") not in BOARD_DEPLOYMENT_STATES:
        errors.append("board_deployment 状态无效")
    return errors


def validate_handoff(data: dict[str, Any], task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        errors.append(f"protocol_version 必须为 {PROTOCOL_VERSION}")
    if data.get("task_id") != task.get("task_id"):
        errors.append("handoff.task_id 与活动任务不一致")
    if data.get("owner_device") != task.get("owner_device"):
        errors.append("handoff.owner_device 与活动任务不一致")
    for key in ("title", "goal", "remote_branch", "rollback", "age_4_6_result"):
        require_nonempty_string(data, key, errors)
    for key in ("base_commit", "final_commit"):
        if not valid_commit(data.get(key)):
            errors.append(f"{key} 必须是非零 40 位 Git commit")
    if data.get("base_commit") != task.get("base_commit"):
        errors.append("handoff.base_commit 与活动任务不一致")
    if data.get("remote_branch") != task.get("branch"):
        errors.append("handoff.remote_branch 与活动任务不一致")
    for key in (
        "non_goals",
        "changed_files",
        "interfaces_changed",
        "decisions",
        "alternatives_rejected",
        "unverified",
        "risks",
        "follow_ups",
    ):
        require_string_list(data, key, errors)
    for key in ("changed_files", "decisions"):
        require_nonempty_list(data, key, errors)

    verification = data.get("verification")
    if not isinstance(verification, list) or not verification:
        errors.append("verification 必须包含至少一条验证")
    else:
        for index, item in enumerate(verification):
            if not isinstance(item, dict):
                errors.append(f"verification[{index}] 必须是对象")
                continue
            if not str(item.get("command", "")).strip():
                errors.append(f"verification[{index}].command 必须填写")
            if item.get("passed") is not True:
                errors.append(f"verification[{index}] 必须明确通过")
            if not str(item.get("result", "")).strip():
                errors.append(f"verification[{index}].result 必须填写")

    deployment = data.get("board_deployment")
    if not isinstance(deployment, dict):
        errors.append("board_deployment 必须是对象")
    elif deployment.get("status") not in BOARD_DEPLOYMENT_STATES:
        errors.append("board_deployment.status 状态无效")
    if data.get("release_impact") not in RELEASE_IMPACTS:
        errors.append("release_impact 必须是 none/candidate/required")
    return errors


def json_files(path: Path) -> Iterable[Path]:
    if not path.exists():
        return ()
    return sorted(path.glob("*.json"))


def active_tasks(repo: Path) -> list[dict[str, Any]]:
    root = coordination_root(repo) / "tasks" / "active"
    return [load_json(path) for path in json_files(root)]


def conflict_errors(candidate: dict[str, Any], existing: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    candidate_files = set(candidate.get("planned_files", []))
    candidate_interfaces = set(candidate.get("interfaces_affected", []))
    for task in existing:
        if task.get("task_id") == candidate.get("task_id"):
            errors.append(f"任务 {candidate.get('task_id')} 已存在")
            continue
        shared_files = sorted(candidate_files.intersection(task.get("planned_files", [])))
        shared_interfaces = sorted(
            candidate_interfaces.intersection(task.get("interfaces_affected", []))
        )
        if shared_files:
            errors.append(
                f"与活动任务 {task.get('task_id')} 冲突文件：{', '.join(shared_files)}"
            )
        if shared_interfaces:
            errors.append(
                f"与活动任务 {task.get('task_id')} 冲突接口：{', '.join(shared_interfaces)}"
            )
    return errors


def refresh_state(repo: Path) -> dict[str, Any]:
    root = coordination_root(repo)
    state_path = root / "state" / "current-state.json"
    state = load_json(state_path)
    tasks = active_tasks(repo)
    observation = git_observation(repo)
    state["protocol_version"] = read_protocol_version(repo)
    state["active_tasks"] = [
        {
            "task_id": task.get("task_id"),
            "title": task.get("title"),
            "owner_device": task.get("owner_device"),
            "branch": task.get("branch"),
            "last_checkpoint_at": task.get("last_checkpoint_at", ""),
        }
        for task in tasks
    ]
    state["local_observation"] = observation
    state["generated_at"] = now_iso()
    atomic_write_json(state_path, state)
    atomic_write_text(root / "state" / "CURRENT_STATE.md", render_state(state))
    return state


def render_state(state: dict[str, Any]) -> str:
    baseline = state.get("baseline") if isinstance(state.get("baseline"), dict) else {}
    board = state.get("board") if isinstance(state.get("board"), dict) else {}
    release = state.get("release") if isinstance(state.get("release"), dict) else {}
    sync = state.get("sync") if isinstance(state.get("sync"), dict) else {}
    local = (
        state.get("local_observation")
        if isinstance(state.get("local_observation"), dict)
        else {}
    )
    tasks = state.get("active_tasks") if isinstance(state.get("active_tasks"), list) else []
    board_host = str(board.get("host") or "").strip()
    board_address = board_host or "动态获取（换网络后重新确认）"
    authentication_policy = str(board.get("authentication_policy") or "").strip()
    authentication_summary = (
        "主开发电脑保留 key 自动登录；其他电脑手动输入密码，key 可选"
        if authentication_policy
        == "primary_device_key_other_devices_manual_password"
        else authentication_policy or "未记录"
    )
    task_lines = (
        "\n".join(
            f"- `{item.get('task_id')}` {item.get('title')} "
            f"（{item.get('owner_device')} / `{item.get('branch')}`）"
            for item in tasks
            if isinstance(item, dict)
        )
        or "- 暂无活动任务。"
    )
    return f"""# 星宝团队当前状态

> 由 `python tools/team_coordination.py refresh` 生成于 `{state.get('generated_at', '')}`。

- 协议版本：`{state.get('protocol_version', '')}`
- 开发门禁：`{state.get('development_gate', '')}`
- 权威基线来源：`{baseline.get('authority', '')}`
- 基线状态：`{baseline.get('status', '')}`
- 基线提交：`{baseline.get('source_commit', '') or '未确认'}`
- 板卡地址：`{board_address}`
- 地址策略：`{board.get('address_policy', 'dynamic_per_network')}`
- SSH 认证策略：{authentication_summary}
- 板卡身份已验证：`{bool(board.get('identity_verified'))}`
- 当前 Release：`{release.get('release_id', '') or '未确认'}`
- 完全同步：`{bool(sync.get('fully_synced'))}`

## 本机观察

- 分支：`{local.get('branch', '')}`
- HEAD：`{local.get('head', '')}`
- 工作区未提交变化：`{bool(local.get('dirty'))}`
- 变化路径数：`{local.get('changed_path_count', 0)}`
- board 远程已配置：`{bool(local.get('board_remote_configured'))}`

## 活动任务

{task_lines}

## 门禁解释

基线未达到 `verified`、工作区不干净或 `board` 远程不可读时，只允许只读调查、
板卡基线恢复和协作基础设施修复，不允许普通产品功能开发。
"""


def validate_repository(repo: Path) -> list[str]:
    errors: list[str] = []
    if read_protocol_version(repo) != PROTOCOL_VERSION:
        errors.append("仓库协议版本与工具不一致")
    tasks = active_tasks(repo)
    for task in tasks:
        task_errors = validate_task(task)
        errors.extend(f"{task.get('task_id', 'unknown')}: {item}" for item in task_errors)
    for index, task in enumerate(tasks):
        errors.extend(conflict_errors(task, tasks[:index]))
    return errors


def claim_task(repo: Path, path: Path) -> dict[str, Any]:
    task = load_json(path)
    errors = validate_task(task)
    errors.extend(conflict_errors(task, active_tasks(repo)))
    report = doctor(repo, str(task.get("owner_device", "")))
    errors.extend(report["blockers"])
    if errors:
        raise CoordinationError("任务认领失败：\n- " + "\n- ".join(errors))
    if not task.get("started_at"):
        task["started_at"] = now_iso()
    task["last_checkpoint_at"] = task.get("last_checkpoint_at", "")
    target = coordination_root(repo) / "tasks" / "active" / f"{task['task_id']}.json"
    atomic_write_json(target, task)
    refresh_state(repo)
    return task


def record_checkpoint(repo: Path, task_id: str, path: Path) -> dict[str, Any]:
    task_path = coordination_root(repo) / "tasks" / "active" / f"{task_id}.json"
    task = load_json(task_path)
    checkpoint = load_json(path)
    errors = validate_checkpoint(checkpoint, task)
    if errors:
        raise CoordinationError("checkpoint 无效：\n- " + "\n- ".join(errors))
    if not checkpoint.get("created_at"):
        checkpoint["created_at"] = now_iso()
    stamp = str(checkpoint["created_at"]).replace(":", "-")
    target = coordination_root(repo) / "checkpoints" / f"{task_id}-{stamp}.json"
    atomic_write_json(target, checkpoint)
    task["last_checkpoint_at"] = checkpoint["created_at"]
    atomic_write_json(task_path, task)
    refresh_state(repo)
    return checkpoint


def verify_remote_tip(repo: Path, branch: str, commit: str) -> None:
    output = run_git(repo, "ls-remote", "--heads", "board", f"refs/heads/{branch}")
    remote_commit = output.split()[0] if output else ""
    if remote_commit != commit:
        raise CoordinationError(
            f"board/{branch} tip 为 {remote_commit or '不存在'}，不是 {commit}"
        )


def close_task(repo: Path, task_id: str, path: Path) -> dict[str, Any]:
    root = coordination_root(repo)
    task_path = root / "tasks" / "active" / f"{task_id}.json"
    task = load_json(task_path)
    handoff = load_json(path)
    errors = validate_handoff(handoff, task)
    if errors:
        raise CoordinationError("handoff 无效：\n- " + "\n- ".join(errors))
    final_commit = str(handoff["final_commit"])
    run_git(repo, "cat-file", "-e", f"{final_commit}^{{commit}}")
    verify_remote_tip(repo, str(handoff["remote_branch"]), final_commit)
    if not handoff.get("completed_at"):
        handoff["completed_at"] = now_iso()
    atomic_write_json(root / "handoffs" / f"{task_id}.json", handoff)
    completed = dict(task)
    completed["status"] = "completed"
    completed["completed_at"] = handoff["completed_at"]
    atomic_write_json(root / "tasks" / "completed" / f"{task_id}.json", completed)
    task_path.unlink()
    refresh_state(repo)
    return handoff


def parser() -> argparse.ArgumentParser:
    root = repository_root()
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", type=Path, default=root)
    commands = result.add_subparsers(dest="command", required=True)

    doctor_parser = commands.add_parser("doctor")
    doctor_parser.add_argument("--device-id", required=True)
    doctor_parser.add_argument("--no-remote-check", action="store_true")

    commands.add_parser("refresh")
    commands.add_parser("validate")

    claim_parser = commands.add_parser("claim")
    claim_parser.add_argument("--task-file", type=Path, required=True)

    checkpoint_parser = commands.add_parser("checkpoint")
    checkpoint_parser.add_argument("--task-id", required=True)
    checkpoint_parser.add_argument("--checkpoint-file", type=Path, required=True)

    close_parser = commands.add_parser("close")
    close_parser.add_argument("--task-id", required=True)
    close_parser.add_argument("--handoff-file", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.command == "doctor":
            result = doctor(
                repo,
                args.device_id,
                check_remote=not args.no_remote_check,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 2
        if args.command == "refresh":
            result = refresh_state(repo)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            errors = validate_repository(repo)
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
            return 0 if not errors else 2
        if args.command == "claim":
            result = claim_task(repo, args.task_file)
        elif args.command == "checkpoint":
            result = record_checkpoint(repo, args.task_id, args.checkpoint_file)
        elif args.command == "close":
            result = close_task(repo, args.task_id, args.handoff_file)
        else:  # pragma: no cover - argparse enforces a command
            raise CoordinationError(f"未知命令：{args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except CoordinationError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
