"""视觉同学可直接复制：只向UI提供两个0/1结果。"""

import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.desktop_integrations import VisionStateAdapter


writer = VisionStateAdapter(ROOT / "saves" / "vision_status.json")


def publish_vision_result(distance_too_close, needs_water):
    """第一个值为1提醒坐远；第二个值为1提醒喝水。"""
    return writer.write(distance_too_close, needs_water)


if __name__ == "__main__":
    # 联调示例：实际使用时，把这里替换成OpenCV模型的两个输出。
    while True:
        model_result_1 = 0
        model_result_2 = 0
        publish_vision_result(model_result_1, model_result_2)
        time.sleep(0.3)
