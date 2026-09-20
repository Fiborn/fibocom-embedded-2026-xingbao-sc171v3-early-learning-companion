"""Safe, read-only real-time tools available to Xingbao's LLM agent."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

try:  # Python 3.9+; the deployed board still has Python 3.8 in some images.
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - depends on the deployed interpreter
    ZoneInfo = None  # type: ignore[assignment,misc]

from core.network import NetworkClient
from core.agent_preferences import load_agent_city
from core.settings import AppSettings, get_qweather_api_key


class RealtimeInfoTools:
    """Expose whitelisted time and weather data without device location access."""

    def __init__(
        self,
        settings: AppSettings,
        network_client: NetworkClient,
    ) -> None:
        self.settings = settings
        self.network_client = network_client

    @staticmethod
    def definitions() -> list[dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "获取当前本地日期、星期和时间。用户询问现在几点、今天几号或星期几时调用。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "获取指定城市的实时天气，包含温度、体感温度、相对湿度、风速和天气状况。用户询问现在、今天的天气、温度、湿度、下雨或出门建议时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "城市名；未指定时使用家长设置的默认城市。",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather_alert",
                    "description": "获取指定城市当前仍生效的官方天气灾害预警。用户询问天气预警、暴雨预警、雷暴预警、大风预警、台风预警或是否有警报时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "城市名；未指定时使用家长设置的默认城市。",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_historical_weather",
                    "description": "获取指定城市过去的历史天气。用户询问昨天、前天或最近10天内某天的天气、温度、湿度或下雨情况时调用；days_ago=1 表示昨天，最大为10。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "城市名；未指定时使用家长设置的默认城市。",
                            },
                            "days_ago": {
                                "type": "integer",
                                "description": "距今天过去的天数：昨天填1，前天填2；最大填10。",
                                "minimum": 1,
                                "maximum": 10,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather_forecast",
                    "description": "获取指定城市未来天气预报。用户询问明天、后天或未来几天天气时必须调用；会返回当天的天气状况、最高最低温、降水概率、风速和湿度范围。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "城市名；未指定时使用家长设置的默认城市。",
                            },
                            "day_offset": {
                                "type": "integer",
                                "description": "距今天的天数：明天填1，后天填2，7天后填7；最多填29（和风天气包含今天共30天）。未指定时填1。",
                                "minimum": 0,
                                "maximum": 29,
                            },
                        },
                    },
                },
            },
        ]
        for name, description in (
            ("get_minutely_precipitation", "查询城市未来两小时分钟降水。用户问马上会不会下雨、雨何时开始或分钟降水时调用。"),
            ("get_lifestyle_indices", "查询城市今天的运动、穿衣和紫外线生活指数。用户问穿什么、适不适合运动或要不要防晒时调用。"),
            ("get_air_quality", "查询城市当前空气质量、AQI和健康建议。用户问空气质量、AQI、雾霾或PM2.5时调用。"),
        ):
            tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": {"city": {"type": "string", "description": "城市名；未指定时使用家长设置的默认城市。"}}}}})
        return tools

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "get_current_time":
            return json.dumps(self.current_time(), ensure_ascii=False)
        if name == "get_current_weather":
            city = str(arguments.get("city") or self.default_city).strip()
            return json.dumps(self.current_weather(city), ensure_ascii=False)
        if name == "get_weather_alert":
            city = str(arguments.get("city") or self.default_city).strip()
            return json.dumps(self.weather_alert(city), ensure_ascii=False)
        if name == "get_minutely_precipitation":
            return json.dumps(self.minutely_precipitation(str(arguments.get("city") or self.default_city).strip()), ensure_ascii=False)
        if name == "get_lifestyle_indices":
            return json.dumps(self.lifestyle_indices(str(arguments.get("city") or self.default_city).strip()), ensure_ascii=False)
        if name == "get_air_quality":
            return json.dumps(self.air_quality(str(arguments.get("city") or self.default_city).strip()), ensure_ascii=False)
        if name == "get_weather_forecast":
            city = str(arguments.get("city") or self.default_city).strip()
            return json.dumps(
                self.weather_forecast(city, _bounded_day_offset(arguments.get("day_offset"))),
                ensure_ascii=False,
            )
        if name == "get_historical_weather":
            city = str(arguments.get("city") or self.default_city).strip()
            return json.dumps(
                self.historical_weather(city, _history_days_ago(arguments.get("days_ago"))),
                ensure_ascii=False,
            )
        return json.dumps({"ok": False, "error": "不支持的工具"}, ensure_ascii=False)

    def current_time(self) -> dict[str, Any]:
        try:
            now = datetime.now(_timezone_for(self.settings.agent_timezone))
        except Exception:
            now = datetime.now().astimezone()
        weekdays = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        return {
            "ok": True,
            "timezone": str(now.tzinfo),
            "date": now.strftime("%Y-%m-%d"),
            "weekday": weekdays[now.weekday()],
            "time": now.strftime("%H:%M"),
        }

    @property
    def default_city(self) -> str:
        return load_agent_city(
            self.settings.agent_preferences_path,
            self.settings.agent_default_city,
        )

    def current_weather(self, city: str) -> dict[str, Any]:
        city = city or self.default_city
        if not city:
            return {"ok": False, "error": "未设置默认天气城市"}
        place, error = self._qweather_city(city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        data = self._qweather_request(
            self._weather_url("/v7/weather/now"),
            {"location": place["id"], "lang": "zh"},
        )
        current = data.get("now") if data.get("code") == "200" else None
        if not isinstance(current, dict):
            return {"ok": False, "city": city, "error": _qweather_error(data)}
        return {
            "ok": True,
            "city": place["name"],
            "country": place["country"],
            "observed_at": str(current.get("obsTime") or ""),
            "condition": str(current.get("text") or "天气状况未知"),
            "temperature_c": _as_number(current.get("temp")),
            "feels_like_c": _as_number(current.get("feelsLike")),
            "relative_humidity_percent": _as_number(current.get("humidity")),
            "wind_speed_kmh": _as_number(current.get("windSpeed")),
        }

    def weather_forecast(self, city: str, day_offset: int = 1) -> dict[str, Any]:
        """Return a date-specific forecast without collecting device location."""
        city = city or self.default_city
        if not city:
            return {"ok": False, "error": "未设置默认天气城市"}
        place, error = self._qweather_city(city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        # 30d covers the supported 0-29 day tool range.  A request outside
        # this range returns an explicit unavailable result, never today.
        data = self._qweather_request(
            self._weather_url("/v7/weather/30d"),
            {"location": place["id"], "lang": "zh"},
        )
        daily = data.get("daily") if data.get("code") == "200" else None
        if not isinstance(daily, list) or day_offset < 0 or day_offset >= len(daily):
            return {"ok": False, "city": city, "error": "暂时没有该日期的天气预报"}
        day = daily[day_offset]
        if not isinstance(day, dict):
            return {"ok": False, "city": city, "error": _qweather_error(data)}
        humidity = _as_number(day.get("humidity"))
        return {
            "ok": True,
            "city": place["name"],
            "country": place["country"],
            "date": str(day.get("fxDate") or ""),
            "day_offset": day_offset,
            "condition": str(day.get("textDay") or day.get("textNight") or "天气状况未知"),
            "temperature_min_c": _as_number(day.get("tempMin")),
            "temperature_max_c": _as_number(day.get("tempMax")),
            "feels_like_min_c": None,
            "feels_like_max_c": None,
            # QWeather daily forecasts provide one daily relative humidity
            # value, not an hourly range.  Keep the existing tool schema by
            # representing that forecast value as both bounds.
            "precipitation_probability_max_percent": None,
            "wind_speed_max_kmh": _as_number(day.get("windSpeedDay")),
            "relative_humidity_min_percent": humidity,
            "relative_humidity_max_percent": humidity,
        }

    def historical_weather(self, city: str, days_ago: int = 1) -> dict[str, Any]:
        """Return QWeather history for yesterday through ten days ago."""
        city = city or self.default_city
        if not city:
            return {"ok": False, "error": "未设置默认天气城市"}
        if days_ago < 1 or days_ago > 10:
            return {"ok": False, "city": city, "error": "历史天气最多可查询10天前"}
        place, error = self._qweather_city(city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        try:
            today = datetime.now(_timezone_for(self.settings.agent_timezone)).date()
        except Exception:
            today = datetime.now().date()
        target_date = today - timedelta(days=days_ago)
        data = self._qweather_request(
            self._weather_url("/v7/historical/weather"),
            {
                "location": place["id"],
                "date": target_date.strftime("%Y%m%d"),
                "lang": "zh",
                "unit": "m",
            },
        )
        daily = data.get("weatherDaily") if data.get("code") == "200" else None
        if not isinstance(daily, dict):
            return {"ok": False, "city": city, "error": _qweather_error(data, fallback="暂无该日期的历史天气")}
        hourly = data.get("weatherHourly")
        conditions = []
        wind_speeds = []
        if isinstance(hourly, list):
            for item in hourly:
                if not isinstance(item, dict):
                    continue
                condition = str(item.get("text") or "").strip()
                if condition and condition not in conditions:
                    conditions.append(condition)
                speed = _as_number(item.get("windSpeed"))
                if speed is not None:
                    wind_speeds.append(speed)
        return {
            "ok": True,
            "city": place["name"],
            "country": place["country"],
            "date": str(daily.get("date") or target_date.isoformat()),
            "days_ago": days_ago,
            "condition": "、".join(conditions) or "历史天气状况暂无记录",
            "temperature_min_c": _as_number(daily.get("tempMin")),
            "temperature_max_c": _as_number(daily.get("tempMax")),
            "relative_humidity_percent": _as_number(daily.get("humidity")),
            "precipitation_mm": _as_number(daily.get("precip")),
            "wind_speed_max_kmh": max(wind_speeds) if wind_speeds else None,
        }

    def weather_alert(self, city: str) -> dict[str, Any]:
        """Return active official alerts for a city without using device location."""
        city = city or self.default_city
        if not city:
            return {"ok": False, "error": "未设置默认天气城市"}
        place, error = self._qweather_city(city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if not latitude or not longitude:
            return {"ok": False, "city": city, "error": "该城市缺少预警查询坐标"}
        data = self._qweather_request(
            self._weather_url(f"/weatheralert/v1/current/{latitude}/{longitude}"),
            {"localTime": "true", "lang": "zh"},
        )
        alerts = data.get("alerts")
        if not isinstance(alerts, list):
            metadata = data.get("metadata")
            if isinstance(metadata, dict) and metadata.get("zeroResult") is True:
                alerts = []
            else:
                return {"ok": False, "city": city, "error": _qweather_error(data, fallback="天气预警服务暂时没有返回数据")}
        prepared: list[dict[str, Any]] = []
        for alert in alerts[:3]:
            if not isinstance(alert, dict):
                continue
            event_type = alert.get("eventType")
            event_name = (
                str(event_type.get("name") or "天气")
                if isinstance(event_type, dict)
                else "天气"
            )
            prepared.append(
                {
                    "event": event_name,
                    "severity": str(alert.get("severity") or ""),
                    "headline": str(alert.get("headline") or ""),
                    "description": str(alert.get("description") or ""),
                    "instruction": str(alert.get("instruction") or ""),
                    "issued_at": str(alert.get("issuedTime") or ""),
                    "expires_at": str(alert.get("expireTime") or ""),
                }
            )
        return {
            "ok": True,
            "city": place["name"],
            "country": place["country"],
            "has_alert": bool(prepared),
            "alert_count": len(prepared),
            "alerts": prepared,
        }

    def minutely_precipitation(self, city: str) -> dict[str, Any]:
        place, error = self._qweather_city(city or self.default_city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        data = self._qweather_request(self._weather_url("/v7/minutely/5m"), {"location": f"{place['longitude']},{place['latitude']}", "lang": "zh"})
        if data.get("code") != "200":
            return {"ok": False, "city": place["name"], "error": _qweather_error(data)}
        return {"ok": True, "city": place["name"], "summary": str(data.get("summary") or ""), "updated_at": str(data.get("updateTime") or "")}

    def lifestyle_indices(self, city: str) -> dict[str, Any]:
        place, error = self._qweather_city(city or self.default_city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        data = self._qweather_request(self._weather_url("/v7/indices/1d"), {"location": place["id"], "type": "1,3,5", "lang": "zh"})
        daily = data.get("daily") if data.get("code") == "200" else None
        if not isinstance(daily, list):
            return {"ok": False, "city": place["name"], "error": _qweather_error(data)}
        return {"ok": True, "city": place["name"], "indices": [{"name": x.get("name"), "category": x.get("category"), "text": x.get("text")} for x in daily if isinstance(x, dict)]}

    def air_quality(self, city: str) -> dict[str, Any]:
        place, error = self._qweather_city(city or self.default_city)
        if place is None:
            return {"ok": False, "city": city, "error": error}
        data = self._qweather_request(self._weather_url(f"/airquality/v1/current/{place['latitude']}/{place['longitude']}"), {"lang": "zh"})
        indexes = data.get("indexes")
        if not isinstance(indexes, list) or not indexes:
            return {"ok": False, "city": place["name"], "error": _qweather_error(data)}
        index = next((x for x in indexes if isinstance(x, dict) and x.get("code") == "cn-mee"), indexes[0])
        health = index.get("health") if isinstance(index, dict) else {}
        return {"ok": True, "city": place["name"], "aqi": index.get("aqiDisplay"), "category": index.get("category"), "primary_pollutant": (index.get("primaryPollutant") or {}).get("name"), "advice": ((health.get("advice") or {}).get("generalPopulation") if isinstance(health, dict) else "")}

    def _qweather_city(self, city: str) -> tuple[dict[str, str] | None, str]:
        data = self._qweather_request(
            self._geo_url("/geo/v2/city/lookup"),
            {"location": city, "number": 1, "lang": "zh"},
        )
        locations = data.get("location") if data.get("code") == "200" else None
        if not isinstance(locations, list) or not locations or not isinstance(locations[0], dict):
            return None, _qweather_error(data, fallback="未找到该城市")
        location = locations[0]
        location_id = str(location.get("id") or "")
        if not location_id:
            return None, "未找到该城市"
        return {
            "id": location_id,
            "name": str(location.get("name") or city),
            "country": str(location.get("country") or ""),
            "latitude": str(location.get("lat") or ""),
            "longitude": str(location.get("lon") or ""),
        }, ""

    def _qweather_request(self, url: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if not url:
            return {
                "code": "config_error",
                "error": "未配置 QWEATHER_API_HOST（请填写和风天气控制台中的 API Host）",
            }
        try:
            return self.network_client.request_json(
                "GET",
                _url_with_query(url, parameters),
                headers={"Accept": "application/json", "X-QW-Api-Key": get_qweather_api_key()},
                timeout=12,
                retries=1,
            )
        except RuntimeError as exc:
            return {"code": "config_error", "error": str(exc)}

    @staticmethod
    def _weather_url(path: str) -> str:
        return os.getenv("QWEATHER_API_HOST", "").strip().rstrip("/") + path if os.getenv("QWEATHER_API_HOST", "").strip() else ""

    @staticmethod
    def _geo_url(path: str) -> str:
        host = os.getenv("QWEATHER_GEO_API_HOST", "").strip()
        if not host:
            host = os.getenv("QWEATHER_API_HOST", "").strip()
        return host.rstrip("/") + path if host else ""


def _url_with_query(base_url: str, parameters: dict[str, Any]) -> str:
    return base_url + "?" + urlencode(
        {key: value for key, value in parameters.items() if value is not None}
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_number(value: Any) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _qweather_error(data: dict[str, Any], fallback: str = "天气服务暂时没有返回数据") -> str:
    code = str(data.get("code") or "")
    if code == "401":
        return "天气服务认证失败"
    if code in {"402", "403", "429"}:
        return "天气服务暂时不可用"
    return str(data.get("error") or fallback)


def _bounded_day_offset(value: Any) -> int:
    try:
        # Do not clamp an unsupported request onto a different date.  The
        # forecast method will return an explicit unavailable result instead.
        return int(value)
    except (TypeError, ValueError):
        return 1


def _history_days_ago(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _daily_value(daily: dict[str, Any], field: str, index: int) -> Any:
    values = daily.get(field)
    return values[index] if isinstance(values, list) and index < len(values) else None


def _hourly_humidity_range(hourly: Any, date: str) -> tuple[Any, Any]:
    if not isinstance(hourly, dict):
        return None, None
    times = hourly.get("time")
    values = hourly.get("relative_humidity_2m")
    if not isinstance(times, list) or not isinstance(values, list):
        return None, None
    readings = [
        value
        for timestamp, value in zip(times, values)
        if str(timestamp).startswith(date) and isinstance(value, (int, float))
    ]
    return (min(readings), max(readings)) if readings else (None, None)


def _timezone_for(name: str) -> Any:
    """Return a board-compatible timezone without adding a package dependency."""
    if ZoneInfo is not None:
        return ZoneInfo(name)
    if name == "Asia/Shanghai":
        return timezone(timedelta(hours=8), name="CST")
    return datetime.now().astimezone().tzinfo
