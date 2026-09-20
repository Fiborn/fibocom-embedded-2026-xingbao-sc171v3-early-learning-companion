#!/usr/bin/env python3
"""Run the reviewed Xingbao presentation flow without network or arm motion.

The central and touch phases run in separate Python processes because both
projects contain a package named ``src``.  This runner exercises the real
conversation state machine, desktop persistence, touch-game logic, memory
book adapters, and parent gate.  It records the high-level ``high_five``
request but never connects to the physical arm service.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOUCH_ROOT = Path(
    os.environ.get(
        "XINGBAO_TOUCH_ROOT",
        str(
            PROJECT_ROOT
            / "work"
            / "incoming"
            / "xingbao_touch_game_latest"
            / "xingbao_touch_game"
        ),
    )
).expanduser().resolve()


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _line(prefix: str, text: str) -> None:
    print(f"{prefix} {text}", flush=True)


def _record_guided_turn(app: Any, child_text: str, reply: Any) -> None:
    store = app.session.conversation_history_store
    if reply is not None and store is not None:
        store.append_turn(child_text=child_text, xingbao_text=reply.text)


def run_central_phase(artifact_dir: Path) -> dict[str, Any]:
    """Exercise the actual guided-expression and safe-memory modules."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from app import XingbaoApp
    from core.memory import MemoryManager
    from core.session import SessionManager

    data_dir = artifact_dir / "data"
    session = SessionManager(memory_manager=MemoryManager(data_dir / "memory.json"))
    app = XingbaoApp(session=session)

    def child(step: int, text: str, *, expect_reply: bool = True) -> Any:
        _line(f"[中央 {step:02d}]", f"小宇：{text}")
        reply = app.handle_guided_expression_text(text)
        if expect_reply:
            _require(reply is not None, f"中央步骤 {step} 没有生成引导回复")
            _line(f"[中央 {step:02d}]", f"星宝：{reply.text}")
            _record_guided_turn(app, text, reply)
        else:
            _require(reply is None, f"中央步骤 {step} 错误拦截了正常功能")
            _line(
                f"[中央 {step:02d}]",
                "结果：交还原有功能处理，未完成的恐龙流程仍然保留。",
            )
        return reply

    _line("[中央 00]", "唤醒词“星宝星宝”已作为一次有效语音会话入口。")
    opening = child(1, "我叫小宇，我喜欢恐龙")
    _require(opening.scene == "dinosaur_interest_started", "兴趣场景未启动")

    leaf_prompt = child(2, "有一种龙特别大，可是我不知道该怎么说")
    _require(leaf_prompt.scene == "dinosaur_short_leaf_prompt", "没有进入树叶追问")
    _require("高高的树叶" in leaf_prompt.text, "树叶追问话术错误")

    recast = child(3, "对，它能吃到高高的树叶")
    _require(recast.scene == "dinosaur_short_recast", "没有进入固定复述步骤")
    _require("我喜欢腕龙" in recast.text, "腕龙示范句错误")

    completed = child(
        4,
        "我喜欢腕龙，因为它身体特别大，脖子特别长，还能吃到高高的树叶",
    )
    _require(completed.scene == "dinosaur_expression_completed", "完整表达没有完成")
    _require(completed.post_tts_arm_action == "high_five", "没有排队具身击掌")
    _require(completed.end_session, "完成后仍会进入下一轮语音收听")

    accepted = child(5, "好呀")
    _require(accepted.scene == "dinosaur_drawing_accepted", "没有进入百宝箱画画引导")
    _require(accepted.end_session, "画画引导后没有结束本轮语音")
    _line("[中央 05]", "击掌结束后进入无唤醒语音引导；随后由真实触控完成画画。")

    recalled = child(6, "星宝，你还记得我喜欢什么恐龙吗？")
    _require(recalled.scene == "dinosaur_interest_recalled", "画画后的记忆回问没有命中")
    _require(recalled.end_session, "记忆回问后没有结束本轮语音")
    _line("[中央 06]", "画作保存后重新开启语音，完成一次腕龙记忆回问。")

    memory = app.session.memory_manager.load()
    _require("恐龙" in memory["interests"], "安全记忆缺少恐龙兴趣")
    _require("腕龙" in memory["interests"], "安全记忆缺少腕龙兴趣")
    _require("小宇" not in json.dumps(memory, ensure_ascii=False), "昵称被错误持久化")
    history = app.session.conversation_history_store.load()
    _require(len(history) >= 8, "回忆本聊天记录没有形成")
    _line(
        "[中央 07]",
        "安全记忆：已保存“恐龙、腕龙”和成长线索；昵称未持久化。",
    )
    _line("[中央完成]", f"聊天记录 {len(history)} 条，状态机已回到 idle。")
    return {
        "phase": "central",
        "passed": True,
        "memory_interests": memory["interests"],
        "history_count": len(history),
        "flow_stage": app.guided_expression_flow.snapshot().stage,
    }


