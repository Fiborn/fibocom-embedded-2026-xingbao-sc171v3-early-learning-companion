# Xingbao Companion

Xingbao Companion 是把原始单文件 `pc5.py` 语音陪伴 demo 迁移为模块化、儿童友好的智能早教陪伴桌系统。角色名为“星宝”。

项目新主线聚焦学龄前儿童成长陪伴与认知启蒙教育领域，依托 SC171V3 核心技术，打造一款智能儿童早教陪伴桌。当前阶段先移除机械臂方向，专注语音交互、触控桌面屏视觉互动、实物摆放、多模态感知输入、学习节奏自适应、健康用眼提示和情绪引导。

屏幕已升级为触控屏，因此触控不再只是辅助输入，而是和语音并列的核心交互方式。孩子可以通过点触、拖拽、长按说明、区域确认和语音指令自然切换完成任务。

产品核心理念是寓教于乐：引导孩子在动手操作、趣味探索的真实桌面场景中完成认知训练、规则意识培养与情绪陪伴，为家庭提供安全、高效、有趣的早期教育解决方案。

## 当前阶段

项目已经完成基础模块化迁移：`SessionManager` 文本演示、安全 memory 管理、动态 prompt builder、本地 profile extractor、action safety、action bus、DashScope network / ASR / LLM / TTS 客户端、基础音频 I/O、VAD、quick ack、`app.py` 编排、`main.py` CLI、色块桌面互动原型和文档。

`serial bridge`、`arm_action` 等机械臂/板卡相关代码目前仅作为历史兼容能力保留，不再作为产品主线推进。后续新功能默认不依赖机械臂，也不新增舵机、原始串口、PWM 或 GPIO 控制。

本轮新增了天猫精灵式的语音事件骨架。现阶段仍保留 HTTP ASR/TTS 回退：ASR 还是录完一句后识别，LLM 支持 streaming，TTS 支持按句排队合成播放。后续可以在不大改上层流程的前提下替换为真实 WebSocket ASR/TTS。

原始基线文件 `pc5.py` 必须保持不变，继续作为可工作的参考实现。

## 项目结构

- `core/` - 应用编排、配置、session、safety、memory、互动状态总线、桌面游戏规则和 voice events。
- `intelligence/` - prompt 构建、profile 提取和模型回复相关逻辑。
- `multimodal/` - ASR、TTS、VAD、音频播放、唤醒词和设备集成。
- `config/` - 角色、运行参数、儿童 profile 和 action schema 配置。
- `data/` - 本地非敏感 memory 数据。
- `web/` - 桌面视觉交互和浏览器原型。
- `docs/` - 产品方向、设计规则、迁移复盘和验收文档。
- `tests/` - 自动化测试。
- `work/cache/` - 运行时生成的缓存文件。
- `pc5.py` - 原始工作基线。迁移过程中不要删除或重写。

## 关键文档

- `docs/PRODUCT_DIRECTION.md` - 星宝产品主线方向。
- `docs/MODULE_COLLABORATION_PROTOCOL.md` - 小游戏、视觉、触控、TTS、表情和记忆模块的协作协议。
- `docs/XINGBAO_EXPRESSION_GUIDE.md` - 星宝表达准则。
- `docs/XINGBAO_EXPRESSION_SCENARIOS.md` - 星宝表达场景分类。
- `docs/XINGBAO_EXPRESSION_GUIDANCE.md` - 孩子断续表达时的引导策略。
- `docs/XINGBAO_EVENT_RESPONSE_TABLE.md` - 事件到星宝表达策略的响应表。
- `docs/XINGBAO_MEMORY_EXPRESSION_RULES.md` - 记忆与表达联动规则。
- `docs/DEMO_FLOW_SCRIPT.md` - 评委展示流程脚本。
- `docs/FEATURE_REGRESSION_CHECKLIST.md` - 每次迭代后的回归检查清单。
- `docs/GAME_XINGBAO_HANDOFF_PACKAGE.md` - 给游戏、动作、表情同学的协同交付包目录。
- `docs/GAME_XINGBAO_COLLAB_RULES.md` - 星宝与触控游戏的协同规则手册。
- `docs/GAME_XINGBAO_API_SPEC.md` - 星宝和触控游戏之间的命令、响应、事件接口规范。
- `docs/GAME_INTENTS_V0.md` - 第一版游戏固定意图表。
- `docs/GAME_STATE_TEMPLATE.md` - 颜色、图形、记忆三个游戏的状态回填模板。
- `docs/ACTION_EXPRESSION_HANDOFF.md` - 机械臂高层动作、星宝表情、灯效白名单交付说明。
- `docs/ACTION_EXPRESSION_FEASIBILITY_TEMPLATE.md` - 动作、表情、灯效可实现性回填模板。
- `docs/MESSAGE_TO_GAME_DEV.md` - 可直接发给游戏同学的任务说明。
- `docs/PORTABILITY.md` - 历史板卡兼容边界。

