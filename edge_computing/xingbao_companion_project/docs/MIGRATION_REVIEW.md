# 迁移复盘

## 已完成阶段

1. Project skeleton
2. Session manager and text demo
3. Memory manager and dynamic prompt builder
4. Profile extractor
5. Action bus and action safety
6. Extract network / ASR / LLM / TTS from `pc5.py`
7. Extract VAD / audio playback from `pc5.py`
8. Integrate `app.py` and `main.py`
9. Add desktop visual interaction prototype
10. Add documentation

## 主线调整

项目方向已从“桌面陪伴宠物 + 可选机械动作”调整为“智能儿童早教陪伴桌”。当前阶段先移除机械臂方向，集中建设语音交互、触控桌面屏视觉互动、实物摆放、多模态感知预留、学习节奏自适应和健康守护。

屏幕已升级为触控屏，触控应和语音并列为主输入。后续验收需要确认关键任务可以纯触控完成，也可以语音与触控混合完成。

`serial bridge` 和 `arm_action` 相关实现只作为历史兼容代码保留，不再列为后续产品主线。新功能默认应通过屏幕表情、星宝状态动画、语音、光效、桌面区域高亮和触控反馈完成。

## 当前能力

- `main.py --text-demo` 可运行本地文本演示。
- `main.py --prompt-preview` 可查看动态 system prompt。
- `main.py --list-devices` 可列出音频设备，前提是安装 `sounddevice`。
- `main.py --voice-once` 已有真实语音单轮流程入口，前提是安装音频依赖并设置 `DASHSCOPE_API_KEY`。
- `main.py --wake-chat` 支持唤醒后连续多轮对话窗口。
- `core.voice_events` 已定义语音事件骨架，为后续真实流式 ASR/TTS 预留接口。
- `web/color_block_game.html` 和 `core/color_block_game.py` 已形成桌面视觉互动与规则层原型。
- 历史兼容：`main.py --send-action wave_hand --serial-port COMx` 仍可发送经过清洗的高层动作，但不属于当前产品主线。

## 关键安全边界

- 新模块只从环境变量 `DASHSCOPE_API_KEY` 读取密钥。
- `pc5.py` 保持原始基线，不参与新模块导入。
- memory 只允许保存非敏感字段。
- 当前主线不新增机械臂、舵机、PWM、GPIO 或原始串口控制。
- LLM 不得直接输出舵机角度或原始硬件命令。
- 历史 action 输出必须经过 whitelist 和 sanitizer。

## 仍需真实设备验证

- 麦克风录音。
- VAD 截句阈值。
- 扬声器播放。
- DashScope ASR / LLM / TTS 真实调用。
- quick ack 在真实交互中的延迟。
- 语音事件在真实 `--wake-chat` 流程中的顺序和时间间隔。
- 触控桌面屏交互在 22.5 寸目标设备上的可读性、触控命中、防误触和用眼舒适度。
- 色块/卡片等实物桌面操作与屏幕反馈的节奏是否自然。
