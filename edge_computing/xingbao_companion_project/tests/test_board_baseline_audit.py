from __future__ import annotations

from pathlib import Path

import pytest

from tools import board_baseline_audit as audit


def test_probe_reports_ports_without_claiming_file_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "probe_port", lambda _host, port: port == 22)

    result = audit.probe("board-on-current-network")

    assert result["ports"] == {"ssh_22": True, "adb_5555": False}
    assert result["board_files_read"] is False
    assert result["board_files_modified"] is False


def test_parser_does_not_hardcode_board_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XINGBAO_BOARD_HOST", raising=False)

    args = audit.parser().parse_args(["probe"])

    assert args.host == ""


def test_parser_accepts_board_address_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XINGBAO_BOARD_HOST", "board-on-current-network")

    args = audit.parser().parse_args(["probe"])

    assert args.host == "board-on-current-network"


def test_manifest_validation_rejects_sensitive_runtime_files() -> None:
    data = {
        "schema_version": 1,
        "files": [
            {
                "path": "data/memory.json",
                "size": 10,
                "sha256": "a" * 64,
            }
        ],
    }

    errors = audit.validate_manifest(data)

    assert any("禁止路径" in error for error in errors)


def test_manifest_validation_accepts_source_files() -> None:
    data = {
        "schema_version": 1,
        "files": [
            {
                "path": "core/session.py",
                "size": 10,
                "sha256": "a" * 64,
            }
        ],
    }

    assert audit.validate_manifest(data) == []


def test_manifest_refuses_when_ssh_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "probe_port", lambda _host, _port: False)

    with pytest.raises(audit.AuditError, match="没有读取或修改板卡文件"):
        audit.capture_manifest(
            host="board-on-current-network",
            user="fibo",
            roots=["/opt/xingbao"],
            output=tmp_path / "manifest.json",
        )

    assert not (tmp_path / "manifest.json").exists()
