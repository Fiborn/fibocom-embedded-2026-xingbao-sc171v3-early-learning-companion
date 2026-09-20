# 历史板卡兼容说明

## 结论

项目主线已经调整为智能儿童早教陪伴桌，当前阶段先移除机械臂方向，集中建设语音、触控桌面屏视觉交互、实物桌面玩法、多模态感知预留和健康守护。

因此，板卡串口、机械臂动作、舵机映射和下位机协议不再是后续产品主线。本文件仅记录旧实现的兼容边界，方便维护既有代码和测试。

## 当前状态

仓库中仍保留以下历史兼容能力：

- `core/serial_bridge.py`
- `core/action_safety.py`
- `core/action_bus.py`
- `config/action_schema.json`
- `tests/test_serial_bridge.py`
- `tests/test_action_safety.py`

这些模块的存在不代表产品继续推进机械臂。新功能默认不应该依赖 `serial_port`、`arm_action`、舵机动作或原始硬件输出。

## 兼容边界

如果确实需要维护旧板卡验证，只允许发送经过清洗的高层动作 JSON，不允许发送舵机角度、PWM、GPIO 或其他原始硬件命令。

旧协议示例：

```json
{"type":"action","action":{"screen_expression":"smile","led_mode":"warm_breath","arm_action":"wave_hand"}}
```

这类输出必须经过 whitelist 和 sanitizer。LLM 不得直接生成任何硬件控制细节。

## 新主线替代方式

旧机械动作在新主线中应替换为桌面视觉和语音反馈：

| 旧机械/板卡反馈 | 新主线反馈 |
| --- | --- |
| `wave_hand` | 星宝入场动画、欢迎语音、桌面柔光 |
| `nod` | 星宝点头表情帧、确认音效、槽位亮起 |
| `shake_head` | 温和纠错表情、重新提示语音 |
| `point_left` / `point_right` | 左右桌面区域高亮、箭头光效、语音指引 |
| `small_dance` | 星宝庆祝动画、星光粒子、鼓励播报 |
| `warm_breath` / `blue_breath` | 屏幕环境光、背景光幕和状态色 |

## 后续建议

- 不再新增机械臂 API、串口命令或舵机动作表。
- 保留现有测试，防止历史代码在未清理前破坏安全边界。
- 后续若彻底删除旧板卡兼容层，应单独开迁移任务，同步更新 `app.py`、`main.py`、`core/color_block_game.py`、`core/color_block_ui.py` 和相关测试。
