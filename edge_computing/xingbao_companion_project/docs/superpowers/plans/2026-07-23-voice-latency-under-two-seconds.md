# 星宝大模型语音延迟 2 秒内实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将用户最后一个有效语音帧结束到星宝播出大模型正文第一个有效字稳定压到 2 秒以内，P95 不超过 1.8 秒；不得截断尾字、重叠播放或丢失模型正文，并保留快速回退。

**Architecture:** 保留当前唤醒、VAD、ASR、LLM 和普通 WAV TTS 路线，在板卡输出层增加 `aplay` 原始 PCM 流式后端。录音期间预热 DashScope 实时 TTS，LLM 产生首个安全短语后立即推送 PCM；失败且尚未出声时回退现有普通 WAV 路线。

**Tech Stack:** Python 3.8、DashScope streaming LLM、DashScope CosyVoice realtime TTS、ALSA `aplay`、pytest、JSONL monotonic timing。

## Global Constraints

- 权威起点是 VAD 元数据 `last_voice_frame_perf`，不是 `speech_captured` 事件。
- 权威终点是第一个有效 PCM 写入板卡 `aplay` 管道的时间。
- 目标是大模型正文首字，不得用提示音代替正文指标。
- 普通 WAV 播放与实时 PCM 必须共享 `_AUDIO_PLAY_LOCK`，禁止语音重叠。
- `pc5.py` 不得修改。
- 板卡项目修改前保留时间戳备份；本地旧主线文件不得被板卡文件覆盖。
- 机械臂只保留高层白名单动作，本计划不修改机械臂底层。

---

### Task 1: Lahaina 原始 PCM 输出后端

**Files:**
- Modify: `.codex_materials/latency_fix_20260723/multimodal/audio_io.py`
- Test: `.codex_materials/latency_fix_20260723/tests/test_audio_vad.py`

**Interfaces:**
- Produces: `AlsaRawOutputStream(samplerate: int, channels: int, dtype: str)`
- Consumes: `configure_lahaina_output_mixer()`、`BOARD_APLAY_OUTPUT_DEVICE`

- [x] **Step 1: 写入失败测试**

  测试 `AlsaRawOutputStream` 将 PCM 写入：

  ```text
  aplay -q -D plughw:<card>,0 -t raw -f S16_LE -c 1 -r 22050
  ```

- [x] **Step 2: 运行测试确认红灯**

  ```bash
  python -m pytest -q \
    tests/test_audio_vad.py::test_alsa_raw_output_stream_writes_pcm_to_aplay \
    tests/test_audio_vad.py::test_realtime_player_uses_aplay_stream_for_board_output
  ```

  预期：分别因 `AlsaRawOutputStream` 不存在和错误调用 `sounddevice` 失败。

- [ ] **Step 3: 实现最小后端**

  后端只接受 `int16` PCM，启动 `aplay` 子进程，通过无缓冲 stdin 写入；`stop()` 关闭 stdin 并检查返回码。

- [ ] **Step 4: 运行后端及现有实时播放器测试**

  预期：新增测试与 `test_realtime_streaming_speech_player_*` 全部通过。

### Task 2: 解锁板卡实时 TTS

**Files:**
- Modify: `.codex_materials/latency_fix_20260723/main.py`
- Modify: `.codex_materials/latency_fix_20260723/deploy/board_start_demo.sh`
- Test: `.codex_materials/latency_fix_20260723/tests/test_main.py`

**Interfaces:**
- Consumes: `BOARD_APLAY_OUTPUT_DEVICE`
- Produces: 板卡启动参数 `--realtime-tts --no-quick-ack --low-latency-voice`

- [ ] **Step 1: 写 CLI 红灯测试**

  使用 `--board-audio-output --realtime-tts` 调用 `main()`，断言不抛出互斥错误，并向 `run_wake_chat()` 传入实时 TTS 与板卡输出设备。

- [ ] **Step 2: 运行测试确认红灯**

  预期：失败信息为 `--board-audio-output is not compatible with --realtime-tts`。

- [ ] **Step 3: 删除互斥并保持混音器预配置**

  板卡输出仍在唤醒前执行 `configure_lahaina_output_mixer()`，然后把输出设备设置为 `BOARD_APLAY_OUTPUT_DEVICE`。

