import socketserver
import sys
import threading
from types import SimpleNamespace

import numpy as np

from multimodal.high_five_vision_runtime import (
    FOLLOW_INPUT_WINDOW_SECONDS,
    FollowInputWindow,
    GRID_ACTIONS,
    GRID_COMMANDS,
    HandControlServer,
    HandDetection,
    HandDetector,
    fibo_hand_detection_from_objects,
    fibo_result_requires_fallback,
    HighFiveFrameProcessor,
    HandRecognitionGate,
    HandPositionSampler,
    StableGridAction,
    follow_dispatch_accepted,
    grid_position,
    wait_for_vision_point_endpoint,
)
import multimodal.high_five_vision_runtime as high_five_runtime


def test_six_point_grid_maps_to_only_reviewed_high_five_actions() -> None:
    assert grid_position(0, 0, 600, 400) == (1, 1)
    assert grid_position(599, 0, 600, 400) == (1, 3)
    assert grid_position(0, 399, 600, 400) == (2, 1)
    assert grid_position(599, 399, 600, 400) == (2, 3)
    assert set(GRID_ACTIONS) == {(row, column) for row in (1, 2) for column in (1, 2, 3)}
    assert set(GRID_ACTIONS.values()) == {
        "vision_high_five_11",
        "vision_high_five_12",
        "vision_high_five_13",
        "vision_high_five_21",
        "vision_high_five_22",
        "vision_high_five_23",
    }
    assert GRID_COMMANDS == {
        (1, 1): "11", (1, 2): "12", (1, 3): "13",
        (2, 1): "21", (2, 2): "22", (2, 3): "23",
    }


def test_grid_position_requires_three_stable_frames_and_sends_once() -> None:
    stabilizer = StableGridAction(required_frames=3)

    assert stabilizer.observe((1, 2)) is None
    assert stabilizer.observe((1, 2)) is None
    assert stabilizer.observe((1, 2)) == "vision_high_five_12"
    assert stabilizer.observe((1, 2)) is None
    assert stabilizer.observe(None) is None
    assert stabilizer.observe((2, 1)) is None
    assert stabilizer.observe((2, 1)) is None
    assert stabilizer.observe((2, 1)) == "vision_high_five_21"


def test_hand_position_sampler_limits_detection_to_three_hz() -> None:
    sampler = HandPositionSampler(interval_seconds=0.30)

    assert sampler.is_due(10.0) is True
    assert sampler.is_due(10.29) is False
    assert sampler.is_due(10.30) is True
    sampler.reset()
    assert sampler.is_due(10.31) is True


def test_standalone_hand_runtime_defaults_sampling_to_point_eight_seconds() -> None:
    assert high_five_runtime.build_parser().parse_args([]).hand_sample_seconds == 0.8


def test_unified_processor_exposes_last_detected_grid_position_for_visualization() -> None:
    class Detector:
        def detect(self, _frame):
            return HandDetection(center=(500, 300), box=(440, 220, 560, 360), confidence=0.91)

    class Frame:
        shape = (400, 600, 3)

    gate = HandRecognitionGate()
    gate.set_enabled(True)
    processor = HighFiveFrameProcessor(
        Detector(), gate,
        vision_point_host="127.0.0.1",
        vision_point_port=10000,
        stable_frames=5,
        sample_seconds=0.05,
    )

    processor.process(Frame())

    assert processor.last_position == (2, 3)
    assert processor.last_detection == HandDetection(
        center=(500, 300), box=(440, 220, 560, 360), confidence=0.91
    )


def test_unified_processor_skips_hand_inference_when_high_five_control_is_idle() -> None:
    class Detector:
        calls = 0

        def detect(self, _frame):
            self.calls += 1
            return HandDetection(center=(100, 100), box=(50, 50, 150, 150), confidence=0.8)

    class Frame:
        shape = (400, 600, 3)

    detector = Detector()
    processor = HighFiveFrameProcessor(
        detector, HandRecognitionGate(),
        vision_point_host="127.0.0.1",
        vision_point_port=10000,
        stable_frames=5,
        sample_seconds=0.05,
    )

    hand_only_active = processor.process(Frame())

    assert hand_only_active is False
    assert detector.calls == 0
    assert processor.last_position is None
    assert processor.last_detection is None


def test_hand_detector_returns_landmark_bounds_and_confidence() -> None:
    points = [
        SimpleNamespace(x=0.20, y=0.25),
        SimpleNamespace(x=0.50, y=0.50),
        SimpleNamespace(x=0.40, y=0.75),
    ]
    detector = HandDetector.__new__(HandDetector)
    detector._last_timestamp_ms = -1
    detector._mp = SimpleNamespace(
        ImageFormat=SimpleNamespace(SRGB="SRGB"),
        Image=lambda **kwargs: kwargs,
    )
    detector._landmarker = SimpleNamespace(
        detect_for_video=lambda _image, _timestamp: SimpleNamespace(
            hand_landmarks=[points],
            handedness=[[SimpleNamespace(score=0.93)]],
        )
    )

    result = detector.detect(np.zeros((400, 600, 3), dtype=np.uint8))

    assert result is not None
    assert result.center == (220, 200)
    assert result.box[0] < 120 < result.box[2]
    assert result.box[1] < 100 < result.box[3]
    assert result.confidence == 0.93


