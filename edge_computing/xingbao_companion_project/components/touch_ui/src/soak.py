import json
import os
from pathlib import Path
import random
import tempfile

from .events import EventName
from .games.memory_path_game import MemoryPathGame, generate_memory_sequence
from .states import AppState
from .autosave import AutoSaveManager
from .demo_timing import get_demo_timing


REQUIRED_FIELDS = {"timestamp", "session_id", "event_name", "page", "game_id", "payload"}
REQUIRED_EVENTS = {
    EventName.CHILD_TOUCHED_GAME.value,
    EventName.CHILD_SELECTED_COLOR.value,
    EventName.CHILD_SELECTED_SHAPE.value,
    EventName.CHILD_SELECTED_SEQUENCE_ITEM.value,
    EventName.CHILD_SELECTED_NUMBER.value,
    EventName.CHILD_SELECTED_ENGLISH.value,
    EventName.CHILD_SELECTED_SKILL.value,
    EventName.CHILD_FINISHED_GAME.value,
    EventName.CHILD_REQUESTED_HINT.value,
    EventName.CHILD_RETURNED_HOME.value,
    EventName.XINGBAO_SPEAK.value,
    EventName.XINGBAO_SHOW_STATE.value,
    EventName.XINGBAO_START_GAME.value,
    EventName.XINGBAO_START_NEXT_ROUND.value,
    EventName.XINGBAO_SHOW_FEEDBACK.value,
    EventName.XINGBAO_SAVE_GROWTH_RECORD.value,
    EventName.DEMO_POINTER_MOVE.value,
    EventName.DEMO_POINTER_PRESS.value,
    EventName.DEMO_STEP_FINISHED.value,
    EventName.DEMO_STEP_STARTED.value,
    EventName.DEMO_SPEED_CHANGED.value,
    EventName.AUTOSAVE_SAVED.value,
}
REMOVED_EVENTS = {"child_confirmed_choice"}
FORBIDDEN_UI_TEXT = ("请把纸片", "小卡片放", "放到桌面区域", "我放好了", "桌面放置识别")


def validate_jsonl_logs(log_dir, require_events=True, paths=None):
    log_dir = Path(log_dir)
    known_events = {event.value for event in EventName}
    events_seen = set()
    errors = []
    invalid_lines = 0
    files_checked = 0

    log_paths = sorted(Path(path) for path in paths) if paths is not None else sorted(log_dir.glob("session_*.jsonl"))
    for path in log_paths:
        files_checked += 1
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                invalid_lines += 1
                errors.append("{}:{} invalid JSON: {}".format(path, line_number, exc))
                continue

            missing = REQUIRED_FIELDS - set(record)
            event_name = record.get("event_name")
            reason = None
            if missing:
                reason = "missing fields {}".format(sorted(missing))
            elif not record.get("session_id"):
                reason = "empty session_id"
            elif event_name in REMOVED_EVENTS:
                reason = "removed event {}".format(event_name)
            elif event_name not in known_events:
                reason = "unknown event {}".format(event_name)
            elif not isinstance(record.get("payload"), dict):
                reason = "payload is not object"
            elif not isinstance(record.get("page"), str) or not record["page"]:
                reason = "invalid page"

            if reason:
                invalid_lines += 1
                errors.append("{}:{} {}".format(path, line_number, reason))
                continue
            events_seen.add(event_name)

    missing_required_events = sorted(REQUIRED_EVENTS - events_seen) if require_events else []
    if require_events and missing_required_events:
        errors.append("missing required events: {}".format(missing_required_events))
    if files_checked == 0:
        errors.append("no JSONL log files found")

    return {
        "valid": files_checked > 0 and invalid_lines == 0 and not missing_required_events,
        "files_checked": files_checked,
        "invalid_lines": invalid_lines,
        "events_seen": sorted(events_seen),
        "missing_required_events": missing_required_events,
        "errors": errors,
    }