- [ ] **Step 4: 写启动脚本红灯测试并增加参数**

  启动脚本必须同时包含：

  ```text
  --realtime-tts
  --no-quick-ack
  --low-latency-voice
  ```

- [ ] **Step 5: 运行 CLI 与启动脚本回归**

### Task 3: 首片段快速切分与录音期预热

**Files:**
- Modify: `.codex_materials/latency_fix_20260723/app.py`
- Test: `.codex_materials/latency_fix_20260723/tests/test_app.py`

**Interfaces:**
- Consumes: `_RealtimeTTSHandle`、`split_realtime_tts_chunks`
- Produces: 首个可读短语尽早进入 TTS，正文顺序保持不变

- [ ] **Step 1: 先运行现有预热与切分测试**

- [ ] **Step 2: 增加首片段延迟红灯测试**

  连续输入未出现句号的中文 delta，断言 6–10 个可读汉字或逗号边界即可输出首片段，后续文本仍完整保留。

- [ ] **Step 3: 最小调整 `_find_realtime_tts_cut`**

  优先自然标点；仅对首片段使用有上限的长度切分，不从词中间切断数字、英文或标点组合。

- [ ] **Step 4: 验证实时失败在首音频前回退普通 WAV**

### Task 4: 权威端到端计时

**Files:**
- Modify: `.codex_materials/latency_fix_20260723/multimodal/audio_io.py`
- Modify: `.codex_materials/latency_fix_20260723/app.py`
- Modify: `tools/board_voice_latency_benchmark.py`
- Test: `tests/test_voice_latency_report.py`

**Interfaces:**
- Produces events: `tts_stream_first_pcm_written`
- Consumes fields: `last_voice_frame_perf`、`event_monotonic_ms`

- [ ] **Step 1: 写报告红灯测试**

  输入 VAD 最后语音帧和首 PCM 写入事件，断言报告输出 `last_voice_to_first_word_ms`。

- [ ] **Step 2: 在首次成功写入 PCM 后发出一次事件**

- [ ] **Step 3: 基准脚本同时报告正文首字、VAD 尾静音、ASR、LLM、TTS 和播放耗时**

### Task 5: 板卡部署与物理基准迭代

**Files:**
- Upload only: `app.py`、`main.py`、`multimodal/audio_io.py`、`deploy/board_start_demo.sh`
- Logs: `work/latency/llm_realtime_*/*.json`

- [ ] **Step 1: 备份板卡目标文件并上传**

- [ ] **Step 2: 运行 `python -m compileall` 与定向 pytest**

- [ ] **Step 3: 启动 UI、语音、动作服务并确认 8764/8765/8766**

- [ ] **Step 4: 用故事、知识问答、情绪陪伴、推理和长句运行至少 15 个物理试次**

- [ ] **Step 5: 若超标，按最大阶段耗时单变量迭代**

  - ASR > 450ms：启用流式 ASR。
  - LLM 首片段 > 600ms：压缩语音系统提示与历史窗口。
  - TTS 首 PCM > 500ms：检查预热复用与首片段长度。
  - PCM 写入 > 100ms：调整 `aplay` 缓冲设置并单独 A/B。

- [ ] **Step 6: 验收**

  - 热态 P95 `last_voice_to_first_word_ms <= 1800`
  - 所有正式验收试次 `<= 2000ms`
  - ASR 语义正确且无尾字截断
  - 正文完整且无语音重叠

### Task 6: 全功能回归和回退

**Files:**
- Test: `tests/test_app.py`
- Test: `tests/test_audio_vad.py`
- Test: `tests/test_board_ui_client.py`
- Test: `tests/test_game_speech_server.py`

- [ ] **Step 1: 验证唤醒确认、监听提示音和再次唤醒打断**
- [ ] **Step 2: 验证画板、百宝箱、游戏读题/提示/答对答错语音**
- [ ] **Step 3: 验证普通 WAV 回退和实时 TTS 失败回退**
- [ ] **Step 4: 验证机械臂只通过高层白名单**
- [ ] **Step 5: 汇总原始 JSONL、A/B 报告、已知外部依赖和回滚文件**
