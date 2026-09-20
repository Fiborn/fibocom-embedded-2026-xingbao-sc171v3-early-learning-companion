"""Create a clean central-controller package for board deployment."""

from __future__ import annotations

import shutil
import sys
import zipfile
from hashlib import sha256
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from release_manifest import write_manifest

STAGE = PROJECT_ROOT / "work" / "package" / "xingbao_companion"
OUTPUT = PROJECT_ROOT / "dist" / "xingbao_companion_central.zip"
SHA256_OUTPUT = OUTPUT.with_suffix(".zip.sha256")

FILES = [
    ".env.example",
    "AGENTS.md",
    "app.py",
    "main.py",
    "pc5.py",
    "pytest.ini",
    "README.md",
    "requirements.txt",
    "requirements-vision.txt",
    "requirements-vision-board.txt",
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
    "vision_system",
    "web",
]

MODEL_FILES = [
    "models/vision/emotion-ferplus-8.onnx",
    "models/vision/yolo11n.pt",
]

EXCLUDED_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_RELATIVE_PATHS = {
    # Board-side emergency copies are intentionally retained in the recovery
    # snapshot, never promoted into another immutable release.
    "deploy/board_start_demo.sh.before-multiturn-20260726",
    # These are generated LaTeX build outputs, not runtime documentation.
    "docs/XINGBAO_RELATION_DIAGRAM_LATEX.aux",
    "docs/XINGBAO_RELATION_DIAGRAM_LATEX.log",
    "docs/XINGBAO_RELATION_DIAGRAM_LATEX.pdf",
}


def copy_release_file(source: Path, target: Path) -> None:
    """Copy a release file, normalizing executable shell scripts for Linux."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".sh":
        target.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        return
    shutil.copy2(source, target)


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    for file_name in FILES:
        source = PROJECT_ROOT / file_name
        if source.exists():
            target = STAGE / file_name
            copy_release_file(source, target)

    for dir_name in DIRS:
        source = PROJECT_ROOT / dir_name
        if not source.exists():
            continue
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            if any(part in EXCLUDED_NAMES for part in relative.parts):
                continue
            project_relative = (Path(dir_name) / relative).as_posix()
            if project_relative in EXCLUDED_RELATIVE_PATHS:
                continue
            target = STAGE / dir_name / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.suffix not in EXCLUDED_SUFFIXES:
                copy_release_file(path, target)

    for model_name in MODEL_FILES:
        source = PROJECT_ROOT / model_name
        if not source.is_file():
            raise FileNotFoundError(f"Required vision model is missing: {source}")
        target = STAGE / model_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for runtime_dir in ("data", "logs", "work/tmp"):
        (STAGE / runtime_dir).mkdir(parents=True, exist_ok=True)

    manifest_path = write_manifest(STAGE, project_root=PROJECT_ROOT)

    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in STAGE.rglob("*"):
            archive.write(path, path.relative_to(STAGE.parent))

    digest = sha256(OUTPUT.read_bytes()).hexdigest()
    # Write bytes so a Windows build still produces the LF-only sidecar that
    # Linux `sha256sum -c` requires on the board.
    SHA256_OUTPUT.write_bytes(f"{digest}  {OUTPUT.name}\n".encode("utf-8"))

    file_count = sum(1 for path in STAGE.rglob("*") if path.is_file())
    print(f"Created package: {OUTPUT}")
    print(f"SHA256 sidecar: {SHA256_OUTPUT}")
    print(f"Files: {file_count}")
    print(f"Release manifest: {manifest_path}")
    print("Upload target directory on board: /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion")
    print("Excluded: .env, .venv, work cache, logs content, local zip files.")


if __name__ == "__main__":
    main()
