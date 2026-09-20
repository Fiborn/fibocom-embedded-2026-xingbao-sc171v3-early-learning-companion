# 游戏语音与页面状态同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复并完善游戏欢迎、自动读题、手动读题、反馈播报、语音缓存和页面状态同步，并对完整儿童使用流程做实机体验审计。

**Architecture:** 游戏 UI 生成唯一文案并携带题目版本；中央服务串行缓存和播放并返回最终状态；独立 `SpeechState` 将语音完成事件与游戏页面状态机连接。固定语音启动前预热，动态语音首次播放后持久缓存。

**Tech Stack:** Python 3.12、Pygame、NDJSON over TCP、pytest、DashScope TTS、SC171V3 板端 Linux。

## Global Constraints

- 不删除或修改 `pc5.py`。
- 不硬编码 API Key，不提交 `.env`。
- 只使用高层、白名单机械臂动作；本计划不新增原始硬件控制。
- 不改变产品代号，不做无关的大版本重构。
- 保留现有脏工作树中的用户修改。
- 每个行为修复先写失败测试并确认失败，再写最小实现。

---

### Task 1: 中央语音最终回执

**Files:**
- Modify: `core/game_speech_server.py`
- Modify: `tests/test_game_speech_server.py`

**Interfaces:**
- Consumes: `speech_request.payload.wait_for_finish: bool`
- Produces: 最终 `speech_status.payload.status`，取值为 `finished` 或 `failed`

- [ ] **Step 1: 写失败测试**

增加真实 TCP 测试：处理函数阻塞时，请求线程不应提前得到 `finished`；释放处理函数后应得到 `finished`，并回显 `utterance_id`、`question_id` 和 `speech_role`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_game_speech_server.py -v`

Expected: 新测试收到当前 `queued`，与期望的 `finished` 不一致。

- [ ] **Step 3: 实现最小回执机制**

为队列任务增加完成事件和错误结果；旧请求立即返回 `queued`，`wait_for_finish=true` 的请求等待工作线程设置最终结果。异常转换为 `failed`，工作线程保持存活。

- [ ] **Step 4: 运行专项测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_game_speech_server.py -v`

Expected: PASS。

### Task 2: 游戏语音缓存模块

**Files:**
- Create: `core/game_speech_cache.py`
- Create: `config/game_speech_cache.json`
- Create: `tests/test_game_speech_cache.py`
- Modify: `app.py`
- Modify: `main.py`
- Modify: `deploy/board_start_demo.sh`

**Interfaces:**
- Produces: `GameSpeechCache.path_for(text, voice_id) -> Path`
- Produces: `GameSpeechCache.inspect_manifest() -> dict`
- Consumes: `config/game_speech_cache.json`

- [ ] **Step 1: 写缓存失败测试**

覆盖稳定哈希路径、有效 WAV、损坏 WAV、清单缺失统计和同一文本复用。

- [ ] **Step 2: 运行测试确认模块不存在**

Run: `.venv\Scripts\python.exe -m pytest tests/test_game_speech_cache.py -v`

Expected: `ModuleNotFoundError: core.game_speech_cache`。

- [ ] **Step 3: 实现缓存与清单**

固定清单包含桌面欢迎、游戏中心欢迎、难度提示、常用阶段提示、颜色/形状/数数固定题目；动态文本按 `SHA-256` 落到 `work/cache/game_tts/`。

- [ ] **Step 4: 接入游戏播放和启动检查**

`speak_game_text()` 优先命中动态缓存，未命中时将合成结果直接写入稳定缓存路径。启动脚本执行固定缓存检查与补齐，失败只记录警告。

