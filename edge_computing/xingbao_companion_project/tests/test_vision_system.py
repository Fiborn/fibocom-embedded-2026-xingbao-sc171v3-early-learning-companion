import json

import pytest

import multimodal.vision_system.app as vision_app
from multimodal.high_five_vision_runtime import HandDetection

from multimodal.vision_system.app import (
    Box,
    DrinkReminderStatus,
    HydrationInferenceScheduler,
    draw_six_point_grid,
    emotion_countdown_seconds,
    emotion_inference_due,
    draw_hand_detection,
    mirror_for_display,
    mirror_box_for_display,
    EmotionResult,
    FaceDistanceEstimator,
    MediaPipeFaceDetector,
    FaceResult,
    ReturnCodeStatus,
    camera_source_candidates,
    face_inference_due,
    prepare_hsemotion_b0_input,
    fibo_faces_from_objects,
    fibo_objects_to_results,
    non_hand_inference_paused,
    result_to_json,
    six_point_grid_rectangles,
)


def test_hand_interaction_pauses_all_non_hand_inference() -> None:
    assert non_hand_inference_paused(hand_interaction_active=True) is True
    assert non_hand_inference_paused(hand_interaction_active=False) is False


def test_emotion_inference_uses_its_own_five_minute_schedule() -> None:
    assert emotion_inference_due(
        now=0.0, last_inference_time=float("-inf"), interval_seconds=300.0
    )
    assert not emotion_inference_due(
        now=299.9, last_inference_time=0.0, interval_seconds=300.0
    )
    assert emotion_inference_due(
        now=300.0, last_inference_time=0.0, interval_seconds=300.0
    )


def test_emotion_countdown_counts_down_to_the_next_five_minute_inference() -> None:
    assert emotion_countdown_seconds(
        now=0.0, last_inference_time=float("-inf"), interval_seconds=300.0
    ) is None
    assert emotion_countdown_seconds(
        now=0.0, last_inference_time=0.0, interval_seconds=300.0
    ) == 300
    assert emotion_countdown_seconds(
        now=0.1, last_inference_time=0.0, interval_seconds=300.0
    ) == 300
    assert emotion_countdown_seconds(
        now=299.1, last_inference_time=0.0, interval_seconds=300.0
    ) == 1
    assert emotion_countdown_seconds(
        now=300.0, last_inference_time=0.0, interval_seconds=300.0
    ) == 0


def test_hsemotion_b0_preprocessing_uses_rgb_imagenet_input() -> None:
    bgr = vision_app.np.zeros((12, 18, 3), dtype=vision_app.np.uint8)
    prepared = prepare_hsemotion_b0_input(bgr)

    assert prepared.shape == (1, 3, 224, 224)
    assert prepared.dtype == vision_app.np.float32
    assert prepared[0, 0, 0, 0] == pytest.approx(-0.485 / 0.229)
    assert prepared[0, 1, 0, 0] == pytest.approx(-0.456 / 0.224)
    assert prepared[0, 2, 0, 0] == pytest.approx(-0.406 / 0.225)


def test_vision_defaults_to_the_legacy_close_range_mediapipe_face_model() -> None:
    args = vision_app.build_parser().parse_args([])

    assert args.face_model_selection == 0
    assert MediaPipeFaceDetector.__name__ == "MediaPipeFaceDetector"


def test_distance_estimator_keeps_original_monocular_contract() -> None:
    estimator = FaceDistanceEstimator(
        known_face_width_m=0.16,
        horizontal_fov_deg=70.0,
        focal_px=640.0,
        smoothing=0.35,
    )

    distance = estimator.estimate(frame_width_px=640, face_width_px=160)

    assert distance == 0.64
    assert estimator.band(distance) == "middle"


def test_six_point_grid_rectangles_cover_the_complete_camera_frame() -> None:
    cells = six_point_grid_rectangles(frame_width=600, frame_height=400)

    assert cells == {
        (1, 1): Box(0, 0, 200, 200),
        (1, 2): Box(200, 0, 400, 200),
        (1, 3): Box(400, 0, 600, 200),
        (2, 1): Box(0, 200, 200, 400),
        (2, 2): Box(200, 200, 400, 400),
        (2, 3): Box(400, 200, 600, 400),
    }


