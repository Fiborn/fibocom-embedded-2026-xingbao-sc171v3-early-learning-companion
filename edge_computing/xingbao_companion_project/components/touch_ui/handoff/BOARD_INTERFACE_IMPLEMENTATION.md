#星宝UI/游戏板卡接口实现

##中枢调用

导入`src.board_adapter`：

```python
from src.board_adapter import open_game, set_xingbao_expression

open_game()  #打开游戏中心
open_game("shape_game", source="voice", context={"difficulty": 2})
set_xingbao_expression("smile", "真棒！", source="voice")
```

这些函数可从工作线程调用，但实际Pygame操作会排入队列，由UI主线程每帧执行。返回值含`ok`、`action`、`error`以及`executed_on_ui_thread`。

游戏列表：`color_game`、`shape_game`、`memory_game`、`counting_game`、`english_game`、`skill_game`。难度只允许`1/2/3`。

表情列表：`neutral`、`smile`、`thinking`、`curious`、`sad`、`surprised`、`sleepy`。未知值自动降级为`neutral/idle`。

##独立进程通信

正常运行`python desktop.py`时会自动在后台启动服务。也可单独运行协议调试服务：

```bash
python examples/central_ui_dispatcher_example.py --host 127.0.0.1 --port 8765
```

协议为UTF-8、每行一个JSON。中枢发送`assistant_output`，服务返回`command_result`。正式联调请启动`desktop.py`；单独运行示例脚本时没有绑定UI，只适合检查协议错误处理。需要关闭端口时使用`python desktop.py --no-central-bridge`。

##游戏主动请求TTS

```python
def send_to_central(payload):
    #payload={"type":"speech_request","text":"...","page":"...","source":"xingbao_touch_game"}
    central_connection.send(payload)

app = XingbaoApp(on_speech_request=send_to_central)
```

所有`XingbaoApp.speak(text,page)`调用都会触发此回调，屏幕仍同时显示文字。中枢收到`speech_request`后负责TTS播放。

##硬件边界

UI项目只实现`src.board_adapter.apply_hardware_feedback()`白名单校验，不控制舵机、PWM、GPIO和原始串口。硬件组应在此函数返回之后执行驱动。

动作白名单：`stay_still`、`wave_hand`、`nod`、`shake_head`、`point_left`、`point_right`、`small_dance`。

灯效白名单：`off`、`blue_breath`、`warm_breath`、`yellow_blink`、`rainbow`、`red_flash`。

返回格式：`{"ok":true,"implemented_by":"board_hardware_team","arm_action":"wave_hand","led_mode":"blue_breath","error":null}`。

##视觉输入

视觉进程调用`VisionStateAdapter("saves/vision_status.json").write(flag1,flag2)`。`[1,0]`表示距离过近；`[0,1]`表示需要喝水。

##验收

```bash
python tools/acceptance_interfaces.py
python -m pytest tests/test_board_adapter.py tests/test_game_api.py -q
```
