# 星宝项目介绍

## 一句话说明

星宝是一个面向学龄前儿童的智能早教陪伴桌项目。它通过语音、触控桌面屏、角色动画、桌面视觉反馈和后续可扩展的多模态输入，陪孩子完成认知启蒙、表达练习、规则意识培养和情绪陪伴。

当前项目来源于一个单文件语音陪伴 demo `pc5.py`。现在的工作重点是把它迁移成模块化、可维护、可测试、儿童安全友好的桌面陪伴系统。

## 产品定位

星宝不是单纯的聊天机器人，也不是机械臂玩具。当前产品主线是“智能儿童早教陪伴桌”：

- 面向儿童：语言、反馈和互动节奏要适合孩子。
- 面向桌面场景：孩子可以看屏幕、触摸屏幕、摆放色块或卡片。
- 面向陪伴和教育：通过游戏、故事、问答、鼓励和复盘完成学习目标。
- 面向安全：不存储敏感儿童信息，不让模型直接控制硬件。

项目当前已经明确：机械臂、舵机、PWM、GPIO 和原始串口控制不再作为产品主线。相关代码只作为历史兼容能力保留。

## 星宝能做什么

### 语音交互

星宝支持完整语音对话链路：

1. 本地唤醒词监听：“星宝星宝”
2. 唤醒提示音
3. VAD 自动截取孩子说的话
4. 接收完音频后的提示音
5. DashScope ASR 语音识别
6. LLM 生成回答
7. TTS 语音播报
8. 连续对话窗口内继续追问
9. 说“退出、结束、停止、再见、拜拜、不聊了”结束窗口

真实对话主入口是：

```powershell
python main.py --wake-chat --realtime-tts --show-voice-events
```

其中 `--realtime-tts` 表示使用 DashScope WebSocket TTS，让文本片段尽早进入语音合成，收到音频块后尽快播放。

### 触控桌面互动

项目已经开始建设桌面视觉互动方向。触控屏不只是辅助输入，而是和语音并列的核心交互方式。

孩子可以通过：

- 点触
- 拖拽
- 长按说明
- 区域选择
- 语音指令

完成桌面任务和小游戏。

当前已有色块桌面互动原型，用于验证儿童桌面游戏规则、反馈节奏和 UI 表达方式。

### 记忆与个性化

系统可以保存非敏感偏好，例如：

- 兴趣
- 喜欢的游戏
- 沟通风格
- 近期情绪
- 非敏感互动偏好

系统不能保存：

- 家庭住址
- 电话
- 学校
- 班级
- 精确位置
- 家长联系方式

## 当前技术架构

项目被拆成几个主要目录：

| 目录 | 作用 |
| --- | --- |
| `core/` | 配置、session、memory、安全动作、语音事件、桌面游戏规则 |
| `intelligence/` | prompt 构建、profile 提取、LLM 相关逻辑 |
| `multimodal/` | ASR、TTS、VAD、音频播放、唤醒词、音频设备 |
| `config/` | 设置、角色、关键词、action schema |
| `data/` | 本地非敏感记忆数据 |
| `web/` | 桌面视觉互动和浏览器原型 |
| `docs/` | 产品方向、迁移复盘、回归检查和项目说明 |
| `tests/` | 自动化测试 |
| `pc5.py` | 原始工作基线，禁止删除或重写 |

## 语音链路详解

当前语音链路可以理解为：

```text
星宝星宝唤醒
→ 唤醒提示音
→ 录音/VAD
→ 接收提示音
→ ASR
→ LLM 流式输出
→ 文本短语分块
→ TTS 合成与播放
→ 等待连续追问
```

语音系统会发出事件，方便调试：

- `wake_detected`：唤醒成功
- `wake_ack_started`：唤醒提示音开始
- `listening_started`：开始听孩子说话
- `speech_captured`：录到一句话
- `quick_ack_started`：接收完音频提示音开始
- `asr_final`：ASR 识别完成
- `llm_delta`：LLM 流式输出片段
- `tts_segment_queued`：可播文本片段进入 TTS 队列
- `tts_stream_started`：实时 TTS 启动
- `tts_stream_audio_started`：收到首个 TTS 音频块
- `playback_started`：开始播放
- `followup_waiting`：等待孩子继续追问
- `session_ended`：当前对话窗口结束

这些事件可以通过：

```powershell
python main.py --wake-chat --realtime-tts --show-voice-events
```

看到。

## 为什么要做流式

儿童交互很看重“响应感”。如果孩子说完话以后长时间没反馈，就会觉得星宝没有听见。

所以项目正在从传统流程：

```text
听完整句 → 识别 → 等完整回答 → 合成完整音频 → 播放
```

推进到更自然的流程：

```text
听完整句 → 识别 → LLM 边生成 → TTS 边合成 → 音频边播放
```

当前已经支持：

- LLM 文本流式输出
- 自然短语切分
- DashScope WebSocket TTS 音频流式播放
- HTTP TTS 回退
- 关键耗时日志

## 安全边界

项目安全规则非常重要：

1. 不能硬编码 API key。
2. DashScope key 只能从环境变量 `DASHSCOPE_API_KEY` 读取。
3. 不能保存儿童敏感信息。
4. LLM 不能直接控制硬件。
5. 历史机械臂动作必须经过白名单和 sanitizer。
6. `pc5.py` 是原始基线，不删除、不重写。

机械臂历史动作白名单在 `config/action_schema.json` 中，当前只是兼容能力，不是产品主线。

## 当前进展

已经完成：

- 单文件 demo 到模块化项目的基础迁移
- 文本 demo
- session 管理
- memory 管理
- 动态 prompt 构建
- profile 提取
- action safety
- DashScope ASR / LLM / TTS 客户端
- VAD 录音
- 本地唤醒词“星宝星宝”
- `--wake-chat` 连续对话窗口
- 实时 TTS 流式输出
- 语音事件和耗时诊断
- 色块桌面互动原型
- 功能防回归检查清单

仍需继续验证：

- 真实设备上的唤醒灵敏度
- 麦克风输入设备选择
- VAD 截句是否自然
- ASR 对儿童声音的识别准确率
- TTS 首包延迟和播放流畅度
- 播放期间是否需要支持打断
- 触控桌面屏在目标尺寸上的可读性和防误触
- 色块/卡片等实物玩法与屏幕反馈的节奏

## 新组员如何快速上手

1. 先读本文件，理解项目整体目标。
2. 再读 `README.md`，了解运行命令。
3. 读 `docs/PRODUCT_DIRECTION.md`，理解产品主线。
4. 读 `docs/FEATURE_REGRESSION_CHECKLIST.md`，了解哪些功能不能在迭代中丢失。
5. 跑一次文本 demo：

```powershell
python main.py --text-demo
```

6. 查看音频设备：

```powershell
python main.py --list-devices
```

7. 检查实时 TTS：

```powershell
python main.py --check-realtime-tts
```

8. 真实语音测试：

```powershell
python main.py --wake-chat --realtime-tts --show-voice-events --show-wake-level
```

## 协作提醒

每次新增能力时，都要确认：

- 没有绕过“星宝星宝”唤醒主链路。
- 没有关闭唤醒提示音。
- 没有关闭接收完音频提示音。
- 没有让 `--voice-once` 替代完整交互验收。
- 没有把机械臂重新变成产品主线。
- 没有新增儿童敏感信息存储。
- 没有硬编码密钥。

一句话总结：星宝项目的核心不是“能聊天”，而是构建一个安全、自然、有教育价值、可触摸可交互的儿童桌面陪伴系统。

