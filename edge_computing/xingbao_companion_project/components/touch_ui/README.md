# 星宝陪伴桌V7：教育型触控陪伴小游戏中心

这是面向2–6岁儿童和SC171V3触控屏的本地pygame教育游戏原型。系统提供六款纯触控游戏、儿童自主难度选择、持续运动的星宝角色和可见的演示点击过程。程序完全离线运行，在电脑上可使用鼠标模拟触控。

## 学习桌面入口

新增`desktop.py`作为比赛演示的统一入口。它显示暖色学习桌主界面，支持星宝反馈、小抽屉、回忆本、护眼提醒和家长验证演示，并可启动本项目的完整游戏中心。游戏首页按`ESC`退出后会自动回到学习桌面。

电脑窗口调试：

```bash
python desktop.py --window
```

SC171V3全屏运行：

```bash
python3 desktop.py --fullscreen --low-effects
```

触控时点击左下角“小抽屉”，再点击“一起玩”。实体按键可映射为`G`、回车或空格，从主桌面直接启动游戏；`D`键用于打开或收起小抽屉。

学习桌面当前可演示：

- 点击星宝获得互动提示。
- 小抽屉中的百宝箱、游戏中心、护眼休息和主动陪伴开关。
- 回忆本记录播放与收藏状态切换。
- 网络状态、音量调节、电量状态和二次确认锁屏。
- 20秒护眼倒计时。
- 算术题家长验证，以及验证后的护眼、内容安全与音量设置。
- 游戏退出后自动恢复学习桌面。
- 顶部显示系统当前时间和日期，不再使用背景图中的固定时间。
- 回忆本读取`latest_save.json`中的最近游戏、今日/累计局数、等级和星星。
- 番茄钟支持开始、暂停、继续和重置；默认5分钟，适合现场演示。
- 画板支持鼠标和触控连续绘制，可一键清空。
- 音量和收藏状态保存到`saves/desktop_settings.json`，重启后继续生效。
- 网络状态使用本机网卡地址判断，Linux板卡电量优先读取`/sys/class/power_supply`，不存在电池节点时显示外接电源。
- 小抽屉支持方向键移动焦点，回车或空格确认，便于实体按键映射。
- 默认桌面增加“今日学习”“每日小目标”两个数据组件，以及游戏、专注、画画三个快捷入口。
- 家长验证使用随机三位数加法，正确结果始终高于200；可触控选择，也可用数字键输入后按回车确认。

### 成长积分

学习桌面提供独立的本地积分与成长等级：

- 完整完成一次5分钟专注奖励50积分；暂停或重置不奖励，同一次完成只结算一次。
- 游戏中心每累计新增5颗星星自动兑换25积分；不足5颗的部分会保留到下次累计。
- 画板中产生实际笔迹并点击“完成作品”奖励30积分；同一幅作品不能重复领取，清空后可创作新作品。
- 每200积分提升一级成长等级。
- 积分、完成次数、星星兑换余数和最近30条奖励记录保存在`saves/desktop_settings.json`。
- 桌面右侧成长卡显示当前等级和积分，点击可查看升级进度、完成次数、最近奖励及积分规则。

### 小小展板与成长记录

- 画板中点击“完成作品”后，作品以PNG格式保存到`saves/artworks/`，不会因为退出程序而丢失。
- 作品元数据保存在`saves/desktop_settings.json`，包括标题、完成时间和图片相对路径。
- 桌面底部“展板”入口显示最近三幅作品缩略图，点击作品可以查看大图。
- 每次完成5分钟专注、20秒护眼休息和一幅画作都会写入本地活动记录。
- 展板汇总专注次数、护眼次数和作品数量，并显示最近一次成长活动。
- 本地最多保留50条作品索引和50条活动记录；图片文件保留在作品目录中，方便比赛后导出。

比赛板卡的实体按键若通过GPIO读取，只需在硬件适配层产生与`G`键等价的`pygame.KEYDOWN`事件；桌面层不直接绑定具体GPIO编号，便于适配不同接线。

OpenCV双返回值、百宝箱队友页面和星宝记忆后台的对接方式见`docs/DESKTOP_INTEGRATION.md`。

### 星宝桌面动画

- 待机呼吸光环与环绕星点持续以30FPS运行。
- 每30秒自动穿插思考、打哈欠和眨眼状态，避免桌面长期静止。
- 点击星宝会依次触发开心、思考和打哈欠互动。
- 获得成长积分时自动播放庆祝状态。
- OpenCV距离与喝水提醒拥有最高优先级，会覆盖普通待机动画。
- 桌面新增“今天的小任务”和“星宝状态”组件，实时显示游戏、专注、画作任务和当前动画状态。
- 桌面背景使用移除静态角色后的干净底图，角色由16张透明全身PNG帧独立播放。
- 待机、哈欠、思考、庆祝各4帧；思考帧经过人工筛选和校正，每帧严格只有左右两只手臂。