def _wrong_choice(game):
    if game.game_id != "memory":
        return next(item["id"] for item in game.options if item["id"] != game.target_id)
    return next(str(index) for index in range(4) if str(index) != game.current_sequence[0])


def _exercise_wrong_choice(app):
    if app.game.game_id == "memory":
        app.game.update(10.0)
    app.select_game_item(_wrong_choice(app.game))
    if app.game.game_id == "shape" and app.growth_support_phase == "invitation":
        # The non-interactive soak runner has no central TTS callback or child
        # high-five, so advance the same reviewed phases with virtual time.
        app.feedback_speech_done = True
        app.update(0.1)
        app.update(9.0)
        app.feedback_speech_done = True
        app.update(0.1)
    else:
        app.update(2.0)


def _complete_one_round(app):
    before = app.game.completed_rounds
    if app.game.game_id == "memory":
        app.game.update(10.0)
        for item in list(app.game.current_sequence):
            app.select_game_item(item)
    else:
        app.select_game_item(app.game.target_id)
    app.update(2.0)
    return app.game.completed_rounds == before + 1


def _run_demo_to_end(app, game_id, max_steps=300):
    app.start_demo(game_id)
    for _ in range(max_steps):
        app.update(10.0)
        if app.state == AppState.HOME and app.last_summary:
            return True
    return False


def _check_memory_sequences(sample_count=100):
    failures = 0
    positions = ["0", "1", "2", "3"]
    for seed in range(sample_count):
        sequence = generate_memory_sequence(12, positions, random.Random(seed))
        if any(left == right for left, right in zip(sequence, sequence[1:])):
            failures += 1
    return failures


def _scan_forbidden_ui_text():
    app_source = (Path(__file__).parent / "app.py").read_text(encoding="utf-8")
    return [text for text in FORBIDDEN_UI_TEXT if text in app_source]


def _check_readme_commands():
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    required = (
        "星宝陪伴桌V7",
        "python3 main.py --window",
        "python3 main.py --fullscreen",
        "python3 main.py --soak-test --rounds 100",
        "python3 main.py --fullscreen --low-effects",
    )
    return all(item in readme for item in required)


