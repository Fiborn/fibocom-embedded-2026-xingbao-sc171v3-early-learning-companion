from pathlib import Path


def test_board_git_setup_is_gated_and_separate_from_runtime() -> None:
    script = Path("deploy/setup_board_git_server.sh").read_text(encoding="utf-8")

    assert "XINGBAO_BOARD_BASELINE_AUDITED" in script
    assert "/home/fibo/xingbao_git" in script
    assert "git init --bare" in script
    assert "xingbao_companion" not in script


def test_board_git_setup_protects_history_and_main() -> None:
    script = Path("deploy/setup_board_git_server.sh").read_text(encoding="utf-8")
    hook = Path("deploy/hooks/xingbao-pre-receive").read_text(encoding="utf-8")

    assert "receive.denyNonFastForwards true" in script
    assert "receive.denyDeletes true" in script
    assert "Published tags are immutable" in hook
    assert "Direct updates to main are disabled" in hook