### 无停顿场景切换

- `desktop.py`启动时使用隐藏窗口预加载游戏背景、角色、图标和本地存档。
- 从桌面进入游戏时只切换显示Surface，不再重复解码资源或重启pygame。
- 游戏退出后复用同一个`XingbaoApp`实例并返回桌面，不复制游戏源码，也不维护两套逻辑。
- 1280×720离屏基准中，预加载约1.305秒发生在启动阶段，桌面到游戏的激活与首帧约0.046秒。

### 回忆本内容

- 回忆本显示最近三条真实记忆，而不是统一的占位提示。
- 记忆类型包括游戏、画作、专注、护眼、学习、故事和星宝陪伴摘要。
- 游戏退出时仅在确实完成新游戏后写入完成游戏、完成局数、累计星星和今日局数。
- 点击每条记忆可查看完整摘要、记录时间和来源模块。
- 星宝或其他队友模块可通过`MemoryBackend.add()`写入新的非敏感记忆摘要。

## 当前边界

- 支持触控屏和鼠标点击。
- 不支持纸片或实体卡片识别。
- 不需要摄像头。
- 不连接真实机械臂。
- 不使用大模型、云服务、Web前后端或网络接口。
- 自动存档只保存本地设备级成长和游戏统计，不上传云端，不保存敏感个人信息或长期儿童画像。

## 小游戏

当前功能包括色彩能量舱、几何星图舱、记忆航线舱、数数星球、英语小练习、神秘小挑战、单模式演示、今日记录、近七日学习记录和本地JSONL日志。

点击任意游戏后先进入难度选择页。低难度为2选1，中难度为4选1，高难度为6选1；孩子每局都可以重新选择。记忆航线对应使用2、3、4个记忆点。高难度积分保持100%，中难度积分为高难度的2/3，低难度积分为高难度的1/2。

### 找颜色

每局5轮，按照所选难度显示2个、4个或6个颜色选项。

### 认形状

每局5轮，按照所选难度显示2个、4个或6个形状选项，图形包括圆形、三角形、正方形、星形、爱心、长方形和椭圆形。

### 记忆小路

每局4轮。低、中、高难度分别使用2、3、4个记忆点。序列不会连续出现相同位置；普通播放节奏为高亮0.8秒、间隔0.4秒、输入前等待0.5秒，慢速演示为高亮1.25秒、间隔0.75秒、输入前等待0.8秒。高亮阶段禁止点击，输入错误后重新播放。

### 数数星球

通过点击数字完成数量对应，题目范围为4至15。低、中、高难度分别提供2个、4个、6个数字选项，始终不需要键盘或拖拽。

### 英语小练习

内置120个幼儿基础词汇，覆盖食物、动物、颜色、数字、家庭、身体、自然、物品和动作。每轮随机采用中译英或英译中，选项数量为2、4或6，并在每轮重新打乱。

### 神秘小挑战

随机挑战混合加减法、乘法和除法，完成后获得双倍积分。混合加减法包含3至5项，答案保持在10至50；乘除法限制在九九乘法表范围内，乘数和除数不会出现1。低、中、高难度分别提供2个、4个、6个答案选项。

每个游戏结束后进入统一结果页，可再玩一次、回到主页或查看今日记录。进入任意游戏的难度选择页后，可点击“演示本模式”，只演示当前游戏。

单模式演示使用可见点击指示器，每次自动点击依次经过说明、移动、按下、结果和步骤间隔五个阶段。指针目标来自当前页面真实可点击rect，逻辑点击点和视觉指针都对准目标中心。默认使用`slow`，也可选择`normal`。主页原总体演示入口已替换为“近七日记录”。

近七日记录使用柱状图展示连续7天的数据：青色柱表示学习时长，金色柱表示完成次数。学习时长只统计正常游戏，不统计自动演示。

## 顶部系统状态

顶部显示本地运行、触控就绪和会话状态；左侧原状态标签区域已经替换为星能升级舱入口。

- “本地”：游戏、日志和存档都在本机或SC171V3本地运行，不依赖云端。
- “触控”：触控屏点击可用，电脑窗口调试时鼠标点击等价于触控。
- “运行中”：当前会话已生成`session_id`，JSONL日志和自动存档可用。

