"""Create a full-UI review submission package under the 100 MB limit."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image

from make_review_submission_package import _create_store_rar


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE = PROJECT_ROOT / "work" / "full_ui_submission" / "xingbao_sc171v3_full_ui"
OUTPUT_RAR = PROJECT_ROOT / "dist" / "xingbao_sc171v3_full_ui_submission_20260709.rar"
TOUCH_UI_SOURCE = PROJECT_ROOT / "work" / "incoming" / "xingbao_touch_game_latest" / "xingbao_touch_game"

TOP_LEVEL_FILES = [
    ".env.example",
    "app.py",
    "main.py",
    "requirements.txt",
    "requirements-wake-word.txt",
]

MAIN_CODE_DIRS = [
    "config",
    "core",
    "deploy",
    "intelligence",
    "multimodal",
    "src",
]

TOOL_FILES = [
    "tools/board_health_check.py",
    "tools/game_speech_smoke.py",
]

WEB_FILES = [
    "web/color_block_game.html",
    "web/kids_visual_tools/__init__.py",
    "web/kids_visual_tools/kids_visual_tools.py",
    "web/kids_visual_tools/README.md",
]

TOUCH_UI_ROOT_FILES = [
    "main.py",
    "desktop.py",
    "README.md",
    "requirements.txt",
    "board_start.sh",
    "design-qa.md",
]

TOUCH_UI_DIRS = [
    "assets",
    "config",
    "docs",
    "examples",
    "integrations",
    "src",
    "tools",
]

EXCLUDED_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "logs",
    "saves",
    "screenshots",
    "dist",
    "audit",
    "assets_backup_before_text_assets",
    "README_ʹ��˵��.txt",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".rar",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".log",
}

TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".sh", ".ps1", ".html", ".css", ".js"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

SENSITIVE_SCAN_TOKENS = [
    "大学",
    "学院",
    "学校名称",
    "校名",
    "学号",
    "指导老师",
    "导师",
    "队伍名称",
    "团队成员",
    "联系电话",
    "联系地址",
    "身份证",
    "Codex",
    "ChatGPT",
    "OpenAI",
    "no_demo",
    "hotfix",
    "AGENTS.md",
]

DOCS = {
    "docs/README.md": """# 星宝 SC171V3 全 UI 评审提交代码包

本包为全 UI 版本，包含星宝主控代码、触控主界面显示工程、色块小游戏显示代码、白宝箱工具箱 UI 代码和压缩后的完整 UI 资源目录。

## 主要目录

- `main.py`, `app.py`：星宝主控入口。
- `core/`：语音、触控、游戏、白宝箱之间的中枢调度和板卡 UI 对接。
- `web/color_block_game.html`：网页形式的色块小游戏界面。
- `web/kids_visual_tools/`：白宝箱工具箱 UI 和 85 个工具资源。
- `ui/touch_main_interface/`：触控主界面与桌面游戏显示工程，来自主界面/游戏显示源码。
- `docs/TECHNICAL_ALIGNMENT.md`：与技术文档的模块对照。

## 体积说明

赛事要求代码包 100MB 以内，因此本包没有放入运行日志、历史存档、测试缓存、旧构建压缩包和截图留档。UI 图片资源保留完整文件名和目录结构，并进行了尺寸与压缩优化，用于评审查看和代码对应。
""",
    "docs/TECHNICAL_ALIGNMENT.md": """# 技术文档与 UI 代码对照

| 功能 | 代码位置 | 说明 |
| --- | --- | --- |
| 星宝主控与语音中枢 | `main.py`, `app.py`, `multimodal/`, `intelligence/` | 负责语音输入、对话生成、TTS 输出和儿童友好陪伴逻辑。 |
| 主界面通信与跳转 | `core/board_ui_client.py`, `core/coordinator.py`, `core/tool_registry.py` | 负责向触控主界面发送表情、文字、灯效和跳转命令。 |
| 触控主界面显示工程 | `ui/touch_main_interface/desktop.py`, `ui/touch_main_interface/src/`, `ui/touch_main_interface/assets/` | 包含主界面、游戏入口、状态卡片、按钮、面板和桌面显示素材。 |
| 色块小游戏 | `core/color_block_*`, `web/color_block_game.html`, `ui/touch_main_interface/src/games/` | 包含游戏规则、触控显示、反馈和语音协同逻辑。 |
| 白宝箱工具箱 | `web/kids_visual_tools/`, `config/kids_visual_tools_registry.json` | 包含 85 个儿童可视化工具、工具注册表和 UI 资源。 |
| 板卡部署准备 | `deploy/`, `ui/touch_main_interface/board_start.sh` | 提供主控和 UI 上板运行脚本。 |
""",
    "docs/UI_CONTENTS.md": """# UI 内容清单

