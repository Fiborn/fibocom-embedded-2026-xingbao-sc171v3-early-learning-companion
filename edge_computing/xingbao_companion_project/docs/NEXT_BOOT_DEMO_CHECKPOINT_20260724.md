# 星宝下次开机恢复清单（2026-07-24）

## 1. 本次封存状态

- 恐龙引导表达流程已完成：支持近义表达、多通道情绪融合、语音兜底、中断续接、完整重述、兴趣记忆和主动画画建议。
- 形状游戏流程已完成：每局首题为三角形；首次答错保持同题，提示后发出一次高层 `handshake`，握手后同题重试；余题和其他游戏保留原逻辑。
- 家长模式已完成：正确答案立即进入；连续两次错误只锁定家长入口 60 秒。
- 画画、百宝箱、回忆本、语音记忆、视觉状态、游戏结算和家长摘要已在隔离数据目录完成全流程模拟。
- `pc5.py` 未修改。
- 中央端完整回归：284 项通过。
- 触控端完整回归：189 项通过。
- 下电前专项回归：17 项通过。

## 2. 封存包

### 中央端

- 文件：`D:\Projects\xingbao_companion\dist\xingbao_companion_central.zip`
- 大小：200143736 字节
- SHA-256：`EEAB99BC4793363C7F2244B74D68B448D07F9AF49F0CF1F00E40F05C9774D8D1`
- 板卡目标目录：`/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion`

中央包已确认包含：

- `core/guided_expression_flow.py`
- `tools/simulate_demo_flow.py`
- `docs/DEMO_FLOW_SCRIPT.md`

### 触控端

- 文件：`D:\Projects\xingbao_companion\work\incoming\xingbao_touch_game_latest\xingbao_touch_game\dist\xingbao_touch_game_board.zip`
- 大小：38780481 字节
- SHA-256：`8E05AC259EEDB1E751A4108C11C86F7BE412F8624324D41A512070F269C41D7F`
- 现场统一启动脚本使用的板卡目录：`/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge`

触控包已确认包含：

- `src/growth_support.py`
- `src/games/shape_game.py`
- `desktop.py`

## 3. 本次完整模拟证据

隔离目录：

`D:\Projects\xingbao_companion\work\tmp\demo_flow_live_retry_20260724_224015`

其中包含：

- `data/memory.json`
- `data/conversation_history.json`
- `data/parent_summaries.json`
- `saves/latest_save.json`
- `saves/xingbao_memory.json`
- `saves/artworks/`
- `saves/memory_shots/`
- `logs/`

本次结果：

- 安全记忆包含“恐龙、腕龙”，昵称未持久化。
- 回忆本读取到 20 条聊天记录。
- 形状游戏完成 5 题，故意答错 1 次，同题重试成功。
- 只产生一个高层 `handshake`。
- 回忆本包含画作与游戏成长记录。
- 家长算术正确答案直接进入，生成 7 条家长摘要。

## 4. 下次板卡开机顺序

当前板卡 IP：`10.21.236.12`

1. 给显示屏、板卡、摄像头和机械臂上电。
2. 等待板卡物理桌面与 Weston 就绪。
3. 从电脑执行 `adb root`，再进入板卡终端。
4. 确认中央端、触控端和机械臂服务文件仍在：

```sh
test -f /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion/main.py
test -f /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge/desktop.py
test -f /home/fibo/xingbao_project/soarm101_module/arm_action_server.py
```

5. 使用统一入口启动：

```sh
cd /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion
sh deploy/board_start_full_demo.sh
```

6. 必须等到终端出现：

```text
[ready] display=:0 ui=127.0.0.1:8765 voice=127.0.0.1:8766 arm=127.0.0.1:8764 vision=central-managed
```

7. 出现 `[ready]` 后，先做三项短检查：

- 说“星宝星宝”，确认能够唤醒。
- 打开小抽屉和百宝箱，确认触控正常。
- 在保证机械臂周围安全后，只做一次握手测试。

## 5. 启动失败时查看

```sh
tail -n 100 /tmp/xingbao_ui_start.log
tail -n 100 /tmp/xingbao_central_start.log
tail -n 100 /tmp/xingbao_arm_action_server.log
```

不要在启动失败时连续重复触发机械臂动作。先根据日志确认 UI、语音或机械臂服务中哪一项没有就绪。

## 6. 重要数据说明

- `.env` 不进入发布包，运行密钥继续从 `/home/fibo/.config/xingbao/runtime.env` 加载。
- 不删除板卡现有 `data/`、`saves/` 和机械臂审核动作库。
- 重新部署压缩包时，先保留板卡现有运行数据，再替换程序文件。
- 正式演示前家长模式只答对，不主动触发 60 秒锁定。
