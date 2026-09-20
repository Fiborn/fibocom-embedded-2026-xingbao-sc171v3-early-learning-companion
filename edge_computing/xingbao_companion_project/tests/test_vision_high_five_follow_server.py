import threading
import time
from types import SimpleNamespace

from components.arm_soarm101.arm_action_server_soft_nod import ArmActionServer, build_parser


class _FakeDriverModule:
    moves: list[dict[str, float]] = []

    @staticmethod
    def move_to_action(
        _robot,
        target,
        *,
        steps,
        step_delay,
        use_smoothstep,
        stop_event,
        deadline_monotonic,
    ) -> bool:
        del steps, step_delay, use_smoothstep, stop_event, deadline_monotonic
        _FakeDriverModule.moves.append(dict(target))
        return True


class _InterruptibleFakeDriverModule:
    """Model the driver's per-step stop check without exposing raw motion."""

    moves: list[dict[str, float]] = []
    interrupted_targets: list[dict[str, float]] = []
    first_target: dict[str, float] = {}
    first_target_started = threading.Event()

    @classmethod
    def reset(cls, first_target: dict[str, float]) -> None:
        cls.moves = []
        cls.interrupted_targets = []
        cls.first_target = dict(first_target)
        cls.first_target_started = threading.Event()

    @staticmethod
    def move_to_action(
        _robot,
        target,
        *,
        steps,
        step_delay,
        use_smoothstep,
        stop_event,
        deadline_monotonic,
    ) -> bool:
        del steps, step_delay, use_smoothstep, deadline_monotonic
        target_copy = dict(target)
        _InterruptibleFakeDriverModule.moves.append(target_copy)
        if target_copy == _InterruptibleFakeDriverModule.first_target:
            _InterruptibleFakeDriverModule.first_target_started.set()
            # Keep the initial long segment in progress until a redirect.  A
            # real driver checks the event every interpolation step; the fake
            # models that interruptibility without making the test depend on
            # host timer granularity.
            if stop_event is not None and stop_event.wait(0.50):
                _InterruptibleFakeDriverModule.interrupted_targets.append(target_copy)
                return False
        return True


def _target_pose(server: ArmActionServer, action: str, segment_index: int) -> dict[str, float]:
    group = server._action_to_group[action]
    pose_id = server._runtime_groups[group]["sequence"][segment_index]
    return dict(server._runtime_poses[pose_id])


def _wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_follow_session_redirects_only_to_reviewed_point_then_returns() -> None:
    server = ArmActionServer(
        follow_idle_seconds=0.12,
        follow_max_redirects=2,
        follow_max_duration_seconds=10.0,
    )
    server._driver_server = SimpleNamespace(
        _lock=threading.Lock(),
        _stop_event=threading.Event(),
        robot=object(),
    )
    server._driver_module = _FakeDriverModule
    _FakeDriverModule.moves = []

    start = server.handle_action_sync("vision_high_five_11")
    assert start["hardware_feedback"]["queue_status"] == "follow_session_started"
    first_target = _target_pose(server, "vision_high_five_11", 1)
    assert _wait_for(lambda: first_target in _FakeDriverModule.moves)

    redirect = server.handle_action_sync("vision_high_five_23")
    assert redirect["hardware_feedback"]["queue_status"] == "follow_redirect_accepted"
    second_target = _target_pose(server, "vision_high_five_23", 1)
    assert _wait_for(lambda: second_target in _FakeDriverModule.moves)
    assert _wait_for(lambda: server._follow_session is None)

    assert _FakeDriverModule.moves[-1] == _target_pose(server, "vision_high_five_23", 2)
    assert first_target in _FakeDriverModule.moves
    assert second_target in _FakeDriverModule.moves


def test_follow_session_rejects_raw_or_excessive_redirects() -> None:
    server = ArmActionServer(
        follow_idle_seconds=0.12,
        follow_max_redirects=0,
        follow_max_duration_seconds=10.0,
    )
    server._driver_server = SimpleNamespace(
        _lock=threading.Lock(),
        _stop_event=threading.Event(),
        robot=object(),
    )
    server._driver_module = _FakeDriverModule
    _FakeDriverModule.moves = []

    assert server.handle_action_sync("servo_angle_120")["hardware_feedback"]["error"].startswith("unknown_action")
    server.handle_action_sync("vision_high_five_12")
    assert _wait_for(lambda: server._follow_session is not None)
    denied = server.handle_action_sync("vision_high_five_13")
    assert denied["hardware_feedback"]["error"] == "follow_redirect_limit"
    assert _wait_for(lambda: server._follow_session is None)


def test_follow_redirect_interrupts_active_segment_without_waiting_for_full_profile() -> None:
    server = ArmActionServer(
        follow_idle_seconds=0.06,
        follow_max_redirects=2,
        follow_max_duration_seconds=5.0,
    )
    server._driver_server = SimpleNamespace(
        _lock=threading.Lock(),
        _stop_event=threading.Event(),
        robot=object(),
    )
    first_target = _target_pose(server, "vision_high_five_11", 1)
    second_target = _target_pose(server, "vision_high_five_23", 1)
    _InterruptibleFakeDriverModule.reset(first_target)
    server._driver_module = _InterruptibleFakeDriverModule

    server.handle_action_sync("vision_high_five_11")
    assert _InterruptibleFakeDriverModule.first_target_started.wait(timeout=1.0)

    redirect_started_at = time.monotonic()
    redirect = server.handle_action_sync("vision_high_five_23")
    assert redirect["hardware_feedback"]["queue_status"] == "follow_redirect_accepted"
    assert _wait_for(lambda: second_target in _InterruptibleFakeDriverModule.moves, timeout=0.20)
    assert time.monotonic() - redirect_started_at < 0.20
    assert first_target in _InterruptibleFakeDriverModule.interrupted_targets
    assert _wait_for(lambda: server._follow_session is None, timeout=2.0)


def test_arm_service_reads_the_shared_runtime_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("XINGBAO_ARM_ACTION_HOST", "127.0.0.1")
    monkeypatch.setenv("XINGBAO_ARM_ACTION_PORT", "18764")

    args = build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 18764