def run_soak_test(rounds=100, log_dir="logs/soak_v2", size=(800, 480), save_dir=None):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    import pygame

    from .app import XingbaoApp

    rounds = max(1, int(rounds))
    log_dir = Path(log_dir)
    save_dir = Path(save_dir) if save_dir is not None else log_dir / "saves"
    app = XingbaoApp(fullscreen=False, size=size, log_dir=log_dir,
                     save_dir=save_dir, demo_speed="slow")
    errors = []
    rounds_completed = 0
    games_completed_by_id = set()
    game_cycle = ("color", "shape", "memory", "counting", "english", "skill")
    cycle_index = 0
    hint_exercised = False
    memory_sequences_checked = 100
    memory_adjacent_repeat_failures = _check_memory_sequences(memory_sequences_checked)
    memory_probe = MemoryPathGame(seed=2026)
    probe_result = memory_probe.handle_choice(memory_probe.current_sequence[0])
    memory_playback_click_ignored = probe_result.ignored and memory_probe.error_count == 0
    if memory_adjacent_repeat_failures:
        errors.append("memory sequence has adjacent repeats")
    if not memory_playback_click_ignored:
        errors.append("memory playback accepted click")

    try:
        while rounds_completed < rounds:
            game_id = game_cycle[cycle_index % len(game_cycle)]
            cycle_index += 1
            app.start_game(game_id)

            if game_id == "color" and not hint_exercised:
                app.update(app.hint_after_seconds + 0.1)
                hint_exercised = True
            _exercise_wrong_choice(app)

            while not app.game.is_finished() and rounds_completed < rounds:
                if not _complete_one_round(app):
                    errors.append("{} round did not advance".format(game_id))
                    break
                rounds_completed += 1

            if app.game.is_finished():
                if app.state != AppState.GAME_SUMMARY:
                    errors.append("{} finished in state {}".format(game_id, app.state.value))
                else:
                    summary = app.last_summary
                    if summary["completed_rounds"] != app.game.rounds:
                        errors.append("{} summary round mismatch".format(game_id))
                    games_completed_by_id.add(game_id)
            app.go_home()

        app.show_records()
        if app.state != AppState.TODAY_RECORD:
            errors.append("today record state not reached")
        app.go_home()

        app.show_weekly_records()
        if app.state != AppState.WEEKLY_RECORD:
            errors.append("weekly record state not reached")
        app.go_home()

        for game_id in game_cycle:
            if not _run_demo_to_end(app, game_id):
                errors.append("{} demo mode did not finish".format(game_id))
                break
        final_state = app.state.value
    except Exception as exc:
        errors.append("{}: {}".format(type(exc).__name__, exc))
        final_state = app.state.value
    finally:
        app.stop()
        pygame.quit()

    save_path = save_dir / "latest_save.json"
    try:
        saved = json.loads(save_path.read_text(encoding="utf-8"))
        autosave_valid = all(isinstance(saved.get(key), dict) for key in
                             ("growth", "totals", "today", "records", "settings"))
    except (OSError, json.JSONDecodeError):
        autosave_valid = False
    restored = AutoSaveManager(save_dir).load_latest()
    autosave_restore_valid = bool(restored and restored.get("growth") == saved.get("growth")) if autosave_valid else False
    with tempfile.TemporaryDirectory() as corrupt_dir:
        Path(corrupt_dir, "latest_save.json").write_text("{broken", encoding="utf-8")
        corrupt_save_fallback = AutoSaveManager(corrupt_dir).load_latest() is None
    slow = get_demo_timing("slow")
    probe_demo = MemoryPathGame(seed=7, demo_timing=True, timing=slow)
    demo_timing_valid = (
        app.demo_speed == "slow" and app.demo_timing["pointer_move"] == 1.0
        and probe_demo.flash_duration == 1.25 and probe_demo.flash_gap == 0.75
        and probe_demo.before_input_delay == 0.8
    )
    if not autosave_valid: errors.append("autosave JSON is invalid")
    if not autosave_restore_valid: errors.append("autosave restore mismatch")
    if not corrupt_save_fallback: errors.append("corrupt save did not fall back")
    if not demo_timing_valid: errors.append("slow demo timing is inactive")

    log_result = validate_jsonl_logs(log_dir, paths=[app.logger.path])
    errors.extend(log_result["errors"])
    forbidden_ui_text_found = _scan_forbidden_ui_text()
    readme_commands_valid = _check_readme_commands()
    if forbidden_ui_text_found:
        errors.append("forbidden UI text: {}".format(forbidden_ui_text_found))
    if not readme_commands_valid:
        errors.append("README run commands are incomplete")

    return {
        "rounds_requested": rounds,
        "rounds_completed": rounds_completed,
        "games_completed_by_id": sorted(games_completed_by_id),
        "final_state": final_state,
        "log_dir": str(log_dir),
        "log_files_checked": log_result["files_checked"],
        "invalid_log_lines": log_result["invalid_lines"],
        "events_seen": log_result["events_seen"],
        "missing_required_events": log_result["missing_required_events"],
        "forbidden_ui_text_found": forbidden_ui_text_found,
        "memory_sequences_checked": memory_sequences_checked,
        "memory_adjacent_repeat_failures": memory_adjacent_repeat_failures,
        "memory_playback_click_ignored": memory_playback_click_ignored,
        "readme_commands_valid": readme_commands_valid,
        "autosave_valid": autosave_valid,
        "autosave_restore_valid": autosave_restore_valid,
        "corrupt_save_fallback": corrupt_save_fallback,
        "demo_timing_valid": demo_timing_valid,
        "errors": errors,
        "all_modules_exercised": set(game_cycle).issubset(games_completed_by_id),
        "passed": (
            rounds_completed == rounds and not errors
            and (rounds < 29 or set(game_cycle).issubset(games_completed_by_id))
        ),
    }
