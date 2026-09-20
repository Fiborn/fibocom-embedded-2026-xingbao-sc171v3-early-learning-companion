"""Local-only runtime status used by the status chips."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SystemStatus:
    local_mode: bool = True
    touch_ready: bool = True
    safe_mode: bool = True
    session_active: bool = True
    autosave_enabled: bool = True
    storage_writable: bool = True
    touch_input_mode: str = "mouse_fallback"

    def to_dict(self):
        return {
            "local_mode": self.local_mode,
            "touch_ready": self.touch_ready,
            "safe_mode": self.safe_mode,
            "session_active": self.session_active,
            "autosave_enabled": self.autosave_enabled,
            "storage_writable": self.storage_writable,
            "touch_input_mode": self.touch_input_mode,
        }

    def get_chip_states(self):
        return [
            {
                "key": "LOCAL",
                "label": "本地",
                "active": bool(self.local_mode),
                "meaning": "本地运行模式：游戏、日志和存档都保存在本机，不上传儿童数据。",
            },
            {
                "key": "TOUCH",
                "label": "触控",
                "active": bool(self.touch_ready),
                "meaning": "触控就绪：触控屏点击可用，电脑调试时鼠标点击等价于触控。",
            },
            {
                "key": "SAFE",
                "label": "安全",
                "active": bool(self.safe_mode),
                "meaning": "儿童安全演示：不采集人脸，不连接云端，只保存本地成长数值。",
            },
        ]

    def top_bar_label(self):
        session = "运行中" if self.session_active else "未运行"
        touch = "触控就绪" if self.touch_ready else "触控未连接"
        local = "本地模式" if self.local_mode else "本地异常"
        return "{}  ·  {}  ·  {}".format(local, touch, session)
