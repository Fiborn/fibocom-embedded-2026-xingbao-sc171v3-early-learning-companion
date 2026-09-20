"""星宝正式视觉运行包。

OpenCV、Ultralytics 等可选依赖只在运行 ``app`` 时加载，普通语音、
触控和文本模式不会因为视觉依赖未安装而受到影响。
"""

__all__ = ["__version__"]

__version__ = "2026.07.24-emotion"