## 星能升级舱

首页左侧提供可点击的星能升级舱。能力只保留三项：星运增幅上限20级，等级为X时有5X%的概率额外获得1颗星星，触发后再有X%的概率获得5颗惊喜星星；专注护盾消耗5颗累计星星购买2个，答错时自动消耗并抵消扣分；魔法药水消耗5颗累计星星购买1瓶，下一局自动使用，使经验×2，但每次答错扣15分。普通游戏每次答错扣5分，每局从100分开始且最低为0分，结算经验会乘以最终得分百分比。低、中、高难度经验倍率分别为50%、约67%、100%，基础星星分别为3、4、5颗；一局中只要出现错题，基础星星至多扣1颗。

星星是跨日期累计的本地货币，不会在每日统计重置时清零。星运增幅达到20级时，额外1颗星星的概率为100%，随后有20%的概率再获得5颗；高难度无错题时对应5+1+5=11颗星星。

## 安装依赖

在项目目录执行：

```bash
python3 -m pip install -r requirements.txt
```

Ubuntu20.04或SC171V3缺少SDL与中文字体时，可安装：

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev libsdl2-mixer-dev fonts-noto-cjk
```

## 运行

电脑窗口模式：

```bash
python3 main.py --window
```

Windows没有`python3`命令时使用：

```powershell
python main.py --window
```

SC171V3全屏模式：

```bash
python3 main.py --fullscreen
```

窗口慢速演示：

```bash
python3 main.py --window --demo-speed slow
```

全屏慢速演示：

```bash
python3 main.py --fullscreen --demo-speed slow
```

需要缩短演示等待时使用`--demo-speed normal`。未知值会提示并回退到`slow`。

板卡性能较低时可使用低特效全屏模式，粒子数量减半并关闭扫描线：

```bash
python3 main.py --fullscreen --low-effects
```

布局调试模式会显示当前页面的重要点击区域，便于检查文字和贴图是否重叠：

```bash
python3 main.py --window --debug-layout
```

默认按`1280×720`设计，也可指定窗口尺寸：

```bash
python3 main.py --window --width 1024 --height 600
```

触控屏在Linux下通常映射为鼠标事件，无需额外适配。`ESC`从游戏、记录或演示返回主页；在主页按`ESC`退出。

## 自动测试

无图形界面时运行：

```bash
python3 main.py --soak-test --rounds 100 --log-dir logs/soak_v2_100
```

Windows命令：

```powershell
python main.py --soak-test --rounds 100 --log-dir logs\soak_v2_100
```

压测使用pygame的dummy视频驱动，不打开真实窗口。它会模拟六款游戏的正确和错误操作、超时提示、记忆序列、结果页、今日记录、近七日记录、六个独立模式演示和返回主页，并校验日志、存档和序列规则。

运行单元测试：

```bash
python3 -m unittest discover -s tests -v
```

也可直接使用独立压测入口：

```bash
python3 tests/soak_test.py --rounds 100
```

## 日志

默认保存在`logs/`：

```text
logs/session_20260627-100000-xxxxxxxx.jsonl
```

每行都是独立JSON，包含：

- `timestamp`
- `session_id`
- `event_name`
- `page`
- `game_id`
- `payload`

核心事件包括颜色、形状、记忆序列点击、请求提示、完成游戏、返回主页、星宝状态、反馈、开始游戏、下一轮和保存本次记录。V2不会生成`child_confirmed_choice`。

## 自动存档

默认存档位置：

```text
saves/latest_save.json
saves/autosave_backup.json
```

存档包含成长数据、累计统计、当日统计、近七日学习时长与次数、最近游戏和演示速度。程序启动时自动恢复；日期变化后当日统计重置，等级、能量、累计统计和历史学习记录继续保留。游戏结束、正常退出以及dirty状态持续12秒时自动保存。

成长等级最高为`LV.100`。星宝称号每2级提升一次，从`星尘新芽`逐步成长到`满级星穹王`；升级所需能量会随等级递增，越往后升级越难。满级后能量条保持满格，不再继续升级。

查看并验证JSON：

```powershell
Get-Content -Raw saves\latest_save.json | ConvertFrom-Json
```

Linux或板卡可使用：

```bash
python3 -m json.tool saves/latest_save.json
```

清空存档请在应用内进入`今日记录`页，点击右下角`清空存档`。系统会先弹出二次确认：

```text
确认清空本地存档？
该操作只会清空成长记录，不会删除日志。
```

确认后会归档旧的`latest_save.json`和`autosave_backup.json`，重新写入初始存档；等级、能量、星星、累计游戏、成功次数和尝试次数归零。`logs/`不会被删除，便于调试和验收。存档仅保存在本机，不包含姓名、人脸、语音或其他敏感个人信息。

## 字体和文字贴图策略

普通中文默认走`FontManager`，优先使用微软雅黑、等线、黑体、NotoSansCJK、思源黑体和文泉驿等中文字体。Ubuntu或SC171V3字体缺失时建议安装：

```bash
sudo apt install fonts-noto-cjk
```

`assets/xingbao_text/`中的文字PNG会保留在素材库，但默认不做大面积使用。当前只允许底部按钮、状态chip和小标签在透明、清晰、不重叠时局部使用；主标题、任务卡标题、颜色名称、形状名称和左侧面板字段继续使用FontManager。找不到或不适合深色UI的PNG必须fallback到FontManager。

## 复制到SC171V3

1. 将整个项目目录复制到板卡。
2. 在板卡项目目录安装`requirements.txt`。
3. 确认系统安装中文字体和SDL依赖。
4. 先运行`python3 main.py --window`检查环境。
5. 连接触控屏后运行`python3 main.py --fullscreen`。
6. 正式演示前运行`python3 main.py --soak-test --rounds 100`。

程序不依赖Windows路径、外部图片或网络服务。板卡需要提供Python3.8及以上版本和pygame2.5及以上版本。

## 代码结构

```text
main.py
requirements.txt
src/
  app.py
  demo.py
  effects.py
  states.py
  theme.py
  events.py
  logger.py
  layout.py
  ui_components.py
  xingbao.py
  records.py
  autosave.py
  system_status.py
  ui_registry.py
  layout_debug.py
  font_manager.py
  text_renderer.py
  demo_timing.py
  soak.py
  action_schema.py
  feedback_policy.py
  game_api.py
  games/
    base_game.py
    color_game.py
    shape_game.py
    memory_path_game.py
