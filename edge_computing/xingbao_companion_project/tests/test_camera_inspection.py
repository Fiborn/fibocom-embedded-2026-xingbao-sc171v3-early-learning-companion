import numpy as np
import pytest


class FakeCapture:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.released = False

    def read(self):
        try:
            return next(self.frames)
        except StopIteration:
            return False, None

    def release(self):
        self.released = True


def test_capture_returns_bounded_jpeg_data_uri_and_releases(monkeypatch):
    import intelligence.camera_inspection as module

    capture = FakeCapture([(True, np.zeros((900, 1800, 3), dtype=np.uint8))])
    monkeypatch.setattr(module.cv2, "VideoCapture", lambda _source: capture)

    snapshot = module.capture_current_camera_frame(timeout_seconds=0.1)

    assert snapshot.data_uri.startswith("data:image/jpeg;base64,")
    assert max(snapshot.width, snapshot.height) == 1024
    assert capture.released is True


def test_capture_raises_timeout_without_valid_frame(monkeypatch):
    import intelligence.camera_inspection as module

    capture = FakeCapture([(False, None)])
    monkeypatch.setattr(module.cv2, "VideoCapture", lambda _source: capture)

    with pytest.raises(module.CameraInspectionError, match="camera_frame_timeout"):
        module.capture_current_camera_frame(timeout_seconds=0.01)

    assert capture.released is True
