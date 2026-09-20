# 动作与表情可实现性回填模板

这份模板请交给负责机械臂动作、星宝表情和灯效设计的同学填写。填写完成后，建议另存为：

```text
ACTION_EXPRESSION_FEASIBILITY.md
```

## 填写说明

星宝侧只会输出高层动作名、表情名和灯效名，不会输出舵机角度、PWM、GPIO 或串口原始命令。

请重点判断：

- 能不能实现。
- 是否适合儿童近距离桌面场景。
- 有没有安全风险。
- 如果不能实现，应该用什么替代。
- 是否需要新增或删除动作、表情、灯效。

## 1. 机械臂动作可实现性

| action | 能否实现 | 实现方式 | 安全风险 | 替代方案 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `stay_still` |  |  |  |  |  |
| `wave_hand` |  |  |  |  |  |
| `nod` |  |  |  |  |  |
| `shake_head` |  |  |  |  |  |
| `point_left` |  |  |  |  |  |
| `point_right` |  |  |  |  |  |
| `small_dance` |  |  |  |  |  |

建议填写方式：

```text
能否实现：能 / 不能 / 暂不建议
安全风险：无 / 低 / 中 / 高
替代方案：例如“屏幕左侧高亮 + 星宝眼睛看左”
```

## 2. 星宝表情可实现性

| expression | 能否实现 | 表情资源或动画名 | 使用建议 | 备注 |
| --- | --- | --- | --- | --- |
| `neutral` |  |  |  |  |
| `smile` |  |  |  |  |
| `thinking` |  |  |  |  |
| `curious` |  |  |  |  |
| `sad` |  |  |  |  |
| `surprised` |  |  |  |  |
| `sleepy` |  |  |  |  |

请特别注意：

- `sad` 不能做得太负面，避免让孩子有挫败感。
- `thinking` 要适合等待游戏返回、等待孩子操作、等待语音识别的状态。
- `surprised` 更适合鼓励和通关，不要过度惊吓。

## 3. 灯效可实现性

| led_mode | 能否实现 | 视觉效果 | 使用建议 | 备注 |
| --- | --- | --- | --- | --- |
| `off` |  |  |  |  |
| `blue_breath` |  |  |  |  |
| `warm_breath` |  |  |  |  |
| `yellow_blink` |  |  |  |  |
| `rainbow` |  |  |  |  |
| `red_flash` |  |  |  |  |

请特别注意：

- `red_flash` 只建议用于明确错误或风险提醒，不要频繁使用。
- `rainbow` 只建议用于通关、连续答对、完成任务等积极场景。
- `blue_breath` 更适合聆听、等待、安静状态。

## 4. 游戏事件到反馈的建议映射

请基于真实游戏体验，确认或修改下面这张表。

| 游戏事件 | 建议 screen_expression | 建议 arm_action | 建议 led_mode | 是否合适 | 修改建议 |
| --- | --- | --- | --- | --- | --- |
| 游戏开始 | `smile` | `wave_hand` | `warm_breath` |  |  |
| 等待孩子操作 | `thinking` | `stay_still` | `blue_breath` |  |  |
| 答对 | `smile` | `nod` | `warm_breath` |  |  |
| 答错 | `sad` | `shake_head` | `yellow_blink` |  |  |
| 请求提示 | `curious` | `point_left` / `point_right` / `stay_still` | `yellow_blink` |  |  |
| 通关或完成 | `surprised` / `smile` | `small_dance` | `rainbow` |  |  |
| 暂停或休息 | `sleepy` | `stay_still` | `blue_breath` |  |  |
| 退出游戏 | `smile` | `wave_hand` | `warm_breath` |  |  |

## 5. 建议新增内容

如果你认为当前白名单不够用，请按下面格式填写。

```text
建议新增：
- 类型：action / expression / led_mode
- 名称：
- 使用场景：
- 为什么现有项不够：
- 是否能安全实现：
- 是否可以用现有项替代：
```

## 6. 建议删除或停用内容

如果你认为某个动作、表情或灯效不适合实现，请按下面格式填写。

```text
建议删除或停用：
- 名称：
- 类型：action / expression / led_mode
- 原因：
- 风险：
- 替代方案：
```

## 7. 需要星宝侧配合的内容

请列出需要星宝侧配合的事项，例如：

- 是否需要新增表情名。
- 是否需要把某些动作默认替换为屏幕反馈。
- 是否需要根据颜色、图形、记忆三个游戏分别设计不同反馈。
- 是否需要限制某些动作的触发频率。
- 是否需要在儿童靠近屏幕或桌面时禁用某些动作。

```text
需要星宝侧配合：
1.
2.
3.
```
