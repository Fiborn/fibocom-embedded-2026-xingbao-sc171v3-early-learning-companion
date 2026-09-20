import importlib.util
from pathlib import Path


def _load_touch_scene_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "components"
        / "touch_ui"
        / "src"
        / "scene_animation.py"
    )
    spec = importlib.util.spec_from_file_location("touch_scene_animation", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_missing_scene_resource_keeps_default_animation(tmp_path):
    module = _load_touch_scene_module()
    animator = module.SceneAnimator(tmp_path)

    assert animator.set_scene(12) is False
    assert animator.active_scene_id == 0


def test_scene_frame_size_matches_default_portrait_height_without_distortion():
    module = _load_touch_scene_module()

    assert module.fit_scene_size(512, 256, 310) == (620, 310)