def test_six_point_grid_draws_six_cells_and_highlights_selected_hand_cell() -> None:
    frame = vision_app.np.zeros((400, 600, 3), dtype=vision_app.np.uint8)

    draw_six_point_grid(frame, selected_position=(2, 3))

    assert frame[200, 300].any()  # centre divider
    assert frame[300, 500].any()  # selected cell overlay
    assert not frame[100, 100].any()  # unselected cell interior remains clear


def test_hand_detection_draws_a_box_and_center_point() -> None:
    frame = vision_app.np.zeros((400, 600, 3), dtype=vision_app.np.uint8)

    draw_hand_detection(
        frame,
        HandDetection(center=(300, 200), box=(240, 140, 360, 260), confidence=0.91),
    )

    assert frame[140, 240].any()
    assert frame[200, 300].any()


def test_fibo_yolo_results_recursively_unwrap_and_keep_the_bottle() -> None:
    assert vision_app.DRINK_CONTAINER_NAMES == frozenset({"bottle", "cup"})
    raw = [
        [
            type("Object", (), {
                "label": "bottle", "class_id": 39, "score": 0.81,
                "bbox": type("Box", (), {"x": 10, "y": 20, "w": 30, "h": 40})(),
            })(),
            type("Object", (), {
                "label": "person", "class_id": 0, "score": 0.95,
                "bbox": type("Box", (), {"x": 50, "y": 60, "w": 70, "h": 80})(),
            })(),
        ]
    ]

    results = fibo_objects_to_results(raw, priority_names={"cup", "bottle"}, cup_only=True)

    assert results == [
        vision_app.ObjectResult(
            box=Box(10, 20, 40, 60),
            class_id=39,
            name="bottle",
            confidence=0.81,
            is_priority=True,
        )
    ]


def test_fibo_face_results_keep_the_highest_score_face_box() -> None:
    raw = [[
        type("Object", (), {
            "score": 0.92,
            "bbox": type("Box", (), {"x": 40, "y": 60, "w": 80, "h": 100})(),
        })(),
        type("Object", (), {
            "score": 0.98,
            "bbox": type("Box", (), {"x": 100, "y": 120, "w": 140, "h": 160})(),
        })(),
    ]]
    estimator = FaceDistanceEstimator(
        known_face_width_m=0.16,
        horizontal_fov_deg=70.0,
        focal_px=640.0,
        smoothing=1.0,
    )

    faces = fibo_faces_from_objects(
        raw,
        frame_width=640,
        frame_height=480,
        min_face_px=60,
        confidence_threshold=0.50,
        distance_estimator=estimator,
    )

    assert len(faces) == 1
    assert faces[0].box == Box(100, 120, 240, 280)
    assert faces[0].distance_m == pytest.approx(640.0 * 0.16 / 140.0)


def test_fibo_face_results_ignore_low_confidence_and_small_boxes() -> None:
    raw = [[
        type("Object", (), {
            "score": 0.99,
            "bbox": type("Box", (), {"x": 1, "y": 2, "w": 30, "h": 70})(),
        })(),
        type("Object", (), {
            "score": 0.20,
            "bbox": type("Box", (), {"x": 3, "y": 4, "w": 80, "h": 90})(),
        })(),
    ]]
    estimator = FaceDistanceEstimator(0.16, 70.0, 640.0, 1.0)

    assert fibo_faces_from_objects(
        raw,
        frame_width=640,
        frame_height=480,
        min_face_px=60,
        confidence_threshold=0.50,
        distance_estimator=estimator,
    ) == []


def test_face_inference_due_runs_once_at_each_configured_interval() -> None:
    assert face_inference_due(now=0.0, last_inference_time=float("-inf"), interval_seconds=300.0)
    assert not face_inference_due(now=299.9, last_inference_time=0.0, interval_seconds=300.0)
    assert face_inference_due(now=300.0, last_inference_time=0.0, interval_seconds=300.0)


