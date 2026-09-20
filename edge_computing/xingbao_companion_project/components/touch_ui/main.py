import argparse
import json
from pathlib import Path

from src.app import XingbaoApp
from src.soak import run_soak_test
from src.demo_timing import normalize_demo_speed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="星宝陪伴桌V2：触控屏小游戏中心")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--window", action="store_true", help="兼容旧命令；正式界面仍保持全屏")
    mode.add_argument("--fullscreen", action="store_true", help="全屏模式，适合板卡触控屏")
    parser.add_argument("--width", type=int, default=1280, help="窗口宽度")
    parser.add_argument("--height", type=int, default=720, help="窗口高度")
    parser.add_argument("--log-dir", default="logs", help="JSONL日志目录")
    parser.add_argument("--snapshot", action="store_true", help="导出主页、游戏页和报告页截图")
    parser.add_argument("--soak-test", action="store_true", help="运行无GUI自动化长时间稳定性测试")
    parser.add_argument("--rounds", type=int, default=100, help="长时间测试模拟的正确答题轮数")
    parser.add_argument("--low-effects", action="store_true", help="降低粒子数量并关闭扫描线")
    parser.add_argument("--demo-speed", default="slow", help="演示速度：normal或slow，默认slow")
    parser.add_argument("--save-dir", default="saves", help="本地自动存档目录")
    parser.add_argument("--debug-layout", action="store_true", help="显示点击目标和布局调试边框")
    args = parser.parse_args(argv)
    normalized = normalize_demo_speed(args.demo_speed)
    if normalized != str(args.demo_speed).lower():
        print("提示：未知演示速度{}，已使用slow。".format(args.demo_speed))
    args.demo_speed = normalized
    return args


def main():
    args = parse_args()
    if args.snapshot:
        from tools.render_snapshots import main as render_snapshot_main

        render_snapshot_main()
        raise SystemExit(0)
    if args.soak_test:
        report = run_soak_test(
            rounds=args.rounds,
            log_dir=Path(args.log_dir),
            size=(args.width, args.height),
            save_dir=Path(args.save_dir),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["passed"] else 1)

    fullscreen = True
    app = XingbaoApp(
        fullscreen=fullscreen,
        size=(args.width, args.height),
        log_dir=Path(args.log_dir),
        low_effects=args.low_effects,
        save_dir=Path(args.save_dir),
        demo_speed=args.demo_speed,
        debug_layout=args.debug_layout,
    )
    app.run()


if __name__ == "__main__":
    main()
