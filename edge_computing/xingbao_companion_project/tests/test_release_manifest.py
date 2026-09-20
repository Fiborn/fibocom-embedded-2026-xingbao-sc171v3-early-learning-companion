from __future__ import annotations

import json

import pytest

from tools.release_manifest import MANIFEST_NAME, verify_manifest, write_manifest


def test_manifest_verifies_and_detects_changed_program_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XINGBAO_RELEASE_ID", "stable-test-001")
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "memory.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-38.pyc").write_bytes(b"cache")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "state").write_text("cache\n", encoding="utf-8")

    manifest_path = write_manifest(tmp_path, project_root=tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["release_id"] == "stable-test-001"
    assert "main.py" in payload["files"]
    assert "data/memory.json" not in payload["files"]
    assert "__pycache__/main.cpython-38.pyc" not in payload["files"]
    assert ".pytest_cache/state" not in payload["files"]
    assert manifest_path.name == MANIFEST_NAME
    assert verify_manifest(tmp_path)["release_id"] == "stable-test-001"

    (tmp_path / "main.py").write_text("print('changed')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="release_integrity_failed:main.py"):
        verify_manifest(tmp_path)