def run_touch_phase(artifact_dir: Path) -> dict[str, Any]:
    """Exercise the actual desktop, game, memory-book, and parent modules."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ["XINGBAO_DISABLE_COMPANION_DATA_DISCOVERY"] = "1"
    os.environ["XINGBAO_COMPANION_DATA_DIR"] = str(artifact_dir / "data")
    os.chdir(TOUCH_ROOT)
    sys.path.insert(0, str(TOUCH_ROOT))

    import pygame
    import desktop as desktop_module
    from src.app import XingbaoApp as TouchGameApp
    from src.desktop_integrations import MemoryBackend, VisionStateAdapter
    from src.states import AppState

    original_store_class = desktop_module.DesktopStore
    desktop_module.DesktopStore = lambda _root: original_store_class(artifact_dir)
    launcher = desktop_module.DesktopLauncher(
        fullscreen=False,
        size=(800, 480),
    )
    launcher.memory_backend = MemoryBackend(
        artifact_dir / "saves" / "xingbao_memory.json"
    )
    launcher.vision_adapter = VisionStateAdapter(
        artifact_dir / "saves" / "vision_status.json"
    )

    _line("[触控 01]", "打开小抽屉。")
    launcher.drawer_open = True
    launcher.drawer_focus = 0
    launcher.handle_key(pygame.K_RETURN)
    _require(launcher.modal == "toolbox", "百宝箱没有通过原入口打开")
    _line("[触控 02]", f"百宝箱：{launcher.modal_read_text()}")

    width, height = launcher.screen.get_size()
    drawing_button = pygame.Rect(
        int(width * 0.52),
        int(height * 0.43),
        int(width * 0.17),
        int(height * 0.10),
    )
    launcher._handle_modal_touch(drawing_button.center)
    _require(launcher.modal == "drawing", "画板没有通过百宝箱触控入口打开")
    _line("[触控 03]", "触控进入画板，开始绘制腕龙示意线条。")

    canvas = launcher.drawing_rect()
    launcher.handle_draw_point((canvas.x + 30, canvas.y + 90), start=True)
    launcher.handle_draw_point((canvas.x + 100, canvas.y + 35))
    launcher.handle_draw_point((canvas.x + 170, canvas.y + 90))
    launcher.handle_draw_point((canvas.x + 230, canvas.y + 45))
    _require(launcher.complete_drawing(), "画作没有保存成功")
    artworks = launcher.store.data.get("artworks", [])
    _require(artworks, "画作列表没有记录")
    artwork_path = artifact_dir / artworks[-1]["path"]
    _require(artwork_path.is_file(), "画作文件不存在")
    _line("[触控 04]", f"画作已保存：{artwork_path.name}")

    visual_state = launcher.update_vision_state(0, 1, hold_seconds=2)
    _require(visual_state["needs_water"] == 1, "桌面视觉状态没有更新")
    _line("[触控 05]", "桌面视觉接口：needs_water=1，健康提醒状态可用。")

    launcher.modal = None
    launcher.drawer_open = True
    launcher.drawer_focus = 1
    action = launcher.handle_key(pygame.K_RETURN)
    _require(action == "game", "主游戏没有通过原有抽屉入口打开")
    _line("[触控 06]", "通过“一起玩”进入主游戏，选择形状游戏。")

    speech_requests: list[dict[str, Any]] = []
    game_states: list[dict[str, Any]] = []
    game = TouchGameApp(
        fullscreen=False,
        size=(800, 480),
        log_dir=artifact_dir / "logs",
        save_dir=artifact_dir / "saves",
        demo_speed="slow",
        on_speech_request=speech_requests.append,
        on_game_state=game_states.append,
    )
    game.start_game("shape")
    _require(game.game.target_id == "triangle", "形状游戏第一题不是三角形")
    _line("[触控 07]", f"第一题：{speech_requests[-1]['text']}")

    wrong = next(
        item["id"]
        for item in game.game.options
        if item["id"] != game.game.target_id
    )
    original_question_id = game.current_question_id()
    game.select_game_item(wrong)
    _require(game.current_question_id() == original_question_id, "答错后题目被替换")
    _require(game.growth_support_phase == "invitation", "首次答错没有进入支持流程")
    _line("[触控 08]", f"第一次答错：{speech_requests[-1]['text']}")

    game.feedback_speech_done = True
    game.update(0.1)
    _require(game.growth_support_phase == "high_five", "没有进入击掌阶段")
    support_states = [
        event["state"]["companion_support"]
        for event in game_states
        if event.get("state", {}).get("companion_support")
    ]
    high_five_state = support_states[-1]
    _require(high_five_state["action"] == "high_five", "没有发出高层击掌动作")
    _line(
        "[触控 09]",
        "机械臂输出：action=high_five（仅记录高层指令，本次不连接实体机械臂）。",
    )

    game.update(9.0)
    _require(game.growth_support_phase == "retry_prompt", "击掌后没有进入重试提示")
    _line("[触控 10]", f"击掌后提示：{speech_requests[-1]['text']}")
    game.feedback_speech_done = True
    game.update(0.1)
    _require(game.state == AppState.GAME_RUNNING, "重试提示后题目没有恢复")
    _require(game.current_question_id() == original_question_id, "重试时不是原题")

    game.select_game_item("triangle")
    _require(game.first_mistake_support.retry_succeeded, "同题重试没有记为成功")
    _line("[触控 11]", f"同题答对：{speech_requests[-1]['text']}")

    for _ in range(40):
        if game.state == AppState.GAME_SUMMARY:
            break
        if game.state == AppState.GAME_FEEDBACK:
            game.feedback_speech_done = True
            # Preserve the mature feedback page's 1.15 second minimum dwell
            # while advancing a headless simulation without real audio.
            game.update(2.0)
        elif game.state == AppState.GAME_RUNNING:
            game.select_game_item(game.game.target_id)
        else:
            game.update(0.2)
    _require(game.state == AppState.GAME_SUMMARY, "余题完成后没有进入结算页")
    _require(game.last_summary["accepted_hint_and_retried"], "结算缺少重试成长记录")
    _line(
        "[触控 12]",
        f"结算完成：{game.last_summary['growth_note']}",
    )

    launcher.memory_backend.add(
        "game",
        "我玩了认形状",
        "我完成了1局，还接受提示重新尝试并成功",
        source="game_center",
        media_path=game.last_game_screenshot,
    )
    launcher.reactivate_display()
    launcher.modal = "memory"
    launcher.memory_tab = "growth"
    launcher.render()
    memories = launcher.memory_backend.recent(80)
    memory_types = {entry["type"] for entry in memories}
    _require({"artwork", "game"}.issubset(memory_types), "回忆本缺少画作或游戏记录")
    _line(
        "[触控 13]",
        "回忆本成长记录：" + "；".join(entry["title"] for entry in memories[:3]),
    )

    chat_records = launcher.conversation_history_backend.load()
    _require(len(chat_records) >= 20, "回忆本没有读到中央端聊天记录")
    launcher.memory_tab = "chat"
    launcher.render()
    _line("[触控 14]", f"回忆本聊天记录：读取到 {len(chat_records)} 条真实对话。")

    launcher.companion_memory_path = artifact_dir / "data" / "memory.json"
    launcher.game_summary = launcher.store.game_summary()
    launcher.refresh_parent_summaries()
    launcher.modal = "parent"
    question = dict(launcher.parent_question)
    _line("[触控 15]", f"家长算术：{question['text']}，本次直接选择正确答案。")
    _require(
        launcher.verify_parent_answer(question["answer"]),
        "家长模式正确答案没有直接进入",
    )
    _require(launcher.modal == "parent_center", "家长中心没有打开")
    _require(launcher.parent_lock_remaining() == 0, "正确答案错误触发了锁定")
    _line("[触控 16]", "家长中心进入成功；本次未演示错误锁定。")

    parent_entries = launcher.parent_summary_backend.load()
    _require(parent_entries, "家长摘要没有生成")
    _line("[触控 17]", f"家长摘要共 {len(parent_entries)} 条。")

    game.stop()
    pygame.quit()
    _line("[触控完成]", "百宝箱、画画、主游戏、击掌状态、回忆本和家长模式全部通过。")
    return {
        "phase": "touch",
        "passed": True,
        "artwork": str(artwork_path),
        "game_summary": game.last_summary,
        "high_five_action": high_five_state["action"],
        "memory_count": len(memories),
        "chat_count": len(chat_records),
        "parent_summary_count": len(parent_entries),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="模拟星宝确认版现场展示流程")
    parser.add_argument(
        "--phase",
        choices=("central", "touch", "all"),
        default="all",
        help="central=语音与记忆，touch=触控与游戏，all=完整流程",
    )
    parser.add_argument(
        "--artifact-dir",
        required=True,
        help="本次模拟的隔离数据目录，不读取或覆盖正式儿童数据",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _line("[模拟]", f"隔离数据目录：{artifact_dir}")

    if args.phase == "central":
        result = run_central_phase(artifact_dir)
    elif args.phase == "touch":
        result = run_touch_phase(artifact_dir)
    else:
        central_result = run_central_phase(artifact_dir)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--phase",
            "touch",
            "--artifact-dir",
            str(artifact_dir),
        ]
        completed = subprocess.run(command, check=False)
        _require(completed.returncode == 0, "触控子流程失败")
        result = {
            "phase": "all",
            "passed": True,
            "central": central_result,
        }

    print("SIMULATION_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
