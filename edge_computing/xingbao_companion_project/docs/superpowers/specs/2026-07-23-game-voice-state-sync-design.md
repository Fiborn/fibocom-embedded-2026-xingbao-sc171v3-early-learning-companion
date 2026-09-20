# 游戏语音与页面状态同步设计

## 目标

在不修改 `pc5.py`、不改变现有产品代号、不让 LLM 直接控制硬件的前提下，恢复并完善游戏欢迎、自动读题、手动读题、反馈播报、语音缓存、失败降级和页面状态同步。

本设计以 `docs/GAME_VOICE_STATE_AUDIT_20260723.md` 为问题基线，用户已于 2026-07-23 同意按推荐方案实施。

## 设计原则

1. 游戏 UI 是欢迎语、题目、读题和游戏内动态文案的唯一内容来源。
2. 中央语音服务负责校验、排队、缓存、合成、播放、中断和生命周期回执。
3. `game_event` 负责状态、屏幕表情、灯光和机械臂等跨模块编排，不重复生成同一道题的 TTS。
4. 页面推进依赖“最短展示时间 + 对应语音完成”两个条件；语音异常时通过安全超时继续，不能卡死游戏。
5. 每条游戏语音都携带 `utterance_id`、`speech_role`、`page_state`、`game_id` 和 `question_id`。
6. 固定语音在启动前准备并检查；动态题目首次合成后按文本与声音配置持久缓存。
7. UI 在语音不可用时保留触控能力，并显示儿童能理解的可见提示。
8. 只拆分与本次职责直接相关的小模块，不做大版本重命名或无关重构。

## 结构

### 中央侧

- `core/game_speech_server.py`
  - 维护 NDJSON 服务和串行播放队列。
  - 对要求等待完成的请求返回 `finished / failed / interrupted`。
  - 保持旧客户端默认收到 `queued` 的兼容行为。
- `core/game_speech_cache.py`
  - 负责缓存键、缓存路径、完整性检查、清单统计和动态文本缓存。
- `config/game_speech_cache.json`
  - 保存固定欢迎、页面提示、游戏阶段提示和常见题目。
- `app.py`
  - 使用统一缓存播放游戏语音。
  - 将播放结果转换为生命周期状态。
- `deploy/board_start_demo.sh`
  - 启动前检查并尝试补齐固定缓存；失败时记录警告但不阻断触控 UI。

### 游戏 UI 侧

工作源：`work/incoming/xingbao_touch_game_latest/xingbao_touch_game/`

- `src/central_speech_client.py`
  - 后台发送请求。
  - 保留请求上下文并向 UI 回调最终状态。
  - 对瞬时连接失败做有界重试。
- `src/speech_state.py`
  - 独立维护当前语音、问题版本、反馈等待和安全超时。
  - 不依赖 Pygame，便于单元测试。
- `src/app.py`
  - 构造语音元数据。
  - 每次真正进入游戏中心时欢迎一次。
  - 每道新题自动读一次；手动读题始终允许。
  - 反馈页等待对应语音完成后再切题。
- `src/game_api.py`
  - 返回 `ui_state`、`page_state`、`question_id`、`display_message` 和 `speech_status`。
- `desktop.py`
  - 创建语音客户端时连接状态回调。
  - 桌面点读和游戏语音使用不同 `speech_role`，避免误删和串话。

## 请求与回执

请求关键字段：

```json
{
  "type": "speech_request",
  "message_id": "network-message-id",
  "source": "xingbao_touch_game",
  "payload": {
    "text": "请找到三角形在哪里。",
    "utterance_id": "shape:1:triangle:question:1",
    "speech_role": "question",
    "page_state": "GAME_RUNNING",
    "game_id": "shape",
    "question_id": "shape:1:triangle",
    "wait_for_finish": true,
    "request_tts": true
  }
}
```

最终回执关键字段：

```json
{
  "type": "speech_status",
  "reply_to": "network-message-id",
  "ok": true,
  "payload": {
    "status": "finished",
    "utterance_id": "shape:1:triangle:question:1",
    "speech_role": "question",
    "page_state": "GAME_RUNNING",
    "game_id": "shape",
    "question_id": "shape:1:triangle"
  }
}
```

兼容规则：

- 未设置 `wait_for_finish` 的旧请求仍立即收到 `queued`。
- 设置 `wait_for_finish` 的游戏请求由后台客户端等待最终回执，不阻塞 Pygame 主线程。
- 超时回执为 `failed`，UI 按安全超时继续。

## 状态推进

### 进入游戏中心

1. 桌面切换到游戏显示。
2. 游戏 UI 进入 `HOME`。
3. 页面第一帧显示。
4. 发送一次 `speech_role=welcome`。

### 开始题目

1. 生成题目和 `question_id`。
2. 页面进入 `GAME_RUNNING` 并显示同一题。
3. 发送一次 `speech_role=question`。
4. 手动“读题”发送新的 `utterance_id`，但沿用相同 `question_id`，角色为 `repeat_question`。

### 答题反馈

1. 答题前冻结当前 `question_id`。
2. 页面进入 `GAME_FEEDBACK`，显示本题结果。
3. 发送 `speech_role=feedback`。
4. 达到最短展示时间且反馈语音结束后，进入下一题。
5. 语音失败或回执丢失时，到达最大等待时间后继续并显示语音降级提示。

## 缓存

- 固定清单使用可读文件名，便于部署检查。
- 动态文本使用 `SHA-256(text + voice profile)` 的稳定文件名。
- 有效 WAV 必须存在且大于最小字节数。
- 缓存统计返回 `ready / missing / corrupt` 数量与明细。
- 启动时先检查，再尝试生成缺失固定项。
- 动态题目第一次播放成功后直接保留，下次命中。

## 用户体验要求

- 欢迎、题目、反馈不重复、不抢话、不跨题。
- 读题按钮在中央暂时不可用时给出“星宝的声音暂时没准备好，题目还在屏幕上”的短提示。
- 反馈期间禁用重复答题输入，但保留返回和语音状态提示。
- 页面显式显示“正在播报 / 可以作答 / 声音暂不可用”等状态。
- 儿童操作文案短、具体、无技术错误码。
- 家长和调试日志保留 `utterance_id + question_id + status`，便于定位。

## 测试

- 中央协议：旧客户端 `queued`、新客户端最终 `finished/failed`、重复请求、异常处理。
- 缓存：命中、缺失、损坏、动态文件稳定性。
- UI 状态：欢迎恰好一次、自动读题一次、手动读题、反馈等待、失败超时。
- 游戏 API：屏幕状态与 `question_id` 一致。
- 端到端：桌面进入游戏、选择难度、答对/答错、下一题、总结。
- 全量回归：不新增现有失败；专项测试全部通过。

## 非目标

- 不改写 `pc5.py`。
- 不引入任意舵机角度或原始硬件指令。
- 不重做全部 Pygame UI。
- 不改产品代号或创建无意义的“第十三代”版本。
- 不把所有动态题库强制一次性云合成后才允许启动。

