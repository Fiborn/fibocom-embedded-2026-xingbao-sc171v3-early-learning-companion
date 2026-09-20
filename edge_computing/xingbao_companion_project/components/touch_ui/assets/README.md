# Assets

运行时资源由`src/asset_loader.py`统一加载，默认先读`src/assets_manifest.py`中的别名映射，再从本目录读取PNG或WebP。资源缺失时会回退到`pygame`绘制，不会因为单张图损坏而直接崩溃。

当前素材来源：
- `D:\Jeff's home\4-竞赛\202604嵌入式竞赛\屏幕交互\xingbao_asset_pack`
- 仅复制运行时需要的独立PNG，不直接使用contact sheet或源切片。

目录用途：
- `backgrounds/`：主页、游戏页、报告页背景，按cover模式铺满并叠加深色遮罩。
- `characters/orb/`：紫色星宝四状态图。运行时会按manifest中的裁切元数据去掉原素材边角状态字。
- `icons/mission/`：主页任务图标、星星奖励、能量核心。
- `icons/shapes/`：认形状页发光图标。
- `icons/system/`：返回箭头、演示点击指针、记录图标。
- `ui/`：玻璃面板、任务卡、按钮底图。
- `ui/feedback/`：反馈条、状态条、摘要页底部装饰。

当前运行时别名示例：
- `bg_home`→`backgrounds/home_stage.png`
- `xingbao_happy`→`characters/orb/xingbao_orb_happy.png`
- `button_primary`→`ui/button_primary.png`
- `icon_touch`→`icons/system/touch_pointer.png`

绘制规则：
- 背景使用cover并加半透明深色veil。
- 图标、角色、报告徽标使用contain，避免变形。
- 文字只落在组件预留安全区内，不直接压在素材边缘。

后续如果接入本地语音、机械臂或视觉模块，可以继续把新增素材放入本目录，并只在manifest里追加映射，不需要把资源路径散落到页面代码里。
