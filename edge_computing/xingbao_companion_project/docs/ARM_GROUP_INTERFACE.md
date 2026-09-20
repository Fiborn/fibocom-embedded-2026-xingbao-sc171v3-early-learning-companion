# 星宝机械臂动作 IPC 接口

## 1. 对外动作名

星宝中枢只发送两个高层动作名：

| 星宝发送值 | 机械臂内部动作组 | 含义 |
|---|---|---|
| `shake_head` | `group_2` | 摇头 |

当前演示阶段暂停使用点头动作。所有原本请求 `nod` 的正向反馈会在 IPC 出口临时转换为 `shake_head`，因此机械臂只会收到 `shake_head`。`group_2` 仅由机械臂接收程序内部映射，星宝中枢、语音模块和游戏模块不得发送 `group_*`。

## 2. 通信协议

- 传输：TCP
- 机械臂地址：`127.0.0.1:8764`
- 编码：UTF-8
- 分帧：NDJSON，每条 JSON 后必须带一个换行符 `\n`
- 方向：星宝中枢连接机械臂接收服务并发送动作

主界面 UI bridge 使用独立的 `127.0.0.1:8765`，不能与机械臂共用 `8764`。

当前唯一发送格式：

```json
{"arm_action":"shake_head"}
```

不发送舵机角度、PWM、串口指令、持续时间、`group` 字段或 `assistant_output` 外层信封。

## 3. 当前游戏调用位点

| 游戏状态 | 发送动作 |
|---|---|
| 选择难度并确认开始 | `nod` |
| 答题正确 | `nod` |
| 儿童完成当前回合 | `nod` |
| 儿童完成游戏 | `nod` |
| 答题错误 | `shake_head` |
| 游戏上报 `child_made_mistake` | `shake_head` |
| 距离屏幕过近或姿势提醒 | `shake_head` |

游戏入口、普通提示、等待选择和无动作状态不发送机械臂消息，避免重复动作。

## 4. Python 调用

```python
from core.arm_action_bridge import send_arm_action_ndjson

send_arm_action_ndjson("shake_head", host="127.0.0.1", port=8764)
```

非法动作（包括 `group_1`、`group_2`）会在发送前被拒绝。

## 5. 板卡联调

接收端启动后，可在项目目录执行：

```bash
python3 -c "from core.arm_action_bridge import send_arm_action_ndjson; send_arm_action_ndjson('shake_head'); print('ok')"
```

预期机械臂程序把 `shake_head` 映射为 `group_2`。恢复点头动作前不调用 `group_1`。
