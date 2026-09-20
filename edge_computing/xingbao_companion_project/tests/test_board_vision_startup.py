from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_full_demo_gives_camera_to_central_vision_only() -> None:
    script = (PROJECT_ROOT / "deploy" / "board_start_full_demo.sh").read_text(
        encoding="utf-8"
    )
    wrapper = (PROJECT_ROOT / "tools" / "board_phase1_ui.py").read_text(
        encoding="utf-8"
    )

    assert "pkill -f '[v]ision_system.app'" in script
    assert "'$UI_WRAPPER' --ui-dir '$UI_DIR'" in script
    assert '"--no-vision"' in wrapper
    assert '"--no-central-bridge"' in wrapper
