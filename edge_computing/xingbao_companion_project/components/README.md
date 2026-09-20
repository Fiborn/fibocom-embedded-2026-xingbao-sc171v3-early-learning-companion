# 板卡运行组件源码

本目录保存比赛基线中原先位于独立板卡目录的组件源码。将它们纳入同一个 Git 提交，
是为了保证中枢、触屏 UI、机械臂和团队交接记录可以原子同步，避免只同步中枢造成
开发断层。

## 路径映射

| 仓库路径 | 板卡运行路径 | 当前基线 |
|---|---|---|
| `components/touch_ui/` | `/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_touch_game_bridge` | `hotfix-ui-drawing-praise-20260726-003` |
| `components/arm_soarm101/` | `/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_competition_fix_20260721_r5/project/hardware/soarm101` | 审计快照，入口 `arm_action_server_soft_nod.py` |

根目录仍对应中枢源码。板卡运行目录只是部署目标，不允许直接作为 Git 工作区。

## 运行时数据

不得提交组件运行产生的日志、缓存、录音、截图、画作、儿童数据、设备密钥或环境变量。
触屏基线只导入 `TOUCH_RELEASE_MANIFEST.json` 明确列出的文件；机械臂基线只导入脱敏
审计清单中的源码和非敏感配置。
