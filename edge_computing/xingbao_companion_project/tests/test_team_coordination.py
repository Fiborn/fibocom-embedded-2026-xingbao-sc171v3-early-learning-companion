from __future__ import annotations

from pathlib import Path

import pytest

from tools import team_coordination as coordination


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def valid_task() -> dict:
    return {
        "schema_version": 1,
        "protocol_version": coordination.PROTOCOL_VERSION,
        "task_id": "XB-20260801-001",
        "title": "建立同步规则",
        "owner_device": "device-a",
        "developer": "开发者甲",
        "status": "active",
        "base_commit": COMMIT_A,
        "branch": "codex/device-a/XB-20260801-001",
        "goal": "建立跨电脑同步规则",
        "non_goals": ["不修改产品功能"],
        "planned_direction": ["先建立协议"],
        "planned_files": ["coordination/README.md"],
        "interfaces_affected": ["team-coordination-v1"],
        "dependencies": [],
        "age_4_6_impact": {
            "suitable": True,
            "language_change": "不改变儿童口播",
            "touch_fallback": "不改变触控",
            "confusion_risk": "无儿童交互变化",
            "verification_case": "协议校验测试通过",
        },
        "release_impact": "none",
        "started_at": "2026-08-01T12:00:00+08:00",
        "last_checkpoint_at": "",
        "lease_until": "2026-08-02T12:00:00+08:00",
    }


def valid_handoff(task: dict) -> dict:
    return {
        "schema_version": 1,
        "protocol_version": coordination.PROTOCOL_VERSION,
        "task_id": task["task_id"],
        "title": task["title"],
        "owner_device": task["owner_device"],
        "goal": task["goal"],
        "non_goals": task["non_goals"],
        "base_commit": task["base_commit"],
        "final_commit": COMMIT_B,
        "remote_branch": task["branch"],
        "changed_files": ["coordination/README.md"],
        "interfaces_changed": ["team-coordination-v1"],
        "decisions": ["使用板卡裸 Git 仓库"],
        "alternatives_rejected": ["普通文件复制不能处理并发"],
        "verification": [
            {"command": "pytest", "passed": True, "result": "全部通过"}
        ],
        "unverified": ["板卡当前离线"],
        "risks": ["板卡仍需异地备份"],
        "follow_ups": ["连接板卡后提取基线"],
        "board_deployment": {
            "status": "not_deployed",
            "release_id": "",
            "verified": False,
        },
        "rollback": "删除新增协作文件",
        "release_impact": "none",
        "age_4_6_result": "没有改变儿童体验，产品范围保持 4—6 岁",
        "completed_at": "2026-08-01T13:00:00+08:00",
    }


def test_valid_task_passes_strict_schema() -> None:
    assert coordination.validate_task(valid_task()) == []


def test_task_requires_complete_age_impact() -> None:
    task = valid_task()
    task["age_4_6_impact"]["verification_case"] = ""

    errors = coordination.validate_task(task)

    assert any("verification_case" in error for error in errors)


def test_task_branch_is_derived_from_device_and_task_id() -> None:
    task = valid_task()
    task["branch"] = "codex/wrong"

    errors = coordination.validate_task(task)

    assert any("branch 必须为" in error for error in errors)


def test_conflict_detection_covers_files_and_interfaces() -> None:
    first = valid_task()
    second = valid_task()
    second["task_id"] = "XB-20260801-002"
    second["branch"] = "codex/device-b/XB-20260801-002"
    second["owner_device"] = "device-b"

    errors = coordination.conflict_errors(second, [first])

    assert any("冲突文件" in error for error in errors)
    assert any("冲突接口" in error for error in errors)


def test_handoff_requires_passed_verification() -> None:
    task = valid_task()
    handoff = valid_handoff(task)
    handoff["verification"][0]["passed"] = False

    errors = coordination.validate_handoff(handoff, task)

    assert any("必须明确通过" in error for error in errors)


def test_valid_handoff_passes_schema() -> None:
    task = valid_task()
    assert coordination.validate_handoff(valid_handoff(task), task) == []


def test_doctor_blocks_unverified_baseline_and_dirty_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path
    state_dir = root / "coordination" / "state"
    state_dir.mkdir(parents=True)
    (root / "coordination" / "PROTOCOL_VERSION").write_text(
        coordination.PROTOCOL_VERSION + "\n",
        encoding="utf-8",
    )
    (state_dir / "current-state.json").write_text(
        """{
          "protocol_version": "1.0.0",
          "baseline": {"status": "pending_board_audit"},
          "sync": {"offsite_backup_configured": false}
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        coordination,
        "git_observation",
        lambda _repo: {
            "branch": "main",
            "head": COMMIT_A,
            "dirty": True,
            "changed_path_count": 4,
            "board_remote_configured": False,
        },
    )

    report = coordination.doctor(root, "device-a", check_remote=False)

    assert report["ready"] is False
    assert any("基线尚未验证" in item for item in report["blockers"])
    assert any("未提交变化" in item for item in report["blockers"])
    assert any("board" in item for item in report["blockers"])


def test_render_state_exposes_board_and_gate() -> None:
    rendered = coordination.render_state(
        {
            "protocol_version": "1.0.0",
            "development_gate": "blocked_pending_board_baseline",
            "generated_at": "2026-08-01T12:00:00+08:00",
            "baseline": {
                "authority": "sc171v3_competition_runtime",
                "status": "pending_board_audit",
                "source_commit": "",
            },
            "board": {
                "host": None,
                "address_policy": "dynamic_per_network",
                "identity_verified": False,
            },
            "release": {"release_id": ""},
            "sync": {"fully_synced": False},
            "local_observation": {
                "branch": "main",
                "head": COMMIT_A,
                "dirty": True,
                "changed_path_count": 2,
                "board_remote_configured": False,
            },
            "active_tasks": [],
        }
    )

    assert "动态获取（换网络后重新确认）" in rendered
    assert "dynamic_per_network" in rendered
    assert "blocked_pending_board_baseline" in rendered
    assert "pending_board_audit" in rendered


def test_resolve_baseline_commit_falls_back_to_immutable_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run_git(_repo: Path, *args: str, **_kwargs: object) -> str:
        calls.append(args)
        return COMMIT_A

    monkeypatch.setattr(coordination, "run_git", fake_run_git)

    result = coordination.resolve_baseline_commit(
        tmp_path,
        {"source_commit": "", "tag": "board-competition-baseline-20260801"},
    )

    assert result == COMMIT_A
    assert calls == [
        (
            "rev-parse",
            "--verify",
            "refs/tags/board-competition-baseline-20260801^{commit}",
        )
    ]
