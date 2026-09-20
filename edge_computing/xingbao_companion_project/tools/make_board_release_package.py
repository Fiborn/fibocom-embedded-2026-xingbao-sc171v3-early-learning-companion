"""Create the board release package for Xingbao Companion."""

from __future__ import annotations

import json
import shutil
import subprocess
import struct
import zipfile
from binascii import crc32
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE = PROJECT_ROOT / "work" / "package_release" / "xingbao_companion"
OUTPUT_BASE = PROJECT_ROOT / "dist" / "xingbao_companion_sc171v3_release_20260709"
OUTPUT_ZIP = OUTPUT_BASE.with_suffix(".zip")
OUTPUT_RAR = OUTPUT_BASE.with_suffix(".rar")

FILES = [
    ".env.example",
    "app.py",
    "main.py",
    "pc5.py",
    "pytest.ini",
    "README.md",
    "requirements.txt",
    "requirements-wake-word.txt",
]

DIRS = [
    "config",
    "core",
    "deploy",
    "docs",
    "examples",
    "intelligence",
    "multimodal",
    "src",
    "tests",
    "tools",
    "web",
]

EXCLUDED_NAMES = {".git", ".pytest_cache", ".venv", "__pycache__"}
EXCLUDED_SUFFIXES = {
    ".7z",
    ".gz",
    ".pyo",
    ".pyc",
    ".rar",
    ".tar",
    ".zip",
}
EXCLUDED_RELATIVE_PATHS = {
    "deploy/board_start_demo.sh",
    "deploy/board_start_full_demo.sh",
    "docs/BOARD_UI_DEMO_RUNBOOK.md",
    "docs/DEMO_FAST_RUNBOOK_20260704.md",
    "docs/DEMO_FLOW_SCRIPT.md",
    "tools/demo_stage_runner.py",
    "tools/enter_demo_flow.py",
    "tools/install_touch_game_demo_patch.py",
    "tools/make_board_release_package.py",
}


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    OUTPUT_BASE.parent.mkdir(parents=True, exist_ok=True)

    copied_files = 0
    for file_name in FILES:
        source = PROJECT_ROOT / file_name
        if source.exists():
            copied_files += _copy_file(source, STAGE / file_name)

    for dir_name in DIRS:
        source = PROJECT_ROOT / dir_name
        if not source.exists():
            continue
        for path in source.rglob("*"):
            project_relative = path.relative_to(PROJECT_ROOT)
            if _skip_path(project_relative, path):
                continue
            target = STAGE / project_relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                copied_files += _copy_file(path, target)

    for runtime_dir in ("data", "logs", "work/tmp"):
        (STAGE / runtime_dir).mkdir(parents=True, exist_ok=True)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "package": OUTPUT_BASE.name,
        "release_type": "board_runtime",
        "platform": "SC171V3",
        "board_target": "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion",
        "entrypoints": [
            "main.py",
            "deploy/board_start_runtime.sh",
            "deploy/board_start_visual_tools.sh",
        ],
        "components": [
            "voice_companion_core",
            "touch_ui_bridge",
            "kids_visual_tools",
            "audio_pipeline",
            "board_deployment_scripts",
        ],
        "notes": [
            "发布包不包含本地环境、缓存、构建产物和临时开发文件。",
            "白宝箱儿童可视化小工具位于 web/kids_visual_tools。",
        ],
    }
    (STAGE / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    copied_files += 1

    _create_zip()
    rar_created, rar_mode = _create_rar_if_possible()

    print(f"Created staging directory: {STAGE}")
    print(f"Created ZIP package: {OUTPUT_ZIP}")
    if rar_created:
        print(f"Created RAR package: {OUTPUT_RAR} ({rar_mode})")
    else:
        print("RAR tool not found; install WinRAR/Rar.exe and rerun this script to create .rar.")
    print(f"Files staged: {copied_files}")


def _copy_file(source: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return 1


def _skip_path(project_relative: Path, path: Path) -> bool:
    if any(part in EXCLUDED_NAMES for part in project_relative.parts):
        return True
    if path.is_file() and path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    normalized = project_relative.as_posix()
    if normalized in EXCLUDED_RELATIVE_PATHS:
        return True
    if project_relative.parts and project_relative.parts[0] in {"dist", "work"}:
        return True
    return False


def _create_zip() -> None:
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()
    with zipfile.ZipFile(
        OUTPUT_ZIP,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in STAGE.rglob("*"):
            archive.write(path, path.relative_to(STAGE.parent))


def _create_rar_if_possible() -> tuple[bool, str]:
    rar_tool = _find_rar_tool()
    if OUTPUT_RAR.exists():
        OUTPUT_RAR.unlink()
    if rar_tool is None:
        _create_store_rar(OUTPUT_RAR, STAGE, STAGE.parent)
        return OUTPUT_RAR.exists(), "rar4 store"
    command = [str(rar_tool), "a", "-r", "-ep1", str(OUTPUT_RAR), str(STAGE)]
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    return completed.returncode == 0 and OUTPUT_RAR.exists(), "external rar tool"


def _find_rar_tool() -> Path | None:
    for name in ("rar", "Rar.exe", "WinRAR.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in (
        Path("C:/Program Files/WinRAR/Rar.exe"),
        Path("C:/Program Files/WinRAR/WinRAR.exe"),
        Path("C:/Program Files (x86)/WinRAR/Rar.exe"),
        Path("C:/Program Files (x86)/WinRAR/WinRAR.exe"),
    ):
        if candidate.exists():
            return candidate
    return None


def _create_store_rar(output: Path, source_dir: Path, archive_root: Path) -> None:
    """Create a RAR4 archive using the uncompressed store method.

    This is intentionally small and conservative: it writes standard RAR 4.x
    marker/archive/file/end headers and stores file bytes without using RAR's
    proprietary compression algorithm.
    """
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    with output.open("wb") as archive:
        archive.write(b"Rar!\x1a\x07\x00")
        _write_rar_block(archive, _rar_archive_header_body())
        for path in files:
            relative = path.relative_to(archive_root).as_posix().replace("/", "\\")
            name = relative.encode("ascii")
            size = path.stat().st_size
            if size > 0xFFFFFFFF:
                raise ValueError(f"RAR4 fallback does not support files over 4GB: {path}")
            file_crc = _crc32_file(path)
            dos_time = _dos_time(path.stat().st_mtime)
            body = _rar_file_header_body(
                name=name,
                size=size,
                file_crc=file_crc,
                dos_time=dos_time,
            )
            _write_rar_block(archive, body)
            with path.open("rb") as source:
                shutil.copyfileobj(source, archive, length=1024 * 1024)
        _write_rar_block(archive, _rar_end_header_body())


def _rar_archive_header_body() -> bytes:
    return struct.pack("<BHHHL", 0x73, 0, 13, 0, 0)


def _rar_file_header_body(
    *,
    name: bytes,
    size: int,
    file_crc: int,
    dos_time: int,
) -> bytes:
    head_size = 32 + len(name)
    return (
        struct.pack(
            "<BHHLLBLLBBHL",
            0x74,
            0,
            head_size,
            size,
            size,
            2,
            file_crc,
            dos_time,
            20,
            0x30,
            len(name),
            0x20,
        )
        + name
    )


def _rar_end_header_body() -> bytes:
    return struct.pack("<BHH", 0x7B, 0, 7)


def _write_rar_block(archive, body: bytes) -> None:
    header_crc = crc32(body) & 0xFFFF
    archive.write(struct.pack("<H", header_crc))
    archive.write(body)


def _crc32_file(path: Path) -> int:
    value = 0
    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            value = crc32(chunk, value)
    return value & 0xFFFFFFFF


def _dos_time(timestamp: float) -> int:
    dt = datetime.fromtimestamp(timestamp)
    year = max(1980, min(2107, dt.year))
    return (
        ((year - 1980) << 25)
        | (dt.month << 21)
        | (dt.day << 16)
        | (dt.hour << 11)
        | (dt.minute << 5)
        | (dt.second // 2)
    )


if __name__ == "__main__":
    main()
