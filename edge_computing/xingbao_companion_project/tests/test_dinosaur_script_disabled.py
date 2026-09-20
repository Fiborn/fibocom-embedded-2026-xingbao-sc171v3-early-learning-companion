from pathlib import Path

from app import XingbaoApp
from core.memory import MemoryManager
from core.session import SessionManager


def test_dinosaur_script_has_no_voice_or_followup_entrypoints(tmp_path: Path) -> None:
    app = XingbaoApp(
        session=SessionManager(memory_manager=MemoryManager(tmp_path / "memory.json"))
    )

    assert app.handle_guided_expression_text("我叫小宇，我喜欢恐龙") is None
    assert app.request_guided_expression_recovery()["reason"] == "dinosaur_script_disabled"
    assert app.request_scripted_followup("drawing_consent")["reason"] == "dinosaur_script_disabled"
    assert app._looks_like_guided_expression_candidate("我叫小宇，我喜欢恐龙") is False
    assert app._llm_dinosaur_script_fallback("我叫小宇，我喜欢恐龙") == ""
