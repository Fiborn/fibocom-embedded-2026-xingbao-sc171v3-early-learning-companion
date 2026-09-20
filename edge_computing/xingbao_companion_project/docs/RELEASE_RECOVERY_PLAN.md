# 星宝稳定版：冻结、备份与恢复方案

## 冻结版本

- 标签：`demo-freeze-20260725`
- 用途：现场演示前的稳定恢复点；禁止在此标签上继续修改功能。
- 中央端安装包：`dist/xingbao_companion_central.zip`
  - SHA256：`01ac91e6449509ef5df10d7fcf6de6ac1935cc83b02695d73d68e0a96180328a`
- 触控游戏安装包：`dist/xingbao_touch_game_board.zip`
  - SHA256：`664f602c64c8301a70077a962ce0d1330a9558a642c5184b1af744369f9f94cc`

安装包不进入 Git 历史：中央包约 200 MB，超过普通 GitHub Git Blob 的 100 MB 限制。两个 ZIP 与对应 `.sha256` 必须作为同名 GitHub Release 的附件上传。

## 四层保险

1. 本机冻结包：`dist/` 的两个 ZIP、两个 SHA256 文件和 `deploy/one_click_deploy.ps1`。
2. 私有 Git 仓库：保存源代码、部署脚本、测试、清单和版本标签。
3. GitHub Release：保存两个固定 ZIP 与 SHA256 文件；用于本机丢失后的下载恢复。
4. 板卡运行备份：保留 `/home/fibo/.config/xingbao/runtime.env`、触控游戏 `saves/`、记忆、画作、家长模式状态和 systemd 用户服务配置。

## 数据边界

- Git / Release 可以保存代码和安装包。
- `runtime.env` 可能包含 API Key，不能提交到 Git、不能上传到 Release。
- 孩子的对话记忆、画作、游戏存档和家长摘要不提交 Git；部署脚本必须原样保留这些数据。
- 内存中的进程状态不是备份；断电或重启后会消失。只有已落盘、已校验且可恢复的文件才属于备份。

## 明日现场恢复

1. 板卡开机，插好 USB 摄像头并联网。
2. 在 Windows PowerShell 运行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Projects\xingbao_companion\deploy\one_click_deploy.ps1"
   ```

3. 脚本将校验两个 SHA256，保留运行数据，启动触控界面、机械臂安全服务、语音中枢、游戏和视觉服务。
4. 通过条件：四个服务 active、端口 8764/8765/8766 可用、百宝箱为 85 项、摄像头可读到实际画面。

## 故障恢复顺序

1. 本机与板卡均正常：直接执行一键部署脚本。
2. 本机安装包丢失：从 `demo-freeze-20260725` 的 GitHub Release 下载两个 ZIP 和 `.sha256`，放回 `dist/` 后执行同一脚本。
3. 本机源码丢失：从私有 Git 仓库检出 `demo-freeze-20260725` 标签，再下载对应 Release 附件。
4. 板卡系统重装：先恢复 `runtime.env` 与数据备份，再部署固定 Release；不要把 API Key 或儿童数据上传到 GitHub。

## 每次变更的固定流程

1. 修改后运行 `python -m compileall .` 和 `pytest`。
2. 重建安装包并记录新 SHA256。
3. 在板卡执行一次完整部署和健康检查。
4. 提交源码、打新标签、上传同标签的 Release 附件。
5. 只在全部验收后，将该标签称为“稳定版”。