tests/
  soak_test.py
  test_app_smoke.py
  test_core.py
  test_autosave.py
  test_demo_timing.py
  test_soak.py
  test_v2_games.py
  test_v2_layout.py
logs/
```

## 后续接口

- 语音侧可以通过`src.game_api.handle_command(app, command)`查询或控制当前触控小游戏。游戏侧只接收已经解析好的意图，不接入ASR、LLM、TTS、摄像头或真实机械臂。
- 如果需要更贴近交接文档中的单参数函数形态，可以创建`GameCommandAdapter(app)`，再调用`adapter.handle_command(command)`。
- 命令格式：
```json
{
  "type": "game_command",
  "game_id": "color_game",
  "intent": "get_hint",
  "user_text": "给我一个提示",
  "context": {"source": "voice"}
}
```
- 返回格式：
```json
{
  "type": "game_response",
  "ok": true,
  "game_id": "color_game",
  "intent": "get_hint",
  "message": "提示：找到蓝色能量",
  "state": {},
  "feedback": {
    "screen_expression": "curious",
    "arm_action": "stay_still",
    "led_mode": "yellow_blink"
  }
}
```
- 当前支持的意图：`get_rule`、`get_goal`、`get_hint`、`get_score`、`get_progress`、`repeat_prompt`、`restart_round`、`next_round`、`pause_game`、`exit_game`。
- 当前支持的游戏ID：`color_game`、`shape_game`、`memory_game`、`counting_game`、`english_game`、`skill_game`。返回的`state`会按游戏类型补充目标、选项、翻译方向或记忆阶段等字段。
- 游戏事件可以通过`src.game_api.build_game_event(app,event,message)`或`adapter.build_event(event,message)`生成，结构为`type=game_event`、`game_id`、`event`、`message`、`state`、`feedback`。
- 反馈只输出高层白名单：表情`neutral/smile/thinking/curious/sad/surprised/sleepy`，动作`stay_still/wave_hand/nod/shake_head/point_left/point_right/small_dance`，灯效`off/blue_breath/warm_breath/yellow_blink/rainbow/red_flash`。同一份白名单也保存于`config/action_schema.json`。硬件侧如果动作风险未知，应优先把动作映射为`stay_still`。
- 机械臂可在独立适配层监听`xingbao_show_feedback`、`xingbao_start_next_round`、`child_finished_game`等事件，当前版本不执行任何真实控制。
- 视觉模块后续可把识别结果转换为游戏`handle_choice()`输入，当前版本不加载摄像头、不调用视觉模块，也不在界面显示相关入口。
- 本地语音可在`XingbaoApp.speak()`外接离线TTS或音频播放，同时保留`xingbao_speak`日志。