def test_hand_detector_initialization_does_not_attempt_the_fibo_model(
    tmp_path, monkeypatch
) -> None:
    import multimodal.high_five_vision_runtime as runtime

    hand_model = tmp_path / "hand_landmarker.task"
    hand_model.write_bytes(b"model")
    fibo_attempts: list[tuple] = []

    class UnexpectedFibo:
        def __init__(self, *args):
            fibo_attempts.append(args)
            raise RuntimeError("fibo must not be used")

    fake_mp = SimpleNamespace(
        tasks=SimpleNamespace(
            BaseOptions=lambda **kwargs: kwargs,
            vision=SimpleNamespace(
                RunningMode=SimpleNamespace(VIDEO="VIDEO"),
                HandLandmarkerOptions=lambda **kwargs: kwargs,
                HandLandmarker=SimpleNamespace(
                    create_from_options=lambda _options: SimpleNamespace()
                ),
            ),
        )
    )
    monkeypatch.setattr(runtime, "_FiboHandDetector", UnexpectedFibo)
    monkeypatch.setitem(sys.modules, "mediapipe", fake_mp)

    HandDetector(hand_model, max_hands=2, threshold=0.5)

    assert fibo_attempts == []


def test_fibo_hand_detection_maps_the_highest_confidence_box_to_existing_contract() -> None:
    objects = [
        SimpleNamespace(score=0.51, bbox=SimpleNamespace(x=10, y=20, w=40, h=60)),
        SimpleNamespace(score=0.93, bbox=SimpleNamespace(x=100, y=120, w=80, h=40)),
    ]

    result = fibo_hand_detection_from_objects(objects, width=300, height=200)

    assert result == HandDetection(
        center=(140, 140), box=(100, 120, 180, 160), confidence=0.93
    )


def test_fibo_hand_detection_clamps_its_box_to_the_camera_frame() -> None:
    objects = [SimpleNamespace(score=0.8, bbox=SimpleNamespace(x=-5, y=180, w=40, h=50))]

    result = fibo_hand_detection_from_objects(objects, width=300, height=200)

    assert result == HandDetection(center=(17, 189), box=(0, 180, 35, 199), confidence=0.8)


def test_fibo_result_with_a_detection_count_but_no_python_coordinates_requires_fallback() -> None:
    assert fibo_result_requires_fallback(count=1, detection=None) is True
    assert fibo_result_requires_fallback(
        count=1,
        detection=HandDetection(center=(2, 2), box=(1, 1, 3, 3), confidence=0.9),
    ) is False
    assert fibo_result_requires_fallback(count=0, detection=None) is False


def test_follow_dispatch_requires_an_accepted_arm_receipt() -> None:
    accepted, status = follow_dispatch_accepted(
        {
            "ok": True,
            "hardware_feedback": {
                "ok": True,
                "queue_status": "follow_redirect_accepted",
            },
        }
    )
    assert accepted is True
    assert status == "follow_redirect_accepted"

    accepted, status = follow_dispatch_accepted(
        {
            "ok": True,
            "hardware_feedback": {
                "ok": False,
                "error": "follow_redirect_limit",
            },
        }
    )
    assert accepted is False
    assert status == "follow_redirect_limit"


def test_follow_window_keeps_camera_open_for_a_later_stable_position() -> None:
    window = FollowInputWindow()

    window.observe_action(100.0)
    assert window.should_close(100.0 + FOLLOW_INPUT_WINDOW_SECONDS - 0.01) is False
    assert window.should_close(100.0 + FOLLOW_INPUT_WINDOW_SECONDS) is True

    window.reset()
    window.observe_action(200.0)
    # A different stable grid arriving during the extended-arm interaction
    # resets the visual input window instead of closing after the first point.
    window.observe_action(203.0)
    assert window.should_close(203.0 + FOLLOW_INPUT_WINDOW_SECONDS - 0.01) is False


def test_vision_waits_for_the_configured_six_point_endpoint() -> None:
    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        wait_for_vision_point_endpoint(host, port, timeout_seconds=0.5)
        thread.join(timeout=1.0)


def test_vision_rejects_a_non_loopback_control_endpoint() -> None:
    control = HandControlServer(HandRecognitionGate(), "0.0.0.0", 10001)

    try:
        control.start()
    except ValueError as exc:
        assert str(exc) == "hand_control_host_must_be_loopback"
    else:
        raise AssertionError("non-loopback control endpoint must be rejected")


def test_hand_recognition_status_exposes_only_control_state() -> None:
    gate = HandRecognitionGate()

    idle = gate.status(now=100.0)
    enabled, generation = gate.set_enabled(True)
    active = gate.status()
    gate.set_enabled(False)
    completed = gate.status()

    assert idle == {
        "hand_recognition_enabled": False,
        "generation": 0,
        "enabled_seconds": 0.0,
        "follow_start_count": 0,
        "follow_redirect_count": 0,
        "last_follow_seconds_ago": None,
    }
    assert enabled is True
    assert generation == 1
    assert active["hand_recognition_enabled"] is True
    assert active["generation"] == 1
    assert set(active) == {
        "hand_recognition_enabled",
        "generation",
        "enabled_seconds",
        "follow_start_count",
        "follow_redirect_count",
        "last_follow_seconds_ago",
    }
    assert completed["hand_recognition_enabled"] is False
    assert completed["generation"] == 2


def test_hand_recognition_status_counts_only_high_level_accepted_follow_actions() -> None:
    gate = HandRecognitionGate()
    gate.set_enabled(True)
    gate.record_follow_action("follow_start", now=100.0)
    gate.record_follow_action("follow_redirect", now=102.0)
    gate.record_follow_action("untrusted_raw_point", now=103.0)

    status = gate.status(now=103.5)

    assert status["follow_start_count"] == 1
    assert status["follow_redirect_count"] == 1
    assert status["last_follow_seconds_ago"] == 1.5
