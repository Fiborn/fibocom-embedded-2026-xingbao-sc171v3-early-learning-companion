from datetime import datetime, timedelta

from core.scene_animation import (
    SCENE_CATALOG,
    SceneMarkerStreamFilter,
    ScenePriorityController,
    SceneTurnSelector,
    extract_scene_marker,
)


def test_scene_marker_is_removed_before_child_facing_text():
    clean_text, scene_id = extract_scene_marker("好呀，我们一起吃面条吧。[[XINGBAO_SCENE:12]]")

    assert clean_text == "好呀，我们一起吃面条吧。"
    assert scene_id == 12


def test_invalid_or_multiple_markers_fall_back_to_default_scene():
    assert extract_scene_marker("你好[[XINGBAO_SCENE:28]]") == ("你好", 0)
    assert extract_scene_marker("你好[[XINGBAO_SCENE:1]][[XINGBAO_SCENE:2]]") == ("你好", 0)


def test_duplicate_user_turn_keeps_previous_nonzero_scene():
    selector = SceneTurnSelector()

    assert selector.select("我想吃面条", "好呀[[XINGBAO_SCENE:12]]") == ("好呀", 12)
    assert selector.select("我想吃面条", "换一个[[XINGBAO_SCENE:3]]") == ("换一个", 12)


def test_stream_filter_decides_prefix_scene_before_releasing_tts_text():
    stream = SceneMarkerStreamFilter()

    chunks = [
        stream.feed("[[XINGBAO_"),
        stream.feed("SCENE:12]]好呀，我们一起吃面条吧。"),
    ]

    assert stream.scene_id == 12
    assert stream.scene_decided is True
    assert "".join(chunks) == "好呀，我们一起吃面条吧。"


def test_stream_filter_removes_short_prefix_marker_before_releasing_tts_text():
    stream = SceneMarkerStreamFilter()

    chunks = [
        stream.feed("[[3"),
        stream.feed("]]明天北京有雷阵雨，出门记得带伞。"),
    ]

    assert stream.scene_id == 3
    assert stream.scene_decided is True
    assert "".join(chunks) == "明天北京有雷阵雨，出门记得带伞。"


def test_short_scene_marker_is_removed_from_non_streaming_text():
    assert extract_scene_marker("[[19]]明天有雷阵雨。") == ("明天有雷阵雨。", 19)


def test_catalog_contains_each_of_the_twenty_seven_scene_ids():
    assert set(SCENE_CATALOG) == set(range(1, 28))
    assert SCENE_CATALOG[19] == "雨天撑伞"
    assert SCENE_CATALOG[20] == "堆雪人"
    assert SCENE_CATALOG[22] == "晚安睡觉"
    assert SCENE_CATALOG[25] == "机械臂互动"
    assert SCENE_CATALOG[26] == "爱心互动"
    assert SCENE_CATALOG[27] == "认真倾听"


def test_scene_prompt_uses_heart_comfort_for_a_childs_sad_or_angry_feelings():
    from core.scene_animation import scene_catalog_prompt

    prompt = scene_catalog_prompt()
    assert "难过或生气时必须选3" in prompt
    assert "不得选6或7" in prompt


def test_scene_prompt_forbids_thinking_scene_for_resolved_weather_queries():
    from core.scene_animation import scene_catalog_prompt

    prompt = scene_catalog_prompt()

    assert "已取得天气结果时不得选5" in prompt
    assert "雨或雷阵雨选19，下雪选20" in prompt
    assert "仅查询失败、超出预报范围或结果不确定时才可选5" in prompt


def test_scene_prompt_exposes_new_interaction_scenes_and_arm_rule():
    from core.scene_animation import scene_catalog_prompt

    prompt = scene_catalog_prompt()

    assert "n 只能是0到27" in prompt
    assert "25=机械臂互动" in prompt
    assert "26=爱心互动" in prompt
    assert "27=认真倾听" in prompt
    assert "击击掌时必须选25" in prompt


def test_night_scene_returns_only_after_ten_idle_minutes():
    controller = ScenePriorityController()
    session_end = datetime(2026, 8, 21, 23, 0, 0)
    assert controller.on_session_end(session_end) == 0

    assert controller.poll_idle(session_end + timedelta(minutes=9, seconds=59)) == 0
    assert controller.poll_idle(session_end + timedelta(minutes=10)) == 22
    assert controller.on_wake(session_end + timedelta(minutes=11)) == 1
