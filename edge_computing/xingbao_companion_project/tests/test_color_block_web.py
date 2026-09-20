from pathlib import Path


def test_color_block_web_ui_contains_game_surfaces() -> None:
    html = Path("web/color_block_game.html").read_text(encoding="utf-8")

    assert "星宝色块牌阵" in html
    assert "星光线" in html
    assert "守护线" in html
    assert 'id="childSlots"' in html
    assert 'id="xingbaoSlots"' in html
    assert 'class="avatar listening"' in html
    assert 'id="micButton"' in html
    assert "function parseCommand" in html
    assert "function childPlay" in html
    assert "function xingbaoTurn" in html
    assert "selectedColor" in html
    assert "function selectColor" in html
    assert "function placeSelectedOnLane" in html
    assert "data-lane" in html
    assert "childHint" in html
