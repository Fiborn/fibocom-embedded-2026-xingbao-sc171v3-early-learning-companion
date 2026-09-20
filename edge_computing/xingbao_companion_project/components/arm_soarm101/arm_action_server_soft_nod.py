#!/usr/bin/env python3
"""Serve reviewed, high-level arm expression actions only.

The public TCP interface has no joint positions or raw commands. It loads only
locally reviewed pose sequences from ``action_registry.json`` and delegates
their execution to the isolated SO-101 compatibility driver.
"""

from __future__ import annotations

import asyncio
import argparse
import importlib.util
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from arm_action_library import (
        DEFAULT_REGISTRY_PATH,
        VISION_HIGH_FIVE_ACTION_NAMES,
        VISION_HIGH_FIVE_FOLLOW_IDLE_SECONDS,
        VISION_HIGH_FIVE_FOLLOW_MAX_DURATION_SECONDS,
        VISION_HIGH_FIVE_FOLLOW_MAX_REDIRECTS,
        compile_registry,
        load_registry,
    )
except ImportError:
    from .arm_action_library import (  # type: ignore
        DEFAULT_REGISTRY_PATH,
        VISION_HIGH_FIVE_ACTION_NAMES,
        VISION_HIGH_FIVE_FOLLOW_IDLE_SECONDS,
        VISION_HIGH_FIVE_FOLLOW_MAX_DURATION_SECONDS,
        VISION_HIGH_FIVE_FOLLOW_MAX_REDIRECTS,
        compile_registry,
        load_registry,
    )


_DEFAULT_DRIVER = Path(__file__).resolve().parent / "legacy_compat" / "arm_action_server.py"
LEGACY_SERVER_PATH = Path(os.getenv("XINGBAO_VERIFIED_ARM_SERVER", str(_DEFAULT_DRIVER)))
REGISTRY_PATH = Path(os.getenv("XINGBAO_ARM_ACTION_REGISTRY", str(DEFAULT_REGISTRY_PATH)))
# 这是协议层可表达的动作名称；真正可执行的集合仍由已审核动作库决定。
PUBLIC_ACTIONS = frozenset({"stay_still", "nod", "shake_head", "bow", "mouth", "high_five"}) | VISION_HIGH_FIVE_ACTION_NAMES


def _feedback(
    action: str,
    request_id: str,
    *,
    implemented: bool,
    ok: bool = True,
    error: str | None = None,
    hardware_group: str = "",
    duration_ms: float | None = None,
    queued: bool = False,
    queue_status: str = "",
) -> dict[str, Any]:
    hardware_feedback: dict[str, Any] = {
        "ok": ok,
        "implemented_by": "board_hardware_team",
        "arm_action": action,
        "implemented": implemented,
        "error": error,
    }
    if hardware_group:
        hardware_feedback["hardware_group"] = hardware_group
    if duration_ms is not None:
        hardware_feedback["duration_ms"] = round(float(duration_ms), 1)
    if queued:
        hardware_feedback["queued"] = True
    if queue_status:
        hardware_feedback["queue_status"] = queue_status
    return {
        "type": "command_result",
        "request_id": request_id,
        "ok": ok,
        "results": [],
        "hardware_feedback": hardware_feedback,
    }


