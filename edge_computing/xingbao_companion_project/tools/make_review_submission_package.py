"""Create the review submission code package for Xingbao SC171V3."""

from __future__ import annotations

import json
import shutil
import struct
from binascii import crc32
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE = PROJECT_ROOT / "work" / "review_submission" / "xingbao_sc171v3"
OUTPUT_RAR = PROJECT_ROOT / "dist" / "xingbao_sc171v3_review_submission_20260709.rar"

TOP_LEVEL_FILES = [
    ".env.example",
    "app.py",
    "main.py",
    "requirements.txt",
    "requirements-wake-word.txt",
]

CODE_DIRS = [
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

LEGACY_DOCS_UNUSED = {
    "docs/README.md": """# 星宝 SC171V3 智能儿童早教陪伴桌

本代码包为评审提交版，聚焦系统重点代码与可验证运行入口。

星宝面向学龄前儿童早教陪伴场景，基于 SC171V3 平台，将语音交互、触控屏互动、桌面小游戏、儿童友好表达、健康提醒和白宝箱儿童可视化小工具整合为一个模块化系统。

## 核心能力

- 语音链路：唤醒、录音、VAD、ASR、LLM、TTS。
- 触控桌面：通过板卡 UI 协议打开游戏中心或指定工具。
- 学习工具：迁移白宝箱 85 个儿童可视化小工具。
- 事件调度：统一处理语音、触控、小游戏和视觉状态事件。
- 儿童安全：敏感信息过滤、动作白名单、高层动作语义输出。

## 主要入口

```bash
python3 main.py --help
python3 main.py --wake-chat --board-ui --game-speech
python3 main.py --kids-visual-tools
python3 main.py --kids-visual-tool draw
python3 tools/board_health_check.py
```

## 运行边界

本包按“重点代码 100MB 以内”要求整理，不包含离线唤醒词大模型、完整高清素材库、Python 虚拟环境和板卡系统镜像。实际整机运行时需要按部署说明补齐模型资源、安装依赖，并启动触控主界面服务。
""",
    "docs/TECHNICAL_ALIGNMENT.md": """# 技术文档对照说明

本提交包内容按技术文档中的系统结构整理。

| 技术文档模块 | 代码位置 | 说明 |
| --- | --- | --- |
| 主控平台与应用入口 | `main.py`, `app.py` | 负责系统启动、参数解析、语音会话和多模块调度。 |
| 配置与角色设定 | `config/`, `core/settings.py` | 运行参数、角色配置、语音配置、动作 schema 和白宝箱注册表。 |
| 语音输入输出 | `multimodal/` | ASR、TTS、VAD、音频播放、唤醒词检测。 |
| 智能对话 | `intelligence/` | Prompt 构建、LLM 客户端、非敏感画像提取。 |
| 统一事件与协调 | `core/coordinator.py`, `core/state_inputs.py`, `core/expression.py` | 将语音、触控、小游戏和视觉状态转换为统一响应计划。 |
| 触控主界面对接 | `core/board_ui_client.py` | 通过 `assistant_output` 和 `ui_command` 对接板卡主界面。 |
| 学习小游戏 | `core/color_block_*`, `web/color_block_game.html` | 色块桌面游戏规则、事件、语音命令和网页原型。 |
| 白宝箱工具箱 | `web/kids_visual_tools/`, `core/kids_visual_tools_bridge.py` | 85 个儿童小工具及中枢跳转桥接。 |
| 动作安全边界 | `core/action_safety.py`, `core/arm_action_bridge.py`, `core/serial_bridge.py` | 仅输出高层动作语义，避免底层硬件指令暴露给模型。 |
| 上板部署 | `deploy/`, `tools/board_health_check.py` | 依赖安装、运行启动、健康检查。 |

包内仅保留重点代码和必要轻量资源；大型过程资料、测试缓存、历史构建产物和完整大图素材未纳入。
""",
    "docs/DEPLOYMENT_GUIDE.md": """# 部署与运行说明

## 安装依赖

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-wake-word.txt
```

如在板卡运行，可先执行：

```bash
sh deploy/board_install_deps.sh
```

## 运行前配置

云端语音和大模型服务密钥从环境变量读取：

```bash
export DASHSCOPE_API_KEY="your_key_here"
```

## 常用启动

```bash
python3 tools/board_health_check.py
python3 main.py --wake-chat --board-ui --game-speech
python3 main.py --kids-visual-tools
python3 main.py --kids-visual-tool draw
```

板卡运行脚本：

```bash
sh deploy/board_start_runtime.sh
sh deploy/board_start_visual_tools.sh
```

## 外部资源说明

- 离线唤醒词模型需放置在 `models/` 目录下，模型体积较大，未纳入 100MB 以内的重点代码包。
- 触控主界面桥接需要板卡 UI 服务在本机端口监听；单独解压代码包时该检查可能显示未连接。
- 真实语音识别、对话和合成需要有效的 `DASHSCOPE_API_KEY`、网络环境、麦克风和扬声器。
- 白宝箱工具箱保留工具注册表、运行代码和轻量预览资源；完整高清素材库可作为资源包另行部署。
""",
    "docs/INTERFACE_SUMMARY.md": """# 接口摘要

## 中枢到触控主界面

中枢通过本机 TCP 向触控主界面发送 `assistant_output` 消息，主要字段为：

```json
{
  "type": "assistant_output",
  "source": "central_controller",
  "target": "desktop_ui",
  "payload": {
    "screen_expression": {"name": "smile", "duration_ms": 4000},
    "screen_text": "准备打开工具",
    "led": {"mode": "warm_breath", "duration_ms": 4000},
    "ui_command": {"name": "open_visual_tools", "params": {}}
  }
}
```

常用 `ui_command`：

- `open_game_center`
- `start_game`
- `return_to_desktop`
- `open_visual_tools`
- `launch_visual_tool`

## 游戏/界面到中枢语音服务

触控游戏可通过 `speech_request` 请求中枢播报：

```json
{
  "type": "speech_request",
  "source": "game_ui",
  "payload": {
    "text": "请找到红色方块",
    "request_tts": true
  }
}
```
""",
}

EXCLUDED_NAMES = {".git", ".pytest_cache", ".venv", "__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".rar", ".zip", ".tar", ".gz", ".7z"}

SENSITIVE_SCAN_TOKENS = [
    "大学",
    "学院",
    "中学",
    "小学",
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

FILENAME_ONLY_SCAN_TOKENS = [
    "demo",
    "patch",
]

DOCS = {
    "docs/README.md": """# 星宝 SC171V3 智能儿童早教陪伴桌

本代码包为评审提交版，聚焦系统重点代码与可验证运行入口。

星宝面向学龄前儿童早教陪伴场景，基于 SC171V3 平台，将语音交互、触控屏互动、桌面小游戏、儿童友好表达、健康提醒和白宝箱儿童可视化小工具整合为一个模块化系统。

## 核心能力

- 语音链路：唤醒、录音、VAD、ASR、LLM、TTS。
- 触控桌面：通过板卡 UI 协议打开游戏中心或指定工具。
- 学习工具：迁移白宝箱 85 个儿童可视化小工具。
- 事件调度：统一处理语音、触控、小游戏和视觉状态事件。
- 儿童安全：敏感信息过滤、动作白名单、高层动作语义输出。

## 主要入口

```bash
python3 main.py --help
python3 main.py --wake-chat --board-ui --game-speech
python3 main.py --kids-visual-tools
python3 main.py --kids-visual-tool draw
python3 tools/board_health_check.py
```
""",
    "docs/TECHNICAL_ALIGNMENT.md": """# 技术文档对照说明

本提交包内容按技术文档中的系统结构整理。

| 技术文档模块 | 代码位置 | 说明 |
| --- | --- | --- |
| 主控平台与应用入口 | `main.py`, `app.py` | 负责系统启动、参数解析、语音会话和多模块调度。 |
| 配置与角色设定 | `config/`, `core/settings.py` | 运行参数、角色配置、语音配置、动作 schema 和白宝箱注册表。 |
| 语音输入输出 | `multimodal/` | ASR、TTS、VAD、音频播放、唤醒词检测。 |
| 智能对话 | `intelligence/` | Prompt 构建、LLM 客户端、非敏感画像提取。 |
| 统一事件与协调 | `core/coordinator.py`, `core/state_inputs.py`, `core/expression.py` | 将语音、触控、小游戏和视觉状态转换为统一响应计划。 |
| 触控主界面对接 | `core/board_ui_client.py` | 通过 `assistant_output` 和 `ui_command` 对接板卡主界面。 |
| 学习小游戏 | `core/color_block_*`, `web/color_block_game.html` | 色块桌面游戏规则、事件、语音命令和网页原型。 |
| 白宝箱工具箱 | `web/kids_visual_tools/`, `core/kids_visual_tools_bridge.py` | 85 个儿童小工具及中枢跳转桥接。 |
| 动作安全边界 | `core/action_safety.py`, `core/arm_action_bridge.py`, `core/serial_bridge.py` | 仅输出高层动作语义，避免底层硬件指令暴露给模型。 |
| 上板部署 | `deploy/`, `tools/board_health_check.py` | 依赖安装、运行启动、健康检查。 |

包内仅保留重点代码和必要轻量资源；大型过程资料、测试缓存、历史构建产物和完整大图素材未纳入。
""",
    "docs/DEPLOYMENT_GUIDE.md": """# 部署与运行说明

## 安装依赖

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-wake-word.txt
```

如在板卡运行，可先执行：

```bash
sh deploy/board_install_deps.sh
```

## 运行前配置

云端语音和大模型服务密钥从环境变量读取：

```bash
export DASHSCOPE_API_KEY="your_key_here"
```

## 常用启动

```bash
python3 tools/board_health_check.py
python3 main.py --wake-chat --board-ui --game-speech
python3 main.py --kids-visual-tools
python3 main.py --kids-visual-tool draw
```

板卡运行脚本：

```bash
sh deploy/board_start_runtime.sh
sh deploy/board_start_visual_tools.sh
```
""",
    "docs/INTERFACE_SUMMARY.md": """# 接口摘要

## 中枢到触控主界面

中枢通过本机 TCP 向触控主界面发送 `assistant_output` 消息，主要字段为：

```json
{
  "type": "assistant_output",
  "source": "central_controller",
  "target": "desktop_ui",
  "payload": {
    "screen_expression": {"name": "smile", "duration_ms": 4000},
    "screen_text": "准备打开工具",
    "led": {"mode": "warm_breath", "duration_ms": 4000},
    "ui_command": {"name": "open_visual_tools", "params": {}}
  }
}
```

常用 `ui_command`：

- `open_game_center`
- `start_game`
- `return_to_desktop`
- `open_visual_tools`
- `launch_visual_tool`

## 游戏/界面到中枢语音服务

触控游戏可通过 `speech_request` 请求中枢播报：

```json
{
  "type": "speech_request",
  "source": "game_ui",
  "payload": {
    "text": "请找到红色方块",
    "request_tts": true
  }
}
```
""",
}

SENSITIVE_SCAN_TOKENS = [
    "大学",
    "学院",
    "中学",
    "小学",
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

EXCLUDED_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "board_start_demo.sh",
    "board_start_full_demo.sh",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".rar", ".zip", ".tar", ".gz", ".7z"}


DOCS = {
    "docs/README.md": """# 星宝 SC171V3 智能儿童早教陪伴桌

本代码包为评审提交版，重点展示星宝智能儿童早教陪伴桌的核心实现代码、模块结构和可对照运行入口。

星宝面向学龄前儿童早教陪伴场景，基于 SC171V3 平台，融合语音交互、触控屏互动、桌面小游戏、儿童友好表达、白宝箱可视化学习工具、健康提醒和多模态状态协同，形成一个“能听、能说、能看、能陪孩子游戏化学习”的智能陪伴桌系统。

## 包内重点内容

- `main.py`、`app.py`：系统主入口，负责参数解析、会话流程、功能调度。
- `core/`：事件协调、触控主界面对接、动作安全、小游戏桥接、白宝箱跳转。
- `intelligence/`：对话提示词、LLM 客户端、儿童画像和非敏感记忆。
- `multimodal/`：ASR、TTS、VAD、音频播放、唤醒词相关链路。
- `web/`：触控小游戏页面和白宝箱儿童可视化工具。
- `config/`：角色设定、运行配置、动作 schema、白宝箱工具注册表。
- `deploy/`：面向板卡部署的安装与启动脚本。
- `docs/`：评审阅读说明、技术文档对照、接口摘要和部署说明。

## 评审建议阅读顺序

1. 阅读 `docs/TECHNICAL_ALIGNMENT.md`，对照技术文档理解模块关系。
2. 阅读 `docs/INTERFACE_SUMMARY.md`，查看主控、触控界面、小游戏、语音服务之间的接口。
3. 查看 `core/coordinator.py`、`core/board_ui_client.py`、`core/kids_visual_tools_bridge.py`，理解核心调度和跳转逻辑。
4. 查看 `main.py --help` 对应的入口，确认语音、触控、小游戏和白宝箱功能均有正式入口。

## 代码包边界

本包按“上传重点代码 100MB 以内”的要求整理，因此不包含 Python 虚拟环境、完整高清素材库、离线唤醒词大模型、历史构建产物和测试缓存。这些属于运行资源或过程文件，不影响评审对核心实现代码的阅读。
""",
    "docs/TECHNICAL_ALIGNMENT.md": """# 技术文档对照说明

本提交包按技术文档中的系统设计目标整理，覆盖星宝智能儿童早教陪伴桌的主要软件功能链路。

| 技术文档内容 | 包内代码位置 | 对应实现 |
| --- | --- | --- |
| SC171V3 主控应用 | `main.py`, `app.py` | 提供系统启动入口、命令行参数、语音会话、工具调度和板卡侧运行入口。 |
| 语音交互 | `multimodal/`, `app.py` | 包含录音、VAD、ASR、LLM 响应、TTS 播放、唤醒词相关流程。 |
| 儿童友好智能体 | `intelligence/`, `config/character.json` | 构建儿童陪伴口吻、学习引导、情绪支持和非敏感记忆。 |
| 触控主界面对接 | `core/board_ui_client.py`, `core/coordinator.py` | 将中枢响应转换为 `assistant_output` 和 `ui_command`，用于主界面跳转。 |
| 桌面小游戏 | `core/color_block_*`, `web/color_block_game.html` | 实现色块认知小游戏、语音命令解析、触控页面和协同事件。 |
| 白宝箱工具迁移 | `web/kids_visual_tools/`, `core/kids_visual_tools_bridge.py`, `config/kids_visual_tools_registry.json` | 集成 85 个儿童可视化学习工具，支持列表、检索、指定工具跳转。 |
| 多模态状态协同 | `core/state_inputs.py`, `core/expression.py`, `core/coordinator.py` | 统一处理语音、触控、小游戏、视觉状态，生成表情、播报、灯效和工具动作。 |
| 健康与成长引导 | `config/growth_guidance_rules.json`, `core/growth_guidance.py` | 支持学习节奏、鼓励反馈、眼健康和成长提醒类策略。 |
| 安全边界 | `core/action_safety.py`, `core/arm_action_bridge.py`, `core/serial_bridge.py` | 仅保留高层动作语义和白名单过滤，避免底层硬件指令直接暴露给模型。 |
| 板卡部署准备 | `deploy/`, `tools/board_health_check.py` | 提供依赖安装、运行启动、白宝箱启动和健康检查脚本。 |

因此，这份代码包不是简单演示文件，而是围绕技术文档目标整理出的主线工程代码。评审可通过模块结构和入口命令看到完整功能设计和实现路径。
""",
    "docs/INTERFACE_SUMMARY.md": """# 接口摘要

## 中枢到触控主界面

中枢通过 `core/board_ui_client.py` 向触控主界面发送结构化消息。典型消息如下：

```json
{
  "type": "assistant_output",
  "source": "central_controller",
  "target": "desktop_ui",
  "payload": {
    "screen_expression": {"name": "smile", "duration_ms": 4000},
    "screen_text": "准备打开工具",
    "led": {"mode": "warm_breath", "duration_ms": 4000},
    "ui_command": {"name": "launch_visual_tool", "params": {"slug": "draw"}}
  }
}
```

常用 `ui_command`：

- `open_game_center`
- `start_game`
- `return_to_desktop`
- `open_visual_tools`
- `launch_visual_tool`

## 语音到工具跳转

`core/intent_router.py` 会识别儿童语音意图。例如“打开画画工具”会路由为：

```text
kids_visual_tools:draw
```

随后由 `core/kids_visual_tools_bridge.py` 生成白宝箱工具跳转请求，再交给板卡主界面执行。

## 游戏到中枢语音服务

触控小游戏可发送 `speech_request`，请求中枢播报提示语：

```json
{
  "type": "speech_request",
  "source": "game_ui",
  "payload": {
    "text": "请找到红色方块",
    "request_tts": true
  }
}
```

这样可以让小游戏、屏幕反馈和语音陪伴保持统一节奏。
""",
    "docs/DEPLOYMENT_GUIDE.md": """# 部署与运行说明

## 安装依赖

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-wake-word.txt
```

板卡部署可参考：

```bash
sh deploy/board_install_deps.sh
sh deploy/board_start_runtime.sh
sh deploy/board_start_visual_tools.sh
```

## 常用入口

```bash
python3 main.py --help
python3 main.py --list-kids-visual-tools
python3 main.py --kids-visual-tools
python3 main.py --kids-visual-tool draw
python3 main.py --coordinate-text "打开画画工具"
python3 main.py --color-block-web
python3 tools/board_health_check.py
```

## 运行资源说明

真实整机运行需要配置 `DASHSCOPE_API_KEY`、麦克风、扬声器、板卡触控主界面服务和离线唤醒词模型。由于提交限制为重点代码 100MB 以内，模型文件、虚拟环境和完整高清素材库未放入本代码包。
""",
}

SENSITIVE_SCAN_TOKENS = [
    "大学",
    "学院",
    "中学",
    "小学",
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


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    OUTPUT_RAR.parent.mkdir(parents=True, exist_ok=True)

    for file_name in TOP_LEVEL_FILES:
        _copy_path(PROJECT_ROOT / file_name, STAGE / file_name)
    for dir_name in CODE_DIRS:
        _copy_tree(PROJECT_ROOT / dir_name, STAGE / dir_name)
    for file_name in TOOL_FILES + WEB_FILES:
        _copy_path(PROJECT_ROOT / file_name, STAGE / file_name)
    _copy_kids_visual_assets()
    _write_docs()
    _write_manifest()
    _assert_submission_clean()
    _create_store_rar(OUTPUT_RAR, STAGE, STAGE.parent)
    print(f"Created review submission package: {OUTPUT_RAR}")
    print(f"Size MB: {OUTPUT_RAR.stat().st_size / 1024 / 1024:.2f}")
    print(f"Files: {sum(1 for _ in STAGE.rglob('*') if _.is_file())}")


def _copy_path(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
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


def _skip_path(relative: Path, path: Path) -> bool:
    if any(part in EXCLUDED_NAMES for part in relative.parts):
        return True
    if path.is_file() and path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def _copy_kids_visual_assets() -> None:
    source = PROJECT_ROOT / "web" / "kids_visual_tools" / "assets" / "illustrations"
    target = STAGE / "web" / "kids_visual_tools" / "assets" / "illustrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob("*.png"):
        if path.name.endswith("_thumb.png") or path.name.endswith("_panel.png"):
            shutil.copy2(path, target / path.name)


def _write_docs() -> None:
    for relative, content in DOCS.items():
        path = STAGE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8-sig")


def _write_manifest() -> None:
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "package": OUTPUT_RAR.stem,
        "type": "review_submission_code",
        "platform": "SC171V3",
        "size_limit": "100MB",
        "contents": [
            "core application code",
            "voice and multimodal pipeline",
            "touch UI bridge",
            "kids visual tools core code",
            "compressed essential visual assets",
            "deployment scripts",
            "review documentation",
        ],
    }
    (STAGE / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _assert_submission_clean() -> None:
    hits: list[str] = []
    for path in STAGE.rglob("*"):
        relative = path.relative_to(STAGE).as_posix()
        for token in [*SENSITIVE_SCAN_TOKENS, *FILENAME_ONLY_SCAN_TOKENS]:
            if token.lower() in relative.lower():
                hits.append(f"{relative}: filename contains {token}")
        if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".txt", ".sh", ".ps1"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for token in SENSITIVE_SCAN_TOKENS:
                if token in text:
                    hits.append(f"{relative}: text contains {token}")
    if hits:
        raise RuntimeError("Submission package contains blocked terms:\n" + "\n".join(hits[:80]))


def _create_store_rar(output: Path, source_dir: Path, archive_root: Path) -> None:
    if output.exists():
        output.unlink()
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    with output.open("wb") as archive:
        archive.write(b"Rar!\x1a\x07\x00")
        _write_rar_block(archive, _rar_archive_header_body())
        for path in files:
            relative = path.relative_to(archive_root).as_posix().replace("/", "\\")
            name = relative.encode("ascii")
            size = path.stat().st_size
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


def _rar_file_header_body(*, name: bytes, size: int, file_crc: int, dos_time: int) -> bytes:
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
    archive.write(struct.pack("<H", crc32(body) & 0xFFFF))
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