- [ ] **Step 5: 运行缓存和应用专项测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_game_speech_cache.py tests/test_app.py tests/test_main.py -q`

Expected: 新缓存测试通过；记录并隔离原有非本任务失败。

### Task 3: UI 语音状态模块与客户端回调

**Files:**
- Create: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/src/speech_state.py`
- Create: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_speech_state.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/src/central_speech_client.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_central_speech_client.py`

**Interfaces:**
- Produces: `SpeechState.begin(...) -> utterance_id`
- Produces: `SpeechState.handle_status(request, response) -> None`
- Produces: `SpeechState.feedback_ready(now) -> bool`
- Central client callback: `on_status(request: dict, response: dict) -> None`

- [ ] **Step 1: 写失败测试**

验证语音元数据、反馈未完成不放行、完成后放行、失败后最短展示结束即放行、回执丢失时最大等待超时放行。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_speech_state.py -v`

Expected: `ModuleNotFoundError: src.speech_state`。

- [ ] **Step 3: 实现独立状态对象**

状态对象不导入 Pygame，仅保存当前语音上下文、最终状态、最短展示截止时间和安全截止时间。

- [ ] **Step 4: 扩展后台客户端**

客户端发送 `wait_for_finish=true`，保留原始请求上下文；最多做两次有界重试；收到响应或最终失败后调用 `on_status`。

- [ ] **Step 5: 运行客户端和状态测试**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_speech_state.py work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_central_speech_client.py -v`

Expected: PASS。

### Task 4: 欢迎、自动读题、手动读题和反馈同步

**Files:**
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/src/app.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/desktop.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_app_smoke.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_desktop_launcher.py`

**Interfaces:**
- `XingbaoApp.speak(text, page, speech_role, question_id, wait_for_finish)`
- `XingbaoApp.handle_speech_status(request, response)`
- `XingbaoApp.current_question_id() -> str`

- [ ] **Step 1: 写欢迎和读题失败测试**

验证构造函数不提前欢迎；每次 `activate_display()` 欢迎恰好一次；开始题目自动读一次；手动读题生成新 `utterance_id` 但沿用当前 `question_id`。

- [ ] **Step 2: 写反馈同步失败测试**

答题后即使本地 1.15 秒结束，只要反馈语音未完成，仍保持 `GAME_FEEDBACK`；完成回执后进入下一题；失败或超时可安全继续。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_app_smoke.py work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_desktop_launcher.py -v`

Expected: 新增断言失败。

- [ ] **Step 4: 接入 `SpeechState`**

从构造函数移除提前欢迎；在 `activate_display()` 第一帧对应生命周期发送欢迎；题目和读题生成完整元数据；反馈状态按语音完成和安全超时推进。

- [ ] **Step 5: 运行 UI 专项测试**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_app_smoke.py work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_desktop_launcher.py -q`

Expected: PASS。

### Task 5: 页面与游戏状态 API 对齐

**Files:**
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/src/game_api.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_game_api.py`

**Interfaces:**
- Produces state fields: `ui_state`, `page_state`, `question_id`, `display_message`, `speech_status`

- [ ] **Step 1: 写失败测试**

分别在 `GAME_RUNNING` 和 `GAME_FEEDBACK` 获取状态，断言 API 与屏幕状态、显示文案和问题版本一致。

- [ ] **Step 2: 运行测试确认字段缺失**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_game_api.py -v`

Expected: `KeyError` 或字段断言失败。

- [ ] **Step 3: 实现页面状态字段**

公共状态从 UI 应用读取页面状态和当前语音状态；反馈阶段保留触发反馈的 `question_id` 和显示文案。

- [ ] **Step 4: 运行 API 测试**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_game_api.py -v`

Expected: PASS。

### Task 6: 语音不可用的儿童友好降级

**Files:**
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/src/speech_state.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/src/app.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/desktop.py`
- Modify: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_app_smoke.py`

**Interfaces:**
- Produces: `speech_available: bool`
- Produces: `speech_notice: str`

- [ ] **Step 1: 写失败测试**

模拟中央连接失败，断言游戏仍可触控、状态机不会卡死、页面显示“星宝的声音暂时没准备好，题目还在屏幕上”。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_app_smoke.py -v`

