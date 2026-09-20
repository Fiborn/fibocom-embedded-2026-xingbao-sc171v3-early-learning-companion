# 给项目材料撰写同学的快速上手路径

> 适用对象：需要撰写星宝项目技术文档、项目难点、系统架构说明、答辩材料的同学。  
> 目标：不用重新参与全部开发，也能在较短时间内理解项目逻辑，并写出专业、清晰、符合当前实现状态的材料。  
> 重要提醒：项目当前主线是“智能儿童早教陪伴桌”。机械臂可以作为补充展示/历史兼容模块写入材料，但不要写成大模型直接控制舵机或底层硬件。

---

## 1. 先用一句话重新理解项目

星宝是一个基于 SC171 V3 板卡的智能儿童早教陪伴桌，通过语音唤醒、连续对话、触控屏主界面、小游戏、视觉健康提醒、TTS 播报、表情反馈和可选机械臂动作，实现面向学龄前儿童的“边玩边学、边互动边引导”的多模态陪伴系统。

它不是单纯的聊天机器人，也不是单纯的游戏程序，而是一个把语音、屏幕、游戏、视觉、硬件反馈统一调度起来的儿童交互系统。

---

## 2. 建议你按这条路径掌握项目

### 第一步：先掌握产品定位

先读：

- [docs/PRODUCT_DIRECTION.md](./PRODUCT_DIRECTION.md)
- [docs/PROJECT_INTRO.md](./PROJECT_INTRO.md)
- [README.md](../README.md)

你需要理解这几个关键词：

- 儿童早教陪伴桌
- 多模态交互
- 语音 + 触控 + 游戏 + 视觉 + 表情反馈
- 儿童安全与隐私保护
- 本地规则与云端大模型结合
- 板卡端完整 demo

写材料时不要只写“语音助手”，而要写“面向儿童桌面学习场景的多模态交互系统”。

### 第二步：掌握系统总体架构

先读：

- [docs/SOFTWARE_ARCHITECTURE_FLOW_DESIGN.md](./SOFTWARE_ARCHITECTURE_FLOW_DESIGN.md)
- [docs/HARDWARE_ARCHITECTURE_AND_DIAGRAM_SPEC.md](./HARDWARE_ARCHITECTURE_AND_DIAGRAM_SPEC.md)
- [docs/MODULE_COLLABORATION_PROTOCOL.md](./MODULE_COLLABORATION_PROTOCOL.md)

你需要能讲清楚：

```text
孩子输入
-> 语音/触控/游戏/视觉模块
-> 中枢统一调度
-> 固定规则或大模型回答
-> TTS/屏幕表情/游戏界面/健康提醒/机械臂动作
-> 返回给孩子
```

### 第三步：掌握语音链路

先读：

- [docs/TTS_QUEUE_AND_BARGE_IN.md](./TTS_QUEUE_AND_BARGE_IN.md)
- [docs/CENTRAL_RULES_AND_TEMPLATES.md](./CENTRAL_RULES_AND_TEMPLATES.md)
- [docs/TO_VOICE_TEAM.md](./TO_VOICE_TEAM.md)

语音链路可以这样写：

```text
本地唤醒词“星宝星宝”
-> VAD 判断孩子开始/结束说话
-> ASR 把语音转成文字
-> 中枢判断意图
-> 固定动作规则或 Qwen-plus 生成回答
-> TTS 合成语音
-> 音响播放
```

注意：唤醒词和 VAD 是本地能力，ASR、LLM、TTS 主要调用云端服务。

### 第四步：掌握主界面和小游戏协同

先读：

- [docs/GAME_XINGBAO_API_SPEC.md](./GAME_XINGBAO_API_SPEC.md)
- [docs/GAME_STATE_TEMPLATE.md](./GAME_STATE_TEMPLATE.md)
- [docs/TO_BOARD_UI_GAME_TEAM.md](./TO_BOARD_UI_GAME_TEAM.md)
- [docs/BOARD_UI_DEMO_RUNBOOK.md](./BOARD_UI_DEMO_RUNBOOK.md)

这部分重点不是“游戏本身多复杂”，而是“语音中枢能否控制 UI，游戏能否把状态返回给语音中枢”。

典型流程：

