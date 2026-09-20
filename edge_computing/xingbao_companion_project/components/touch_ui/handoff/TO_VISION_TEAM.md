# 发给视觉同学的文字

下面这段可以直接转发：

> UI不接收摄像头画面、检测框、人脸图像或置信度，只接收两个0/1结果。第一个值`distance_too_close=1`表示孩子离屏幕太近，UI会提醒坐远一点；第二个值`needs_water=1`表示需要提醒喝水。独立视觉进程请原子写入`xingbao_touch_game/saves/vision_status.json`，建议每0.2—0.5秒更新一次。可以直接复用`VisionStateAdapter.write()`，示例在`examples/vision_writer_example.py`。

## 推荐代码

```python
from pathlib import Path
from src.desktop_integrations import VisionStateAdapter

writer = VisionStateAdapter(Path("saves/vision_status.json"))

# OpenCV每次推理完成后调用：
writer.write(distance_too_close, needs_water)
```

写出的JSON如下：

```json
{
  "distance_too_close": 0,
  "needs_water": 1
}
```

如果视觉模型与桌面在同一Python进程，也可直接调用：

```python
desktop.update_vision_state(distance_too_close, needs_water)
```

## 联调验收

1.写入`[0,0]`，桌面不弹提醒。
2.写入`[1,0]`，桌面提醒坐远一点。
3.写入`[0,1]`，桌面提醒喝水。
4.写入`[1,1]`，桌面同时提醒坐远和喝水。
5.视觉进程退出后，UI仍能继续运行。

## 隐私边界

- 不把原始相机帧写入UI项目。
- 不把人脸、姓名、学校、位置等信息写入`saves/`。
- 视觉日志只保留调试所需的非敏感数值，正式演示时关闭模型调试窗口。
