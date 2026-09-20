# 星宝稳定版锁定清单

## 唯一基准

- 基准时间：2026-07-24 23:13（Asia/Shanghai）
- 状态：完整演示流程验证结束、下电保存前的稳定版本
- 锁定原则：未经用户明确授权，不升级、不重构、不追加功能、不替换依赖
- 运行数据：板卡现有 `data/`、`saves/`、画作、回忆本和日志不属于程序回退范围

## 发布包

### 中央端稳定包

- 文件：`dist/xingbao_companion_central.zip`
- 大小：200146290 字节
- SHA-256：`3C50A8EE6AEB0B047817BAD9C66F8B95281D75E15F5EC941BF54C61B2AE9EF46`
- 板卡目录：`/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion`

说明：23:13 原中央压缩包曾被覆盖；当前包由恢复后的23:13源码重新生成，因此压缩包二进制哈希与历史记录不同。

### 触控端稳定包

- 文件：`work/incoming/xingbao_touch_game_latest/xingbao_touch_game/dist/xingbao_touch_game_board.zip`
- 大小：38780481 字节
- SHA-256：`8E05AC259EEDB1E751A4108C11C86F7BE412F8624324D41A512070F269C41D7F`
- 板卡目录：`/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge`

## 关键运行文件哈希

### 中央端

- `main.py`：`fb53830ccf6a69efacb002f633a3f28c310340b6abbf1671efb2cb6f3df029d5`
- `app.py`：`3e2b799c7da00e250fc61f347bd1e1ea168eb498315a79b15d6f2e2876156f68`
- `core/guided_expression_flow.py`：`299f0e599bbb084cd27355e4d0cc742d2afe23e87410007a75f5bf884ebc39a9`
- `core/game_speech_server.py`：`e96266ae80185737f366c54fafe97325a99fc5695787f6fe7343ca313c3226db`
- `deploy/board_start_demo.sh`：`dd30ae188543320611cb27b4f456e0336c8ee6b10e8afea39c4c6c5c0ef1a1ff`
- `tools/board_health_check.py`：`974c41ccc03b6c8208fe38122c35f4792f0bbe9ac598bc11075c5448c568add5`

### 触控端

- `desktop.py`：`db0f3e29d115466054e064f81fbd04497ac6ac5b37473ef99aef3bb4f228345c`
- `src/board_adapter.py`：`f17b07ea03798c00c155361ccc345443de9c7d6cb251b1fef8858793dc426708`
- `examples/central_ui_dispatcher_example.py`：`c7e68d8725742eaf9ca8e483546dc87049ec991267c449b20f0198c14faed84f`
- `src/growth_support.py`：`321fe94c622d2f43b4a74dd2e2c8cb3fba19625536d7ea21eba59698fae19063`
- `src/games/shape_game.py`：`13c4a6b8d857e705e719051c4d8ceb73d95e32f354743772708025753cc96a95`

## 锁定验收

- 中央端完整回归：284 项通过
- 触控端完整回归：189 项通过
- 板卡服务端口：机械臂 `8764`、触控界面 `8765`、游戏语音 `8766`
- 电脑源码、保存包关键文件、板卡运行文件哈希一致

## 凌晨增量备份

- 文件：`D:\Projects\xingbao_post_2313_changes_backup_20260725_0130.zip`
- SHA-256：`0ABD1251039CB77CC5B7ADD69E736F47B7E750617C9379F2D6BD31BCB93D4D2D`
- 用途：仅用于人工明确要求恢复23:13之后的增量时使用，不属于稳定版