```text
孩子说：星宝星宝，我要玩游戏
-> 语音识别出“我要玩游戏”
-> 中枢生成 open_game / start_game 指令
-> 主界面切到小游戏界面
-> 游戏产生答对/答错/提示/分数等状态
-> 中枢接收状态
-> 星宝用 TTS 说鼓励语，并切换表情
```

### 第五步：掌握视觉健康提醒

先读：

- [docs/XINGBAO_STATE_INPUTS.md](./XINGBAO_STATE_INPUTS.md)
- [docs/examples/vision_state_face_too_close.json](./examples/vision_state_face_too_close.json)

视觉模块在材料里可以写成：

```text
视觉检测模块负责观察孩子是否离屏幕过近、是否需要喝水或休息。
它不直接控制语音或界面，而是把检测结果写成统一状态，交给中枢判断。
中枢再决定是否触发 TTS 提醒、屏幕提示和表情变化。
```

### 第六步：掌握机械臂补充模块

先读：

- [docs/SOFTWARE_ROBOTIC_ARM_SUPPLEMENT.md](./SOFTWARE_ROBOTIC_ARM_SUPPLEMENT.md)
- [docs/HARDWARE_ARM_SUPPLEMENT.md](./HARDWARE_ARM_SUPPLEMENT.md)
- [docs/ARM_GROUP_INTERFACE.md](./ARM_GROUP_INTERFACE.md)

机械臂在当前材料里建议这样定位：

```text
机械臂是星宝多模态表达层的补充输出通道。
软件中枢只发送高层动作名称，例如 nod、shake_head、wave_hand 或 group_1。
底层舵机角度、PWM、GPIO、串口协议由机械臂控制端负责，不能由大模型直接生成。
```

这句话非常重要：**大模型不直接控制机械臂，机械臂只执行白名单内的高层动作。**

---

## 3. 当前项目可以写成哪些模块

| 模块 | 作用 | 材料中推荐写法 |
| --- | --- | --- |
| 语音唤醒 | 平时静默，听到“星宝星宝”后进入交互 | 本地唤醒降低云端依赖，保护隐私 |
| VAD 收音 | 判断孩子开始/结束说话 | 解决儿童语音长短不稳定的问题 |
| ASR | 把孩子语音转为文字 | 为后续意图识别和大模型回答提供文本输入 |
| 中枢调度 | 判断当前该聊天、开游戏、查游戏状态还是健康提醒 | 系统“大脑”，负责多模块协同 |
| 固定规则线 | 对确定任务快速响应，如打开游戏、查询分数、退出 | 保证演示稳定，不让大模型乱控制 |
| 大模型回答线 | 处理开放式聊天和儿童陪伴回答 | 让回答更自然、更像日常对话 |
| TTS 队列 | 把文字转成语音并排队播放 | 避免多段语音重叠 |
| 打断机制 | 播放中再次唤醒可中断 | 更接近真实对话 |
| 主界面 UI | 展示星宝形象、表情和游戏入口 | 负责视觉反馈 |
| 小游戏 | 提供答题、选择、反馈、分数等状态 | 体现“学习通过游戏发生” |
| 视觉检测 | 检测距离过近、喝水/姿态提醒等 | 实现健康陪伴 |
| 机械臂补充 | 执行点头、摇头等高层动作 | 增强陪伴感，但不作为主控制逻辑 |

---

## 4. 系统核心流程可以这样写

### 4.1 日常对话流程

```text
孩子说“星宝星宝”
-> 本地唤醒成功
-> 星宝进入倾听状态
-> 孩子说“星宝你好”
-> VAD 截取语音
-> ASR 转文字
-> 中枢判断为普通问候
-> 大模型或本地模板生成简短回复
-> 屏幕显示微笑表情
-> TTS 播放“你好呀”
```

### 4.2 打开游戏流程

```text
孩子说“我要玩游戏”
-> ASR 得到文本
-> 固定规则命中 start_game/open_game
-> 中枢向主界面发送游戏启动指令
-> UI 切换到小游戏界面
-> 星宝说“进入游戏啦，请选择一个游戏，再选择难度”
```

### 4.3 游戏反馈流程