## 使用方式

查看 CLI 帮助：

```powershell
python main.py --help
```

运行文本演示：

```powershell
python main.py --text-demo
```

查看动态 prompt：

```powershell
python main.py --prompt-preview
```

运行星宝表达调度 demo：

```powershell
python main.py --expression-demo
```

用 JSON 文件测试一个模块协作事件：

```powershell
python main.py --expression-event-file .\event.json
```

默认模式只会预览星宝的表达输出。如果要接入到应用层，同步更新记忆、屏幕表情和灯效状态，使用：

```powershell
python main.py --expression-event-file .\event.json --expression-apply
```

如果需要让星宝把 `speak_text` 真正说出来，使用：

```powershell
python main.py --expression-event-file .\event.json --expression-speak --local-tts-fallback
```

列出音频设备：

```powershell
python main.py --list-devices
```

运行单轮真实语音流程：

```powershell
python main.py --voice-once
```

指定音频输入和输出设备：

```powershell
python main.py --voice-once --input-device 5 --output-device 3
```

历史兼容：发送一个安全高层动作到板卡。该能力不属于当前产品主线，只有在维护旧板卡验证时使用：

```powershell
python main.py --send-action wave_hand --serial-port COM3
```

## 本地唤醒词

唤醒词为“星宝星宝”。唤醒检测使用本地 `openWakeWord` 和项目内置的 TFLite 模型，不会在待机监听阶段调用 DashScope，也不会上传待机音频。麦克风录音统一使用 16 kHz。

安装可选依赖：

```powershell
python -m pip install -r requirements-wake-word.txt
```

项目已包含所需模型文件，部署时请保留以下文件：

```text
model_voice/xingbao.tflite
model_voice/openwakeword/melspectrogram.tflite
model_voice/openwakeword/embedding_model.tflite
```

仓库内的 `config/keywords.txt` 已配置“星宝星宝”。模型文件较大，不提交到 Git。

只测试一次本地唤醒，不调用云端：

```powershell
python main.py --test-wake-word --input-device 5
```

也可以先录成 WAV，再离线检查唤醒词：

```powershell
python -c "from multimodal.audio_io import record_wav,AudioDeviceConfig; print(record_wav('work/cache/wake_test.wav',seconds=4,config=AudioDeviceConfig(input_device=5)))"
python main.py --test-wake-wav work/cache/wake_test.wav
```

## 连续语音对话

唤醒后处理一轮语音：

```powershell
python main.py --wake-loop --input-device 5 --output-device 3
```

唤醒一次后进入连续聊天窗口，不需要每句话都重新唤醒：

```powershell
python main.py --wake-chat --input-device 5 --output-device 3
```

默认一次唤醒后最多处理 5 轮。每轮回答结束后，星宝会等待 8 秒后续问题；如果没有听到新的问题，本次聊天窗口结束并回到待唤醒状态。

在连续聊天窗口内，说“退出”“结束”“停止”“再见”“拜拜”或“不聊了”，会结束当前窗口并回到待唤醒状态。

单次验收可以限制为一个唤醒窗口：

```powershell
python main.py --wake-chat --max-wake-sessions 1 --input-device 5 --output-device 3
```

临时调整窗口参数：

```powershell
python main.py --wake-chat --max-chat-turns 3 --follow-up-timeout 6 --input-device 5 --output-device 3
```

实验性开启真正音频流式 TTS。真实对话验收请优先使用 `--wake-chat`，保留“星宝星宝”唤醒机制和接收提示音：

```powershell
python main.py --wake-chat --realtime-tts --show-voice-events --input-device 5 --output-device 3
```