Expected: 当前没有可见降级状态。

- [ ] **Step 3: 实现可见降级**

错误回调设置短提示和不可用状态；后续成功回执自动恢复；不显示 socket、端口或异常类名。

- [ ] **Step 4: 运行专项测试**

Run: `.venv\Scripts\python.exe -m pytest work/incoming/xingbao_touch_game_latest/xingbao_touch_game/tests/test_app_smoke.py -v`

Expected: PASS。

### Task 7: 发布包、板端部署与端到端验证

**Files:**
- Modify generated package: `work/incoming/xingbao_touch_game_latest/xingbao_touch_game/dist/xingbao_touch_game_board.zip`
- Update: `docs/GAME_VOICE_STATE_AUDIT_20260723.md`

**Interfaces:**
- Board UI: `127.0.0.1:8765`
- Central speech: `127.0.0.1:8766`

- [ ] **Step 1: 运行两个代码库专项测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_game_speech_server.py tests/test_game_speech_cache.py -q`

Run in UI source with Pygame test dependency: `python -m pytest tests/test_speech_state.py tests/test_central_speech_client.py tests/test_app_smoke.py tests/test_game_api.py -q`

Expected: 全部通过。

- [ ] **Step 2: 生成板端包并验证内容**

Run: `python tools/make_board_package.py`

Expected: ZIP 包含 `src/speech_state.py`、更新后的客户端、应用和测试所需配置。

- [ ] **Step 3: 备份并部署**

解析板端当前符号链接和实际目录；创建带时间戳备份；通过现有发布脚本安装新 release，不覆盖共享 `saves/` 和 `logs/`。

- [ ] **Step 4: 启动并验证日志**

确认 8765、8766 监听；发送带最终回执的 smoke request；检查 UI 与中央日志不存在语音连接失败。

- [ ] **Step 5: 验证完整用户流程**

依次验证桌面、游戏中心、难度、第一题、读题、答错、答对、下一题、总结、返回桌面；每一步记录页面状态、`question_id` 和语音状态。

### Task 8: 实机用户体验审计与高影响优化

**Files:**
- Create: `docs/GAME_USER_EXPERIENCE_AUDIT_20260723.md`
- Create screenshots under: `docs/references/game_ux_audit_20260723/`

**Interfaces:**
- Evidence: 本次板端流程截图

- [ ] **Step 1: 截取完整流程**

保存 `01-desktop.png` 至 `08-summary.png`，逐张检查不是黑屏、加载页或错误页面。

- [ ] **Step 2: 从三个视角审计**

儿童：下一步是否明显、反馈是否及时、文字是否短、误触能否恢复。  
家长：学习结果是否可理解、语音失败是否可发现、隐私信息是否安全。  
演示操作者：启动是否确定、缓存是否就绪、日志是否能定位问题。

- [ ] **Step 3: 修复高影响且低风险的问题**

每个修复先增加失败测试；只处理影响任务完成、误操作恢复、状态理解、声音可用性和可访问性的 P0/P1 问题。

- [ ] **Step 4: 回归并更新报告**

记录每个步骤健康度、截图证据、已修复项和仍需硬件人工验证项。

### Task 9: 最终回归

**Files:**
- Update: `docs/FEATURE_REGRESSION_CHECKLIST.md`

**Interfaces:**
- Central test suite
- UI test suite
- Board smoke checks

- [ ] **Step 1: 中央编译和全量测试**

Run: `.venv\Scripts\python.exe -m compileall .`

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: 不新增失败；专项测试全绿；既有失败单独列出。

- [ ] **Step 2: UI 编译和全量测试**

Run: `python -m compileall desktop.py src tests`

Run: `python -m pytest -q`

Expected: PASS，或只保留有明确证据的既有环境相关失败。

- [ ] **Step 3: 板端重启复验**

重启完整演示服务后重复欢迎、读题和两题流程，确认缓存命中且页面/语音不串题。