def test_hydration_scheduler_accelerates_on_bottle_and_cools_down_after_drink() -> None:
    scheduler = HydrationInferenceScheduler(
        normal_object_interval_seconds=1.0,
        normal_face_interval_seconds=300.0,
        confirm_interval_seconds=0.8,
        bottle_cooldown_seconds=60.0,
    )

    assert scheduler.object_inference_due(0.0)
    scheduler.record_object_inference(0.0, bottle_detected=True)
    assert scheduler.confirming is True
    assert scheduler.face_inference_due(0.0)
    scheduler.record_face_inference(0.0)
    assert not scheduler.object_inference_due(0.79)
    assert scheduler.object_inference_due(0.8)
    assert not scheduler.face_inference_due(0.79)
    assert scheduler.face_inference_due(0.8)

    assert scheduler.record_drink_reset(1.0) is True
    assert not scheduler.object_inference_due(60.9)
    assert not scheduler.face_inference_due(60.9)
    assert scheduler.object_inference_due(61.0)
    assert not scheduler.face_inference_due(61.0)


def test_unified_vision_defaults_hand_sampling_to_point_eight_seconds() -> None:
    assert vision_app.build_parser().parse_args([]).hand_sample_seconds == 0.8


def test_mirror_for_display_reverses_only_the_horizontal_axis() -> None:
    frame = vision_app.np.array([[[1], [2], [3]], [[4], [5], [6]]], dtype=vision_app.np.uint8)

    mirrored = mirror_for_display(frame)

    assert mirrored.tolist() == [[3, 2, 1], [6, 5, 4]]


def test_mirror_box_for_display_keeps_detection_aligned_with_mirrored_frame() -> None:
    assert mirror_box_for_display(Box(10, 20, 90, 100), frame_width=400) == Box(309, 20, 389, 100)


def test_json_output_keeps_legacy_codes_and_adds_emotion_code() -> None:
    face = FaceResult(
        box=Box(10, 10, 100, 100),
        distance_m=0.32,
        distance_band="close",
    )
    emotion = EmotionResult(
        face_index=0,
        box=face.box,
        label="sadness",
        display_name="sad",
        confidence=0.84,
        return_code=2,
        confirmed=True,
    )
    return_status = ReturnCodeStatus(
        code=1,
        smoothed_distance_m=0.32,
        close_seconds=2.2,
        face_presence_ratio=0.95,
        face_window_seconds=1200.0,
        face_seen_seconds=1140.0,
    )
    drink_status = DrinkReminderStatus(
        enabled=True,
        overlap_now=False,
        alert=True,
        seconds_since_overlap=1201.0,
        seconds_until_alert=0.0,
        bottle_count=0,
        face_count=1,
    )

    payload = json.loads(
        result_to_json(
            12,
            18.5,
            [face],
            [],
            [emotion],
            drink_status,
            return_status,
        )
    )

    assert payload["return_code"] == 1
    assert payload["drink_return_code"] == 1
    assert payload["emotion_return_code"] == 2
    assert payload["emotions"][0]["label"] == "sadness"
    assert payload["faces"][0]["distance_m"] == 0.32


def test_camera_candidates_recover_after_usb_index_changes(monkeypatch) -> None:
    monkeypatch.setattr(vision_app.platform, "system", lambda: "Windows")

    assert camera_source_candidates(4, [5, 6]) == [4, 5, 6]
    assert camera_source_candidates("auto", [5, 6]) == [5, 6]
    assert camera_source_candidates("sample.avi", [5, 6]) == ["sample.avi"]


def test_linux_camera_candidates_use_explicit_v4l_paths(monkeypatch) -> None:
    monkeypatch.setattr(vision_app.platform, "system", lambda: "Linux")

    assert camera_source_candidates("auto", [5, 6]) == [
        "/dev/video5",
        "/dev/video6",
    ]
    assert camera_source_candidates(4, [5]) == ["/dev/video4", "/dev/video5"]


def test_capture_open_falls_back_to_reenumerated_camera(monkeypatch) -> None:
    opened: list[int | str] = []
    released: list[int | str] = []

    class FakeCapture:
        def __init__(self, source: int | str) -> None:
            self.source = source

        def isOpened(self) -> bool:
            return True

        def read(self):
            return self.source == 5, object() if self.source == 5 else None

        def release(self) -> None:
            released.append(self.source)

    monkeypatch.setattr(
        vision_app,
        "camera_source_candidates",
        lambda source: [4, 5],
    )
    monkeypatch.setattr(
        vision_app,
        "open_capture",
        lambda source, width, height: opened.append(source) or FakeCapture(source),
    )

    capture, active_source = vision_app.open_capture_with_fallback(4, 640, 480)

    assert capture is not None
    assert active_source == 5
    assert opened == [4, 5]
    assert released == [4]