`--realtime-tts` 会使用 DashScope WebSocket TTS：LLM 边输出文字，程序边按自然短语把文本片段送入 TTS，收到 PCM 音频块后立即播放。不开这个参数时，仍使用默认的 HTTP 分句合成与播放路径。首次使用前请确认虚拟环境已安装 `dashscope`：

```powershell
python -m pip install -r requirements.txt
```

流式 ASR 由 `XINGBAO_ASR_BACKEND` 选择：默认 `cloud` 使用共享的
`DASHSCOPE_API_KEY` 调用 `qwen-audio-3.0-asr-flash-streaming`，并把中间识别
结果实时显示在 UI 字幕；设为 `local` 可回退到内置 Sherpa-ONNX 流式识别。正式
启动脚本均已传入 `--streaming-asr`。

在板卡的 `~/.config/xingbao/runtime.env` 中设置该变量即可统一控制资源：
`XINGBAO_ASR_BACKEND=local` 会启动或复用本地 Sherpa 服务；
`XINGBAO_ASR_BACKEND=cloud` 不会启动它，并会停止本项目遗留的本地服务。
cron 自启动、总服务管理和语音服务管理均使用这一规则。

不录音、不调用云端，只检查实时 TTS 依赖和本地播放环境：

```powershell
python main.py --check-realtime-tts
```

单轮调试可以使用 `--voice-once`，但它会绕过唤醒词；不要把它当作完整交互验收命令。`--no-quick-ack` 只用于延迟诊断，会关闭“接收完音频”的提示音。

如果等待唤醒时感觉“怎么叫都没反应”，打开输入电平调试：

```powershell
python main.py --wake-chat --realtime-tts --show-voice-events --show-wake-level --input-device 5 --output-device 3
```

此时每秒会输出 `[wake] input_rms=...`。如果数字几乎不变或接近 0，优先检查 `--input-device` 是否选对；如果数字会随说话明显变化但仍不唤醒，再调唤醒词阈值。

扬声器或播放设备还没有连接时，可先关闭唤醒提示音和 TTS：

```powershell
python main.py --wake-loop --input-device 0 --no-wake-ack --no-tts
```

如需停止持续监听，按 `Ctrl+C`。

## 语音事件骨架

`core.voice_events.VoiceEvent` 定义了当前语音交互的关键事件：

- `wake_detected`
- `wake_ack_started`
- `quick_ack_started`
- `listening_started`
- `speech_captured`
- `asr_final`
- `llm_delta`
- `llm_stream_finished`
- `tts_segment_queued`
- `tts_synthesis_started`
- `tts_synthesis_finished`
- `tts_synthesis_skipped`
- `tts_stream_started`
- `tts_stream_audio_started`
- `tts_stream_finished`
- `tts_stream_failed`
- `playback_started`
- `playback_finished`
- `playback_skipped`
- `followup_waiting`
- `session_ended`

`XingbaoApp.run_voice_once()`、`run_wake_loop()` 和 `run_wake_chat()` 可以接收 `on_voice_event` 回调。当前实现用现有 HTTP ASR/TTS 发事件，后续真实流式 ASR/TTS 可以沿用同一组事件。

开启 `--show-voice-events` 后，重点观察这些延迟字段：`asr_final.elapsed_ms` 表示识别耗时，`llm_delta.first_delta_elapsed_ms` 表示模型首字耗时，`tts_segment_queued.first_queue_elapsed_ms` 表示首个可播文本片段生成耗时，`tts_stream_audio_started.first_audio_elapsed_ms` 表示实时 TTS 首个音频块耗时。

## 安全规则

新代码不能硬编码 API key，只能从环境变量 `DASHSCOPE_API_KEY` 读取 DashScope 凭证。

不要存储儿童敏感信息，例如家庭住址、电话、学校、班级、精确位置或家长联系方式。

当前产品主线不新增机械臂、舵机、原始串口、PWM 或 GPIO 控制。星宝的反馈应优先落在屏幕表情、语音播报、光效、桌面区域高亮和触控提示上。

LLM 不得直接生成舵机角度、PWM、GPIO 或串口原始命令。任何历史高层动作输出都必须经过 whitelist 和 sanitizer。

## 历史板卡兼容

详见 `docs/PORTABILITY.md`。

该文档记录旧板卡/串口方向的兼容边界。新主线优先建设语音、桌面视觉、触控和多模态感知闭环。
