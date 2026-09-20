import json

from core.agent_preferences import load_agent_city
from core.settings import AppSettings
from intelligence.realtime_tools import RealtimeInfoTools


def test_agent_city_uses_parent_preference_file(tmp_path) -> None:
    path = tmp_path / "agent_preferences.json"
    path.write_text(json.dumps({"weather_city": "上海"}, ensure_ascii=False), encoding="utf-8")

    settings = AppSettings(
        agent_default_city="杭州",
        agent_preferences_path=str(path),
    )
    tools = RealtimeInfoTools(settings, object())  # type: ignore[arg-type]

    assert load_agent_city(path, "杭州") == "上海"
    assert tools.default_city == "上海"
