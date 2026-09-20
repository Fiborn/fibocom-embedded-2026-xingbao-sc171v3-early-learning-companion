# 部署说明

## 代码位置与运行环境

应用位于 `edge_computing/xingbao_companion_project`。Python 导入与资源路径以该目录为工作目录。SC171V3 原板卡运行 Ubuntu，正式界面使用原生 Wayland。电脑端文本测试不能代替板端音频、摄像头、触控和 NPU 验证。

## 安装依赖

先执行根 README 中的基础安装。按启用功能补充：

```bash
python3 -m pip install -r requirements-wake-word.txt
python3 -m pip install -r requirements-vision-board.txt
python3 -m pip install -r components/touch_ui/requirements.txt
```

这些是原工程已有依赖文件，尚未在全新 SC171V3 系统上重新安装验证。板端原生库和 `tools/runtime` 中的程序面向 Linux ARM64，不能直接在 Windows 执行。

## 凭据

在运行环境中设置 `DASHSCOPE_API_KEY`，可选设置 `MOONSHOT_API_KEY` 与 `QWEATHER_API_KEY`。也可按现有启动脚本说明使用用户目录中的 `~/.config/xingbao/runtime.env`，并将权限设为 `600`。仓库根 `.env.example` 仅列出变量名称；不要把真实 `.env` 或凭据文件提交到 Git。

发布副本已移除 `pc5.py` 和视觉场景描述模块中的硬编码密钥。原始备份仍在本机；不要直接上传原始备份或原 Git 历史。

## 板端路径

现有部署脚本以 `/home/fibo/xingbao_companion_project` 为固定路径。为了兼容它们，可将仓库中应用子目录复制到该位置，或在不存在同名路径时建立指向应用目录的符号链接。已有部署应先备份并按实际路径调整，不要覆盖已有目录。

正式触控界面启动脚本为 `deploy/board_start_wayland_ui.sh`，它要求活动 Wayland 会话。运行前应核对 `XDG_RUNTIME_DIR`、`WAYLAND_DISPLAY`、Python 与 Pygame 安装路径。旧文档中的 X11/XWayland 启动方式仅作历史参考。

语音启动与联调示例见应用内 `deploy/board_start_demo.sh`；执行系统服务安装脚本之前，应先核对其中的用户、路径与音频设备配置。

## 模型与许可

`.onnx`、`.pt`、`.tflite` 和原生动态库由 Git LFS 管理。缺少实际资源而只有 LFS 指针时，执行 `git lfs pull`。提交前需核对目标 GitHub 账号的 LFS 配额。

第三方模型和二进制的版本、来源及许可应以原分发方为准。本次整理没有训练或替换模型，也没有重新构建原生库。