本包包含三类 UI：

1. 触控主界面 UI：`ui/touch_main_interface/`
2. 色块小游戏 UI：`web/color_block_game.html` 和 `ui/touch_main_interface/src/games/`
3. 白宝箱工具 UI：`web/kids_visual_tools/`

为满足 100MB 限制，图片资源进行了压缩处理；源码、目录、文件名和资源引用结构保持可读。
""",
}


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    OUTPUT_RAR.parent.mkdir(parents=True, exist_ok=True)

    for file_name in TOP_LEVEL_FILES:
        _copy_path(PROJECT_ROOT / file_name, STAGE / file_name)
    for dir_name in MAIN_CODE_DIRS:
        _copy_tree(PROJECT_ROOT / dir_name, STAGE / dir_name)
    for file_name in TOOL_FILES + WEB_FILES:
        _copy_path(PROJECT_ROOT / file_name, STAGE / file_name)

    _copy_kids_visual_tools_full_ui()
    _copy_touch_main_interface()
    _write_docs()
    _write_manifest()
    _assert_submission_clean()
    _create_store_rar(OUTPUT_RAR, STAGE, STAGE.parent)

    size_mb = OUTPUT_RAR.stat().st_size / 1024 / 1024
    print(f"Created full UI submission package: {OUTPUT_RAR}")
    print(f"Size MB: {size_mb:.2f}")
    print(f"Files: {sum(1 for path in STAGE.rglob('*') if path.is_file())}")
    if size_mb >= 100:
        raise RuntimeError(f"Package is over 100 MB: {size_mb:.2f} MB")


def _copy_path(source: Path, target: Path) -> None:
    if not source.exists() or _skip_path(source.name, source):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in IMAGE_SUFFIXES:
        _copy_optimized_image(source, target)
    else:
        shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _skip_path(relative, path):
            continue
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            _copy_path(path, destination)


def _skip_path(relative: Path | str, path: Path) -> bool:
    parts = Path(relative).parts
    try:
        str(relative).encode("ascii")
    except UnicodeEncodeError:
        return True
    if any(part in EXCLUDED_NAMES for part in parts):
        return True
    if path.is_file() and path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def _copy_kids_visual_tools_full_ui() -> None:
    source = PROJECT_ROOT / "web" / "kids_visual_tools" / "assets" / "illustrations"
    target = STAGE / "web" / "kids_visual_tools" / "assets" / "illustrations"
    for path in source.glob("*"):
        if path.is_file():
            _copy_path(path, target / path.name)


def _copy_touch_main_interface() -> None:
    target_root = STAGE / "ui" / "touch_main_interface"
    for file_name in TOUCH_UI_ROOT_FILES:
        _copy_path(TOUCH_UI_SOURCE / file_name, target_root / file_name)
    for dir_name in TOUCH_UI_DIRS:
        _copy_tree(TOUCH_UI_SOURCE / dir_name, target_root / dir_name)


def _copy_optimized_image(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            image.load()
            image.thumbnail((720, 720), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA", "P"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            if source.suffix.lower() in {".jpg", ".jpeg"}:
                image.convert("RGB").save(target, format="JPEG", quality=72, optimize=True)
            else:
                if image.mode == "RGBA":
                    quantized = image.quantize(colors=192, method=Image.Quantize.FASTOCTREE)
                else:
                    quantized = image.convert("P", palette=Image.Palette.ADAPTIVE, colors=192)
                quantized.save(target, format="PNG", optimize=True)
    except Exception:
        shutil.copy2(source, target)


def _write_docs() -> None:
    for relative, content in DOCS.items():
        path = STAGE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8-sig")


def _write_manifest() -> None:
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "package": "xingbao_sc171v3_full_ui_submission_20260709",
        "type": "full_ui_review_submission",
        "platform": "SC171V3",
        "size_limit": "100MB",
        "contents": [
            "main controller code",
            "touch main interface UI source",
            "touch game display source",
            "white-box kids visual tools UI",
            "optimized UI visual assets",
            "board integration scripts",
        ],
    }
    (STAGE / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )


def _assert_submission_clean() -> None:
    hits: list[str] = []
    for path in STAGE.rglob("*"):
        relative = path.relative_to(STAGE).as_posix()
        for token in SENSITIVE_SCAN_TOKENS:
            if token.lower() in relative.lower():
                hits.append(f"{relative}: filename contains {token}")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in SENSITIVE_SCAN_TOKENS:
                if token in text:
                    hits.append(f"{relative}: text contains {token}")
    if hits:
        raise RuntimeError("Submission package contains blocked terms:\n" + "\n".join(hits[:80]))


if __name__ == "__main__":
    main()