```text
孩子点击答案
-> 小游戏判断答对/答错
-> 小游戏返回 game_event 或 mini_game_state
-> 中枢生成鼓励语
-> TTS 播放
-> 屏幕表情切换为 smile/thinking/encourage
-> 可选机械臂执行 nod 或 shake_head
```

### 4.4 健康提醒流程

```text
视觉模块检测孩子距离屏幕过近
-> 生成 vision_state
-> 中枢判断健康提醒优先级高于普通游戏反馈
-> 星宝播放“你离屏幕有点近啦，往后坐一点哦”
-> 屏幕显示关心表情和护眼提示
```

### 4.5 机械臂协同流程

```text
中枢生成高层动作 arm_action = shake_head
-> 动作白名单检查
-> 机械臂适配器通过 IPC/TCP 发送动作名
-> 机械臂控制端把 shake_head 映射为具体动作组
-> 执行动作
```

材料里不要写：

```text
大模型输出舵机角度
大模型直接控制 PWM
大模型直接控制 GPIO
```

这些写法不安全，也不符合当前项目设计。

---

## 5. 项目技术难点怎么写

下面这些可以直接作为“项目难点与解决方案”的提纲。

### 难点一：语音交互要像真人一样自然

问题：

- 儿童说话可能断断续续，音量忽大忽小。
- 如果录音截断不准，就会识别不完整。
- 如果 TTS 播放太慢，孩子会以为星宝没听见。

解决：

- 使用本地唤醒词保持低功耗待机。
- 使用 VAD 判断语音起止。
- 使用 ASR 将语音转文字。
- TTS 使用队列机制，避免多段语音同时播放。
- 播放过程中允许再次唤醒打断，模拟日常对话。

### 难点二：固定规则和大模型需要分工

问题：

- 如果所有事情都交给大模型，打开游戏、退出、查分数等动作会不稳定。
- 如果全部用固定模板，星宝又会显得呆板。

解决：

- 中枢分成两条线：
  - 固定动作规则线：只负责确定性任务，如打开游戏、切换界面、查询游戏状态。
  - 回答线：调用 Qwen-plus 生成简短自然的儿童友好回答。
- 这样既保证演示和控制稳定，又保留自然对话能力。

### 难点三：多个 Python 程序之间要协同

问题：

- 语音中枢、主界面、小游戏、视觉检测可能是不同进程。
- 如果直接互相调用内部变量，容易线程冲突、界面卡死。

解决：

- 使用本地 TCP + UTF-8 NDJSON 做进程间通信。
- 每一行 JSON 是一个完整指令或状态。
- UI、游戏、语音只交换高层语义，不交换底层实现细节。

典型消息：

```json
{"type":"assistant_output","payload":{"screen_expression":"smile","ui_command":{"name":"start_game"}}}
```

### 难点四：主界面和游戏显示要在板卡上稳定运行

问题：

- 通过 SSH 启动 Pygame 时，可能找不到真实显示器。
- SDL 可能误用 offscreen/dummy 驱动，导致程序运行但屏幕无画面。
- UI 主线程和网络线程混用可能导致 Pygame 卡死。

解决：

- 板卡启动脚本统一设置显示环境。
- Pygame 界面操作回到 UI 主线程执行。
- 中枢只发送 UI 指令，不直接操作 Pygame 内部对象。
- 使用日志确认 `desktop.py` 是否真正进入前台显示。

### 难点五：小游戏语音和屏幕状态要同步

问题：

- 如果小游戏自己随意播放语音，可能和屏幕题目不同步。
- 多个语音来源同时发声，会造成体验混乱。

解决：

- 小游戏只上报状态，不直接决定最终播报节奏。
- 中枢统一管理 TTS 队列。
- 游戏反馈使用 `game_event`、`mini_game_state` 等结构化状态。
- 中枢根据状态生成对应语音、表情和动作。

### 难点六：儿童安全与隐私

问题：

- 儿童项目不能随意保存敏感信息。
- 大模型输出不能直接变成硬件控制命令。

解决：

- 只允许保存兴趣、偏好、近期情绪等非敏感信息。
- 禁止保存家庭住址、电话、学校、班级、精确位置、家长联系方式。
- 所有硬件动作必须经过白名单。
- 机械臂只接收高层动作名，不接收底层硬件参数。

### 难点七：机械臂与星宝人格反馈的一致性

