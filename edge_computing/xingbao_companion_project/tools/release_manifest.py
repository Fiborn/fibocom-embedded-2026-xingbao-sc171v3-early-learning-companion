"""Create and verify an immutable Xingbao release manifest.

The manifest deliberately covers program files only.  Runtime data, logs,
cache files, API credentials, and child records remain outside a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_NAME = "RELEASE_MANIFEST.json"
SCHEMA_VERSION = 1
RUNTIME_DIRECTORY_NAMES = frozenset({"data", "logs", "work"})
INTERPRETER_CACHE_DIRECTORY_NAMES = frozenset({"__pycache__", ".pytest_cache"})
INTERPRETER_CACHE_SUFFIXES = frozenset({".pyc", ".pyo"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(project_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _release_id() -> str:
    explicit = os.environ.get("XINGBAO_RELEASE_ID", "").strip()
    if explicit:
        return explicit
    return "candidate-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _tracked_files(release_root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(release_root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        relative = path.relative_to(release_root).as_posix()
        parts = relative.split("/")
        if parts[0] in RUNTIME_DIRECTORY_NAMES:
            continue
        # Python can create bytecode after a valid release has started.  Those
        # generated files are not release content and must never make a
        # recovered board look like a corrupted release on its next boot.
        if any(part in INTERPRETER_CACHE_DIRECTORY_NAMES for part in parts):
            continue
        if path.suffix.lower() in INTERPRETER_CACHE_SUFFIXES:
            continue
        files[relative] = _sha256(path)
    return files


def build_manifest(release_root: Path, *, project_root: Path | None = None) -> dict[str, Any]:
    root = release_root.resolve()
    source_root = (project_root or root).resolve()
    # Generated archives and local recovery material are intentionally outside
    # the program source that this manifest attests to.  This prevents the
    # checksum sidecar itself from making an otherwise committed release look
    # like an unreviewed source change.
    dirty = _git_value(
        source_root,
        "status",
        "--porcelain",
        "--untracked-files=no",
        "--",
        ".",
        ":(exclude)dist",
        ":(exclude)work",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": _release_id(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": _git_value(source_root, "rev-parse", "HEAD"),
        "source_dirty_at_build": bool(dirty),
        "files": _tracked_files(root),
        "runtime_excluded": [".env", "data/", "logs/", "work/"],
    }


def write_manifest(release_root: Path, *, project_root: Path | None = None) -> Path:
    root = release_root.resolve()
    manifest_path = root / MANIFEST_NAME
    manifest = build_manifest(root, project_root=project_root)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def load_manifest(release_root: Path) -> dict[str, Any]:
    manifest_path = release_root / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported_release_manifest")
    if not isinstance(payload.get("release_id"), str) or not payload["release_id"].strip():
        raise ValueError("release_id_missing")
    if not isinstance(payload.get("files"), dict):
        raise ValueError("release_files_missing")
    return payload


def verify_manifest(release_root: Path) -> dict[str, Any]:
    root = release_root.resolve()
    manifest = load_manifest(root)
    mismatches: list[str] = []
    for relative, expected in manifest["files"].items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            mismatches.append(str(relative))
            continue
        path = root / relative
        if not path.is_file() or _sha256(path) != expected:
            mismatches.append(relative)
    if mismatches:
        raise ValueError("release_integrity_failed:" + ",".join(mismatches[:10]))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a Xingbao release manifest.")
    parser.add_argument("release_root", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--print-release-id", action="store_true")
    args = parser.parse_args()

    if args.create:
        path = write_manifest(args.release_root)
        print(path)
        return
    manifest = verify_manifest(args.release_root)
    if args.print_release_id:
        print(manifest["release_id"])
    else:
        print(f"release_manifest_ok={manifest['release_id']}")


if __name__ == "__main__":
    main()
