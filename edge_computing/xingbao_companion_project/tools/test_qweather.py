#!/usr/bin/env python3
"""Manual QWeather connectivity test for Xingbao.

Examples:
    python3 tools/test_qweather.py
    python3 tools/test_qweather.py --city 贵阳 --forecast-days 1

The script reads the same protected runtime.env as the voice launcher.  It
never prints the API key; it only prints the returned, child-facing weather
fields and a useful failure message.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.network import NetworkClient  # noqa: E402
from core.settings import AppSettings  # noqa: E402
from intelligence.realtime_tools import RealtimeInfoTools  # noqa: E402


DEFAULT_ENV_FILE = Path.home() / ".config" / "xingbao" / "runtime.env"


def load_runtime_env(path: Path) -> None:
    """Load simple KEY=VALUE entries without echoing protected values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export ") :].strip()
        if not name or name in os.environ:
            continue
        os.environ[name] = value.strip().strip("\"'")


def main() -> int:
    parser = argparse.ArgumentParser(description="测试星宝的和风天气接口")
    parser.add_argument("--city", default="北京", help="测试城市，默认：北京")
    parser.add_argument(
        "--forecast-days",
        type=int,
        default=1,
        choices=range(0, 30),
        metavar="0-29",
        help="预报距今天的天数，默认：1（明天）",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="运行环境文件路径，默认：~/.config/xingbao/runtime.env",
    )
    parser.add_argument(
        "--history-days-ago",
        type=int,
        choices=range(1, 11),
        metavar="1-10",
        help="额外测试历史天气：1 为昨天，10 为 10 天前",
    )
    args = parser.parse_args()

    load_runtime_env(args.env_file.expanduser())
    host = os.environ.get("QWEATHER_API_HOST", "").strip()
    key_available = bool(os.environ.get("QWEATHER_API_KEY", "").strip())
    print(f"城市：{args.city}")
    print(f"API Host：{host or '未配置'}")
    print(f"API Key：{'已配置（已隐藏）' if key_available else '未配置'}")

    settings = AppSettings.load(PROJECT_ROOT / "config" / "settings.json")
    tools = RealtimeInfoTools(settings, NetworkClient(settings))
    now = tools.current_weather(args.city)
    forecast = tools.weather_forecast(args.city, args.forecast_days)
    print("\n实时天气：")
    print(json.dumps(now, ensure_ascii=False, indent=2))
    print(f"\n天气预报（+{args.forecast_days} 天）：")
    print(json.dumps(forecast, ensure_ascii=False, indent=2))

    history: dict | None = None
    if args.history_days_ago is not None:
        history = tools.historical_weather(args.city, args.history_days_ago)
        print(f"\n历史天气（{args.history_days_ago} 天前）：")
        print(json.dumps(history, ensure_ascii=False, indent=2))

    if now.get("ok") and forecast.get("ok") and (
        history is None or history.get("ok")
    ):
        print("\n结果：和风天气实时与预报接口均可用。")
        return 0
    print("\n结果：至少一个接口不可用，请查看上方 error 字段。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
