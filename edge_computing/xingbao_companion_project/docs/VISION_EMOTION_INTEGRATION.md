# 视觉情绪系统现场接入说明

## 1. 正式运行链

新版视觉代码位于 `multimodal/vision_system/`，保留发布包兼容入口：

```powershell
python -m vision_system.app --source 0
```

现场中央服务通过 `VisionProcessBridge` 托管视觉子进程。视觉只输出经过
稳定、去重和白名单过滤的 `vision_state`，随后进入现有协调器：

```text
摄像头
  -> 距离 / 久坐 / 饮水 / FERPlus 情绪
  -> VisionEventAdapter
  -> vision_state
  -> XingbaoCoordinator
  -> 屏幕 + 中央 TTS + 高层机械臂 IPC
```

手动启动中央联调：

```powershell
python main.py --game-speech --vision-runtime --board-ui
```

`deploy/board_start_demo.sh` 默认增加 `--vision-runtime`。视觉初始化失败时，
子进程退出并记录 `[vision]` 日志，但中央语音、触控和游戏服务继续运行。

完整演示只允许一个进程占用摄像头：当 `XINGBAO_ENABLE_VISION=1`（默认）时，
`deploy/board_start_full_demo.sh` 会先清理遗留的视觉子进程，并用
`desktop.py --no-vision` 关闭触控桌面内置的旧视觉桥接；摄像头只由中央服务
托管的新版情绪视觉使用。只有显式设置 `XINGBAO_ENABLE_VISION=0` 时，启动脚本
才不向桌面传 `--no-vision`，用于兼容回退。

## 2. 向后兼容接口

原接口保持不变：

- `return_code=1`：距离过近；
- `return_code=2`：长时间持续检测到人脸；
- `drink_return_code=1`：需要饮水提醒。

新增独立接口：

- `emotion_return_code=0`：置信度不足，不产生情绪事件；
- `1..8`：开心、悲伤、愤怒、惊讶、恐惧、厌恶、轻蔑、中性。

距离、饮水和情绪是并列信号，情绪不会覆盖旧返回码。

## 3. 情绪联动策略

情绪必须连续稳定 3 帧才允许上报。任意情绪反馈最短间隔为 15 秒，同一
情绪重复反馈冷却时间为 90 秒；距离和饮水提醒按状态上升沿触发。

| 情绪线索 | 屏幕/灯光 | 语音 | 当前现场机械臂 |
|---|---|---|---|
| 开心 | 微笑、暖色呼吸 | 温和回应开心 | `stay_still` |
| 悲伤 | 陪伴表情、蓝色呼吸 | 使用“如果你现在……”的非诊断话术 | `shake_head` |
| 愤怒 | 平静表情、蓝色呼吸 | 引导慢呼吸 | `stay_still` |
| 惊讶 | 惊讶表情、暖色呼吸 | 询问是否发现新东西 | `stay_still` |
| 恐惧 | 陪伴表情、蓝色呼吸 | 使用条件式安抚话术 | `shake_head` |
| 厌恶/轻蔑/中性 | 低打扰屏幕状态 | 不主动说话 | `stay_still` |

现场机械臂目前只正式启用 `shake_head`，所以没有把开心强行映射为点头。
所有动作只经过 `127.0.0.1:8764` 的高层动作接口，不发送动作组、舵机角度、
PWM、GPIO、原始串口命令或任意时序。

情绪识别只作为可能的互动线索，不作为医学或心理诊断，也不写入儿童敏感信息。

## 4. PC 与 SC171V3 配置

PC 完整功能依赖：

```powershell
python -m pip install -r requirements-vision.txt
```

SC171V3 现场默认设置：

```sh
export XINGBAO_ENABLE_VISION=1
export XINGBAO_VISION_NO_OBJECTS=1
export XINGBAO_VISION_SOURCE=0
```

该模式使用 OpenCV Haar + OpenCV DNN FERPlus，保留距离和情绪识别，不加载
PyTorch/Ultralytics，更适合现场板卡。安装板端依赖：

```sh
XINGBAO_INSTALL_VISION_DEPS=1 sh deploy/board_install_deps.sh
```

若现场已有带 OpenCV 的独立 Python，可指定：

```sh
export XINGBAO_VISION_PYTHON=/path/to/python3
```

完成依赖和摄像头配置后，可把视觉设为启动硬门槛：

```sh
export XINGBAO_REQUIRE_VISION=1
```

此时 `board_health_check.py` 会验证视觉 Python、FERPlus 模型、OpenCV DNN
模型加载和人脸分类器。完整 YOLO 模式还会验证 Ultralytics 和 YOLO 权重。

现场接好摄像头并启动中央服务后，执行最终验收：

```sh
python3 tools/vision_site_acceptance.py --check-central
```

该命令读取少量摄像头帧，确认三个返回码字段、真实模型推理进程和中央
`vision_state` 路由均可用。中央路由探针使用“中性、静默、无机械臂动作”
事件，不会触发情绪语音或实体动作。

## 5. 可配置环境变量

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `XINGBAO_ENABLE_VISION` | `1` | 是否由现场启动脚本启用视觉 |
| `XINGBAO_REQUIRE_VISION` | `0` | 视觉检查失败时是否阻止中央启动 |
| `XINGBAO_VISION_PYTHON` | 中央 Python | 视觉子进程 Python |
| `XINGBAO_VISION_SOURCE` | `0` | 摄像头编号或视频路径 |
| `XINGBAO_VISION_NO_OBJECTS` | 板端为 `1` | 禁用 YOLO 物体识别 |
| `XINGBAO_VISION_MODEL` | `models/vision/yolo11n.pt` | YOLO 模型路径 |
| `XINGBAO_VISION_EMOTION_MODEL` | `models/vision/emotion-ferplus-8.onnx` | 情绪模型路径 |
| `XINGBAO_VISION_IMGSZ` | `320` | YOLO 输入尺寸 |
| `XINGBAO_VISION_OBJECT_EVERY` | `5` | 每隔多少帧执行物体识别 |
| `XINGBAO_VISION_EMOTION_THRESHOLD` | `0.60` | 情绪确认阈值 |

## 6. 模型与发布包

本地模型位置：

```text
models/vision/yolo11n.pt
models/vision/emotion-ferplus-8.onnx
```

`models/` 不进入 Git，但 `tools/make_central_board_package.py` 会显式校验并把
这两个视觉模型加入板端发布包。缺少模型时打包会直接失败，避免部署出一个
启动后才发现不可用的空视觉模块。