def _load_verified_driver(path: Path = LEGACY_SERVER_PATH) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError(f"verified SO-101 service is missing: {path}")
    spec = importlib.util.spec_from_file_location("xingbao_verified_so101", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load verified SO-101 service: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class _VisionHighFiveFollowSession:
    """Private hardware-side state for one bounded six-point interaction."""

    target_action: str
    started_at: float
    update_event: threading.Event
    redirects: int = 0
    target_revision: int = 0
    phase: str = "starting"
    cancelled: bool = False


class ArmActionServer:
    """仅执行已审核高层动作库的 SO-101 白名单包装器。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8764,
        registry_path: Path | str = REGISTRY_PATH,
        *,
        follow_idle_seconds: float = VISION_HIGH_FIVE_FOLLOW_IDLE_SECONDS,
        follow_max_redirects: int = VISION_HIGH_FIVE_FOLLOW_MAX_REDIRECTS,
        follow_max_duration_seconds: float = VISION_HIGH_FIVE_FOLLOW_MAX_DURATION_SECONDS,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.registry_path = Path(registry_path)
        compiled = compile_registry(load_registry(self.registry_path))
        self._runtime_poses: dict[int, dict[str, float]] = compiled["poses"]
        self._runtime_groups: dict[str, dict[str, Any]] = compiled["groups"]
        self._action_to_group: dict[str, str] = compiled["action_to_group"]
        self._action_cooldowns: dict[str, float] = compiled["action_cooldowns"]
        self._action_segments: dict[str, list[dict[str, Any]]] = compiled["action_segments"]
        self._action_max_durations: dict[str, float] = compiled["action_max_durations"]
        self._driver_server: Any | None = None
        self._driver_module: ModuleType | None = None
        self._request_lock = threading.Lock()
        self._last_action_started_at: dict[str, float] = {}
        # 所有自动表意动作在服务内串行执行。待执行槽只有一个，避免孩子
        # 连续点击或多个事件源造成“补播一串过期动作”。最新且不同的语义
        # 会替换旧的待执行动作；当前正在运行的动作绝不被自动中断。
        self._execution_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending_action: tuple[str, str] | None = None
        self._fault_lock = threading.Lock()
        self._fault_reason = ""
        self._inflight_worker: threading.Thread | None = None
        # A follow session is intentionally private to this hardware service.
        # Network callers may provide only one reviewed point name; the worker
        # itself chooses the already-reviewed target pose and profile.
        self._follow_lock = threading.Lock()
        self._follow_session: _VisionHighFiveFollowSession | None = None
        self._follow_idle_seconds = max(0.5, float(follow_idle_seconds))
        self._follow_max_redirects = max(0, int(follow_max_redirects))
        self._follow_max_duration_seconds = max(
            # A session must always reserve time for one target transition
            # and its final neutral return, even in a test configuration.
            self._follow_idle_seconds + 8.0,
            float(follow_max_duration_seconds),
        )

    def _current_fault(self) -> str:
        with self._fault_lock:
            return self._fault_reason

    def _latch_fault(self, reason: str) -> None:
        with self._fault_lock:
            self._fault_reason = str(reason or "arm_service_fault")
        with self._pending_lock:
            self._pending_action = None

    def _request_stop(self) -> None:
        driver = self._driver_server
        stop_event = getattr(driver, "_stop_event", None) if driver is not None else None
        if stop_event is not None:
            stop_event.set()
        with self._pending_lock:
            self._pending_action = None
        with self._follow_lock:
            if self._follow_session is not None:
                self._follow_session.cancelled = True
                self._follow_session.update_event.set()

    def execute_group(self, group_name: str) -> dict[str, Any]:
        if group_name not in self._runtime_groups:
            return {"ok": False, "implemented": False, "error": "unsafe_group"}
        if self._driver_server is None:
            raise RuntimeError("SO-101 driver is not initialized")
        result = self._driver_server.execute_group(group_name)
        return dict(result) if isinstance(result, dict) else {
            "ok": False,
            "implemented": False,
            "error": "invalid_driver_result",
        }

    def _uses_custom_segment_profiles(self, action: str) -> bool:
        profiles = self._action_segments[action]
        first = profiles[0]
        return any(
            profile["steps"] != first["steps"]
            or profile["delay_seconds"] != first["delay_seconds"]
            or profile["smoothstep"] != first["smoothstep"]
            or profile.get("hold_after_seconds", 0.0) > 0
            for profile in profiles[1:]
        )

    def _execute_segmented_action(
        self,
        action: str,
        group_name: str,
        *,
        deadline_monotonic: float,
    ) -> dict[str, Any]:
        """执行本地审核过的分段速度配置，供“击掌慢回位”使用。

        这里仍在硬件服务内，姿态、步数和延时均来自本地动作库；TCP 请求无法
        提供任何关节参数。
        """
        driver = self._driver_server
        module = self._driver_module
        if driver is None or module is None:
            raise RuntimeError("SO-101 driver is not initialized")
        lock = getattr(driver, "_lock", None)
        if lock is None or not lock.acquire(blocking=False):
            return {"ok": False, "implemented": False, "error": "robot_busy"}
        try:
            sequence = self._runtime_groups[group_name]["sequence"]
            profiles = self._action_segments[action]
            stop_event = getattr(driver, "_stop_event", None)
            for pose_id, profile in zip(sequence, profiles):
                if time.monotonic() >= deadline_monotonic:
                    return {"ok": False, "implemented": False, "group": group_name, "error": "duration_exceeded"}
                if stop_event is not None and stop_event.is_set():
                    return {"ok": False, "implemented": False, "group": group_name, "error": "stopped"}
                completed = module.move_to_action(
                    driver.robot,
                    driver.actions[pose_id],
                    steps=int(profile["steps"]),
                    step_delay=float(profile["delay_seconds"]),
                    use_smoothstep=bool(profile["smoothstep"]),
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                )
                if not completed:
                    error = "duration_exceeded" if time.monotonic() >= deadline_monotonic else "stopped"
                    return {"ok": False, "implemented": False, "group": group_name, "error": error}
                hold_after_seconds = float(profile.get("hold_after_seconds", 0.0))
                if hold_after_seconds > 0 and stop_event is not None and stop_event.wait(hold_after_seconds):
                    return {"ok": False, "implemented": False, "group": group_name, "error": "stopped"}
                if hold_after_seconds > 0 and stop_event is None:
                    time.sleep(hold_after_seconds)
            return {"ok": True, "implemented": True, "group": group_name, "message": "sequence_completed"}
        except Exception as exc:
            return {"ok": False, "implemented": False, "group": group_name, "error": str(exc)}
        finally:
            lock.release()

    def execute_action(self, action: str, *, deadline_monotonic: float) -> dict[str, Any]:
        group_name = self._action_to_group[action]
        # Every reviewed action uses the registry's segment profile.  This
        # keeps stop checks and the deadline active for nod as well as the
        # less common expressions.
        return self._execute_segmented_action(
            action,
            group_name,
            deadline_monotonic=deadline_monotonic,
        )

    def _run_action(self, action: str, request_id: str) -> dict[str, Any]:
        """Run one action with a hard fail-closed watchdog around the driver."""
        started_at = time.monotonic()
        group_name = self._action_to_group[action]
        max_duration = self._action_max_durations[action]
        deadline_monotonic = started_at + max_duration
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def execute() -> None:
            try:
                outcome["result"] = self.execute_action(
                    action,
                    deadline_monotonic=deadline_monotonic,
                )
            except Exception as exc:  # hardware exceptions must become a receipt
                outcome["result"] = {
                    "ok": False,
                    "implemented": False,
                    "group": group_name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            finally:
                completed.set()

        worker = threading.Thread(
            target=execute,
            name=f"arm-action-{action}",
            daemon=True,
        )
        self._inflight_worker = worker
        worker.start()
        if not completed.wait(timeout=max_duration):
            # A low-level serial call cannot be killed safely in-process.
            # Stop at the next checked point, latch the service in a
            # fail-closed state, and require a clean service restart before
            # any further motion can be requested.
            self._request_stop()
            self._latch_fault("duration_exceeded")
            duration_ms = (time.monotonic() - started_at) * 1000
            print(
                f"[arm-safety] action={action} fault=duration_exceeded duration_ms={duration_ms:.1f}",
                flush=True,
            )
            return _feedback(
                action,
                request_id,
                implemented=False,
                ok=False,
                error="duration_exceeded",
                hardware_group=group_name,
                duration_ms=duration_ms,
            )

        result = outcome.get("result")
        if not isinstance(result, dict):
            result = {"ok": False, "implemented": False, "error": "invalid_driver_result"}
        duration_ms = (time.monotonic() - started_at) * 1000
        if duration_ms > max_duration * 1000 or result.get("error") == "duration_exceeded":
            self._request_stop()
            self._latch_fault("duration_exceeded")
            result = {**result, "ok": False, "implemented": False, "error": "duration_exceeded"}
        print(
            "[arm-action] action={} ok={} error={} duration_ms={:.1f}".format(
                action,
                bool(result.get("ok")),
                result.get("error"),
                duration_ms,
            ),
            flush=True,
        )
        return _feedback(
            action,
            request_id,
            ok=bool(result.get("ok")),
            implemented=bool(result.get("implemented")),
            error=result.get("error"),
            hardware_group=group_name,
            duration_ms=duration_ms,
        )

    def _move_follow_segment(
        self,
        action: str,
        segment_index: int,
        *,
        deadline_monotonic: float,
        interrupt_event: threading.Event | None = None,
    ) -> bool:
        """Move only to a pose/profile compiled from the approved registry.

        A follow redirect may use its private update event as the stop source.
        ``move_to_action`` checks that event between every reviewed 40 ms
        interpolation step, then the next call starts from the arm's observed
        current pose.  No request can supply a pose, speed, or trajectory.
        """
        driver = self._driver_server
        module = self._driver_module
        if driver is None or module is None:
            return False
        group_name = self._action_to_group[action]
        sequence = self._runtime_groups[group_name]["sequence"]
        pose_id = int(sequence[segment_index])
        profile = self._action_segments[action][segment_index]
        stop_event = interrupt_event or getattr(driver, "_stop_event", None)
        return bool(
            module.move_to_action(
                driver.robot,
                self._runtime_poses[pose_id],
                steps=int(profile["steps"]),
                step_delay=float(profile["delay_seconds"]),
                use_smoothstep=bool(profile["smoothstep"]),
                stop_event=stop_event,
                deadline_monotonic=deadline_monotonic,
            )
        )

    def _follow_segment_seconds(self, action: str, segment_index: int) -> float:
        profile = self._action_segments[action][segment_index]
        return float(profile["steps"]) * float(profile["delay_seconds"])

    def _finish_follow_session(self, session: _VisionHighFiveFollowSession) -> None:
        with self._follow_lock:
            if self._follow_session is session:
                self._follow_session = None
        self._execution_lock.release()

    def _run_vision_high_five_follow(
        self,
        session: _VisionHighFiveFollowSession,
    ) -> None:
        """Hold one fixed point, redirect only on a new reviewed point, then return.

        The legacy driver lock is held by this one worker so retargeting cannot
        race another arm action.  It is not an arbitrary trajectory API: every
        segment resolves to a precompiled pose and segment profile.
        """
        driver = self._driver_server
        if driver is None:
            self._finish_follow_session(session)
            return
        driver_lock = getattr(driver, "_lock", None)
        if driver_lock is None or not driver_lock.acquire(blocking=False):
            self._finish_follow_session(session)
            return

        deadline = session.started_at + self._follow_max_duration_seconds
        last_arrived_at = 0.0
        current_action = ""
        try:
            with self._follow_lock:
                initial_action = session.target_action
            # The current six-point actions all share the reviewed neutral
            # opening pose.  Keeping this short segment makes each session
            # begin from a predictable safe position.
            if not self._move_follow_segment(
                initial_action,
                0,
                deadline_monotonic=deadline,
            ):
                return

            while time.monotonic() < deadline:
                with self._follow_lock:
                    if session.cancelled:
                        return
                    desired_action = session.target_action
                    target_revision = session.target_revision
                    session.phase = "moving" if desired_action != current_action else "holding"
                    # Clearing while holding the same lock as the redirect
                    # writer means a new reviewed position can never be lost:
                    # it either predates this movement or sets the event after
                    # this point and interrupts it within one interpolation
                    # step.
                    session.update_event.clear()

                # Leave enough of the bounded session for a clean neutral
                # return.  A late camera update is ignored rather than
                # letting the arm remain extended past its safety deadline.
                return_action = current_action or desired_action
                return_reserve = self._follow_segment_seconds(return_action, 2) + 0.5
                if time.monotonic() >= deadline - return_reserve:
                    break

                if desired_action != current_action:
                    transition_budget = (
                        self._follow_segment_seconds(desired_action, 1)
                        + self._follow_segment_seconds(desired_action, 2)
                        + 0.5
                    )
                    if time.monotonic() >= deadline - transition_budget:
                        break
                    if not self._move_follow_segment(
                        desired_action,
                        1,
                        deadline_monotonic=deadline,
                        interrupt_event=session.update_event,
                    ):
                        with self._follow_lock:
                            if session.cancelled:
                                return
                            redirected = session.target_revision != target_revision
                        # A different approved point arrived during this
                        # interpolation.  ``move_to_action`` has stopped at
                        # the current physical pose; immediately begin a new
                        # smooth interpolation from there instead of waiting
                        # for the remaining 3.6-second segment.
                        if redirected:
                            continue
                        return
                    current_action = desired_action
                    last_arrived_at = time.monotonic()
                    with self._follow_lock:
                        redirected = session.target_revision != target_revision
                        session.phase = "holding"
                    if redirected:
                        continue
                    continue

                remaining_idle = self._follow_idle_seconds - (time.monotonic() - last_arrived_at)
                if remaining_idle <= 0:
                    break
                session.update_event.wait(timeout=min(0.10, remaining_idle))
                session.update_event.clear()

            with self._follow_lock:
                if session.cancelled:
                    return
                session.phase = "returning"
            # The final segment of every reviewed six-point action is the
            # same neutral return.  The deadline remains active here too.
            if current_action:
                self._move_follow_segment(
                    current_action,
                    2,
                    deadline_monotonic=deadline,
                )
        finally:
            driver_lock.release()
            self._finish_follow_session(session)

    def _start_or_update_vision_high_five(
        self,
        action: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Accept a reviewed point as a bounded follow-session start/update."""
        fault_reason = self._current_fault()
        if fault_reason:
            return _feedback(
                action,
                request_id,
                implemented=False,
                ok=False,
                error=f"service_faulted:{fault_reason}",
            )

        group_name = self._action_to_group[action]
        with self._follow_lock:
            session = self._follow_session
            if session is not None:
                if session.cancelled or session.phase == "returning":
                    return _feedback(
                        action,
                        request_id,
                        implemented=False,
                        ok=False,
                        error="follow_session_closing",
                        hardware_group=group_name,
                    )
                if action == session.target_action:
                    return _feedback(
                        action,
                        request_id,
                        implemented=False,
                        hardware_group=group_name,
                        queued=True,
                        queue_status="follow_duplicate_position",
                    )
                if session.redirects >= self._follow_max_redirects:
                    return _feedback(
                        action,
                        request_id,
                        implemented=False,
                        ok=False,
                        error="follow_redirect_limit",
                        hardware_group=group_name,
                    )
                session.target_action = action
                session.redirects += 1
                session.target_revision += 1
                session.update_event.set()
                return _feedback(
                    action,
                    request_id,
                    implemented=False,
                    hardware_group=group_name,
                    queued=True,
                    queue_status="follow_redirect_accepted",
                )

            if not self._execution_lock.acquire(blocking=False):
                return _feedback(
                    action,
                    request_id,
                    implemented=False,
                    ok=False,
                    error="robot_busy",
                    hardware_group=group_name,
                )
            stop_event = getattr(self._driver_server, "_stop_event", None)
            if stop_event is not None:
                stop_event.clear()
            session = _VisionHighFiveFollowSession(
                target_action=action,
                started_at=time.monotonic(),
                update_event=threading.Event(),
            )
            self._follow_session = session
            worker = threading.Thread(
                target=self._run_vision_high_five_follow,
                args=(session,),
                name="vision-high-five-follow",
                daemon=True,
            )
            self._inflight_worker = worker
            worker.start()
            return _feedback(
                action,
                request_id,
                implemented=False,
                hardware_group=group_name,
                queued=True,
                queue_status="follow_session_started",
            )

    def _queue_after_current(self, action: str, request_id: str) -> dict[str, Any]:
        """Coalesce or replace the one pending non-interrupting expression."""
        with self._pending_lock:
            current = self._pending_action
            if current is not None and current[0] == action:
                return _feedback(
                    action,
                    request_id,
                    implemented=False,
                    queued=True,
                    queue_status="coalesced_duplicate",
                )
            self._pending_action = (action, request_id)
            return _feedback(
                action,
                request_id,
                implemented=False,
                queued=True,
                queue_status="replaced_pending" if current is not None else "queued_after_current",
            )

    def _take_pending_action(self) -> tuple[str, str] | None:
        with self._pending_lock:
            pending = self._pending_action
            self._pending_action = None
            return pending

    def handle_action_sync(self, action_name: str, request_id: str = "") -> dict[str, Any]:
        action = str(action_name or "").strip()
        if action != "stay_still" and action not in self._action_to_group:
            return _feedback(
                "stay_still",
                request_id,
                implemented=False,
                error=f"unknown_action: {action}",
            )
        if action == "stay_still":
            # ``driver.handle_action_sync`` is replaced with this wrapper at
            # startup, so calling it here would recurse until the socket closes.
            # Setting the legacy driver's stop event preserves its safe-stop
            # behavior without issuing any low-level joint command.
            self._request_stop()
            return _feedback("stay_still", request_id, implemented=True)

        if action in VISION_HIGH_FIVE_ACTION_NAMES:
            return self._start_or_update_vision_high_five(action, request_id)

        fault_reason = self._current_fault()
        if fault_reason:
            return _feedback(
                action,
                request_id,
                implemented=False,
                ok=False,
                error=f"service_faulted:{fault_reason}",
            )

        now = time.monotonic()
        with self._request_lock:
            cooldown = self._action_cooldowns[action]
            last_started_at = self._last_action_started_at.get(action, 0.0)
            if now - last_started_at < cooldown:
                return _feedback(
                    action,
                    request_id,
                    implemented=False,
                    ok=False,
                    error="rate_limited",
                )
            self._last_action_started_at[action] = now

        if not self._execution_lock.acquire(blocking=False):
            # Do not replay stale physical movements.  A child can repeat the
            # semantic request after the current expression has completed.
            return _feedback(
                action,
                request_id,
                implemented=False,
                ok=False,
                error="robot_busy",
            )
        try:
            stop_event = getattr(self._driver_server, "_stop_event", None)
            if stop_event is not None:
                stop_event.clear()
            response = self._run_action(action, request_id)
            return response
        finally:
            self._execution_lock.release()

    async def run(self) -> None:
        module = _load_verified_driver()
        self._driver_module = module
        groups = getattr(module, "ACTION_GROUPS", None)
        if not isinstance(groups, dict):
            raise RuntimeError("verified SO-101 driver has no action groups")
        driver = module.ArmActionServer(host=self.host, port=self.port)
        self._driver_server = driver
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, driver.init_robot)
        # 私有兼容驱动仍负责串口、插值、锁和异常恢复；只替换其静态姿态组。
        # 外部请求永远只能通过本服务的高层 action 名进入。
        groups.clear()
        groups.update(self._runtime_groups)
        driver.actions = self._runtime_poses
        driver.handle_action_sync = self.handle_action_sync
        server = await asyncio.start_server(
            driver.handle_client,
            self.host,
            self.port,
            reuse_address=True,
        )
        async with server:
            await server.serve_forever()

    def shutdown(self) -> None:
        if self._driver_server is not None:
            self._driver_server.shutdown()


def _configured_port(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid_{name.lower()}:{raw}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"invalid_{name.lower()}:{raw}")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Xingbao whitelisted arm action service")
    parser.add_argument(
        "--host",
        default=os.getenv("XINGBAO_ARM_ACTION_HOST", "127.0.0.1").strip() or "127.0.0.1",
    )
    parser.add_argument("--port", type=int, default=_configured_port("XINGBAO_ARM_ACTION_PORT", 8764))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    server = ArmActionServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
