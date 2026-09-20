#视觉模型接入说明

视觉发布包已经放入`integrations/vision_release`，桌面程序启动时会自动启动视觉进程，不需要再单独打开视觉窗口。

启动方式：

```bash
python desktop.py
```

切换摄像头：

```bash
python desktop.py --camera-source 1
```

调试时关闭视觉：

```bash
python desktop.py --no-vision
```

数据流为：视觉模型逐帧输出JSON，`src/vision_bridge.py`读取JSON并转换为两个UI标志位，然后原子写入`saves/vision_status.json`，桌面读取该文件并显示提醒。

映射规则：

-`return_code=1`转换为`distance_too_close=1`，提醒孩子离屏幕远一点。
-`drink_return_code=1`转换为`needs_water=1`，提醒孩子喝水。
-`return_code=2`表示长时间检测到人脸，不等于距离过近，目前不会错误触发距离提醒。
-视觉进程停止或异常退出时，两个状态自动清零，防止残留旧提醒。

PC版本依赖`opencv-python`、`ultralytics`、`torch`和`numpy`。SC171V3正式部署时，发布包说明要求将YOLO推理部分替换为板卡NPU接口；JSON字段和UI桥接层无需改变。
