"""Build a clean, checksum-protected touch-game package from a frozen source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path


EXCLUDED_DIRECTORY_NAMES = frozenset(
    {".git", ".pytest_cache", "__pycache__", "logs", "saves", "work", "dist"}
)
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})
MANIFEST_NAME = "TOUCH_RELEASE_MANIFEST.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_release_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name == MANIFEST_NAME:
            continue
        files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="frozen touch-game source directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/xingbao_touch_game_board.zip"),
        help="destination zip package",
    )
    parser.add_argument(
        "--release-id",
        default=os.environ.get("XINGBAO_RELEASE_ID", "").strip(),
        help="release identifier recorded inside the package",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    release_id = args.release_id or "candidate-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for required in (source / "desktop.py", source / "src" / "app.py"):
        if not required.is_file():
            raise FileNotFoundError(f"required touch source file is missing: {required}")

    files = iter_release_files(source)
    file_hashes = {path.relative_to(source).as_posix(): sha256_file(path) for path in files}
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_excluded": ["logs/", "saves/", "work/"],
        "files": file_hashes,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(source).as_posix())
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    with zipfile.ZipFile(output) as archive:
        bad_file = archive.testzip()
    if bad_file:
        raise ValueError(f"zip_crc_error:{bad_file}")

    sidecar = output.with_suffix(output.suffix + ".sha256")
    # Keep this portable: a Windows text-mode write would otherwise add CRLF
    # and make Linux `sha256sum -c` treat the filename as ending in `\\r`.
    sidecar.write_bytes(f"{sha256_file(output)}  {output.name}\n".encode("utf-8"))
    print(f"Created package: {output}")
    print(f"SHA256 sidecar: {sidecar}")
    print(f"Files: {len(files)}")
    print(f"Release ID: {release_id}")


if __name__ == "__main__":
    main()