问题：

- 机械臂动作如果太夸张，会干扰儿童注意力。
- 如果动作和语音、表情不同步，会显得割裂。

解决：

- 机械臂作为表达层的一部分，由中枢统一调度。
- 每个动作只表示明确语义：
  - `nod`：肯定/鼓励
  - `shake_head`：温和纠错
  - `wave_hand`：欢迎/告别
  - `stay_still`：默认安全状态
- 底层动作组由机械臂端实现，星宝软件只发动作名称。

---

## 6. 可直接引用的开发文档目录

### 产品与总体说明

- [docs/PROJECT_INTRO.md](./PROJECT_INTRO.md)：项目介绍
- [docs/PRODUCT_DIRECTION.md](./PRODUCT_DIRECTION.md)：产品方向
- [docs/PROJECT_INTRODUCTION_DRAFT.md](./PROJECT_INTRODUCTION_DRAFT.md)：项目简介草稿

### 软件架构与流程

- [docs/SOFTWARE_ARCHITECTURE_FLOW_DESIGN.md](./SOFTWARE_ARCHITECTURE_FLOW_DESIGN.md)：软件系统流程图设计
- [docs/MODULE_COLLABORATION_PROTOCOL.md](./MODULE_COLLABORATION_PROTOCOL.md)：模块协同协议
- [docs/XINGBAO_COORDINATION_READINESS.md](./XINGBAO_COORDINATION_READINESS.md)：中枢协同准备状态
- [docs/CENTRAL_RULES_AND_TEMPLATES.md](./CENTRAL_RULES_AND_TEMPLATES.md)：中枢规则和模板回答

### 语音链路

- [docs/TO_VOICE_TEAM.md](./TO_VOICE_TEAM.md)：语音对接说明
- [docs/TTS_QUEUE_AND_BARGE_IN.md](./TTS_QUEUE_AND_BARGE_IN.md)：TTS 队列和打断机制
- [docs/BOARD_UPLOAD_QUICKSTART.md](./BOARD_UPLOAD_QUICKSTART.md)：板卡上传与运行

### 主界面和小游戏

- [docs/GAME_XINGBAO_API_SPEC.md](./GAME_XINGBAO_API_SPEC.md)：游戏与星宝 API 协议
- [docs/GAME_STATE_TEMPLATE.md](./GAME_STATE_TEMPLATE.md)：小游戏状态模板
- [docs/GAME_XINGBAO_COLLAB_RULES.md](./GAME_XINGBAO_COLLAB_RULES.md)：游戏协同规则
- [docs/TO_BOARD_UI_GAME_TEAM.md](./TO_BOARD_UI_GAME_TEAM.md)：给主界面/游戏组的对接说明
- [docs/BOARD_UI_DEMO_RUNBOOK.md](./BOARD_UI_DEMO_RUNBOOK.md)：板卡 UI demo 运行手册

### 视觉与健康提醒

- [docs/XINGBAO_STATE_INPUTS.md](./XINGBAO_STATE_INPUTS.md)：游戏状态和视觉状态输入
- [docs/XINGBAO_GROWTH_GUIDANCE_LAYER_DESIGN.md](./XINGBAO_GROWTH_GUIDANCE_LAYER_DESIGN.md)：成长引导层设计

### 表情与表达

- [docs/XINGBAO_EXPRESSION_GUIDE.md](./XINGBAO_EXPRESSION_GUIDE.md)：星宝表情指南
- [docs/XINGBAO_EXPRESSION_SCENARIOS.md](./XINGBAO_EXPRESSION_SCENARIOS.md)：表情场景
- [docs/XINGBAO_EVENT_RESPONSE_TABLE.md](./XINGBAO_EVENT_RESPONSE_TABLE.md)：事件响应表

### 硬件与关系图

- [docs/HARDWARE_ARCHITECTURE_AND_DIAGRAM_SPEC.md](./HARDWARE_ARCHITECTURE_AND_DIAGRAM_SPEC.md)：硬件架构图说明
- [docs/XINGBAO_RELATION_DIAGRAM_LATEX.tex](./XINGBAO_RELATION_DIAGRAM_LATEX.tex)：关系图 LaTeX 源码
- [docs/XINGBAO_RELATION_DIAGRAM_LATEX.pdf](./XINGBAO_RELATION_DIAGRAM_LATEX.pdf)：已生成关系图 PDF
- [docs/XINGBAO_RELATION_DIAGRAM_PROMPT.md](./XINGBAO_RELATION_DIAGRAM_PROMPT.md)：关系图生成提示词

### 机械臂补充

- [docs/SOFTWARE_ROBOTIC_ARM_SUPPLEMENT.md](./SOFTWARE_ROBOTIC_ARM_SUPPLEMENT.md)：软件系统机械臂补充材料
- [docs/HARDWARE_ARM_SUPPLEMENT.md](./HARDWARE_ARM_SUPPLEMENT.md)：硬件机械臂补充材料
- [docs/ARM_GROUP_INTERFACE.md](./ARM_GROUP_INTERFACE.md)：机械臂动作组接口说明

---

## 7. 推荐材料结构

你可以按这个目录写最终项目材料：

```text
1. 项目背景与目标
2. 产品定位：智能儿童早教陪伴桌
3. 系统总体架构
   3.1 硬件架构
   3.2 软件架构
   3.3 模块协同方式
4. 核心功能
   4.1 语音唤醒与连续对话
   4.2 触控主界面与星宝表情
   4.3 小游戏协同
   4.4 视觉健康提醒
   4.5 TTS 队列与打断
   4.6 机械臂补充反馈
5. 技术实现
   5.1 本地唤醒与 VAD
   5.2 ASR + Qwen-plus + TTS
   5.3 中枢固定规则与大模型回答双路线
   5.4 TCP/NDJSON 进程通信
   5.5 高层动作白名单与安全适配
6. 项目难点与解决方案
7. 演示流程
8. 当前进度与后续优化
```

---

## 8. 答辩时可以讲的完整 demo

推荐讲这个流程：

```text
1. 孩子坐到星宝桌前。
2. 孩子说“星宝星宝”唤醒系统。
3. 星宝进入倾听状态，屏幕表情切换。
4. 孩子说“星宝你好”。
5. 星宝用儿童友好的语气回应，并显示微笑表情。
6. 孩子说“我要玩游戏”。
7. 中枢识别为固定动作规则，不走开放式大模型乱猜。
8. 主界面切换到小游戏界面。
9. 星宝提示孩子选择游戏和难度。
10. 孩子答题。
11. 小游戏把答对/答错状态返回中枢。
12. 中枢统一触发 TTS 鼓励、表情变化和可选机械臂动作。
13. 视觉模块检测孩子距离屏幕较近。
14. 星宝触发护眼提醒，并提示孩子注意喝水。
```

这个 demo 能体现：

- 语音闭环
- 主界面联动
- 小游戏状态回传
- TTS 播报
- 表情反馈
- 视觉健康提醒
- 机械臂高层动作扩展
- 中枢调度能力

---

## 9. 材料中不要这样写

不要写：

- “大模型直接控制机械臂”
- “大模型输出舵机角度”
- “系统直接控制 PWM/GPIO”
- “项目核心是机械臂”
- “摄像头会识别孩子身份并长期保存”
- “星宝会记录孩子住址、学校、家长电话”

推荐写：

- “中枢输出高层动作意图”
- “动作经过白名单和安全适配”
- “机械臂是多模态表达层的补充”
- “视觉模块只输出健康/状态事件”
- “系统只保存非敏感偏好和成长线索”

---

## 10. 一段可以直接放进材料的总结

星宝项目围绕“儿童早教陪伴桌”这一具体场景，构建了语音、触控、小游戏、视觉感知和多模态反馈协同的交互系统。系统采用本地唤醒词和 VAD 完成自然语音入口，通过 ASR、固定规则、大模型回答和 TTS 构成完整语音闭环；同时使用统一中枢调度层，将孩子的语音意图、触控操作、小游戏状态和视觉健康事件转化为结构化响应计划，再驱动屏幕表情、语音播报、游戏界面和可选机械臂动作。项目的关键设计思想是：确定性控制走固定规则，开放式陪伴走大模型回答，硬件反馈走高层动作白名单，从而在保证儿童安全、隐私保护和演示稳定性的前提下，实现自然、有趣、可扩展的早教陪伴体验。

