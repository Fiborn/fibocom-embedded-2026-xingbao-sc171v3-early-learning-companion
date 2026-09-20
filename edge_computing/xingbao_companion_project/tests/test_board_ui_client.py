from core.board_ui_client import (
    BoardUIClient,
    arm_action_from_plan,
    assistant_arm_action_output,
    assistant_game_command_output,
    assistant_output_from_plan,
    extract_game_response,
    plan_has_board_action,
)
from core.coordinator import XingbaoCoordinator


def test_direct_camera_snapshot_command_has_a_dedicated_payload(monkeypatch) -> None:
    client = BoardUIClient()
    messages: list[dict] = []
    monkeypatch.setattr(
        BoardUIClient,
        "send_assistant_output",
        lambda _self, message: messages.append(message) or {"ok": True},
    )

    client.send_ui_command(
        {"name": "camera_snapshot", "action": "show", "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240},
    )

    assert messages[-1]["payload"]["camera_snapshot"] == {
        "action": "show", "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
    }
    assert messages[-1]["payload"]["ui_command"] == {
        "name": "camera_snapshot", "action": "show",
        "data_uri": "data:image/jpeg;base64,AA==", "width": 320, "height": 240,
    }


def test_board_ui_message_opens_game_center_for_general_game_request() -> None:
    plan = XingbaoCoordinator().plan_text("星宝我要玩游戏啦")

    message = assistant_output_from_plan(plan, request_id="test-request")

    assert message["type"] == "assistant_output"
    assert message["request_id"] == "test-request"
    payload = message["payload"]
    assert payload["screen_expression"]["name"] == "smile"
    assert payload["arm_action"] == "stay_still"
    assert payload["led"]["mode"] == "warm_breath"
    assert payload["speech"] == {"text": "", "request_tts": False, "interrupt": False}
    assert payload["ui_command"] == {"name": "open_game_center", "params": {}}


def test_board_ui_message_can_start_specific_touch_game() -> None:
    plan = XingbaoCoordinator().plan_text("星宝我要玩找颜色")

    message = assistant_output_from_plan(plan)

    assert message["payload"]["ui_command"] == {
        "name": "start_game",
        "params": {"game_id": "color_game", "difficulty": 1},
    }


def test_board_ui_message_can_open_migrated_visual_tools_home() -> None:
    plan = XingbaoCoordinator().plan_text("星宝打开白宝箱")

    message = assistant_output_from_plan(plan, request_id="visual-tools-home")

    assert message["payload"]["ui_command"]["name"] == "open_visual_tools"
    assert message["payload"]["ui_command"]["params"]["app_id"] == "kids_visual_tools"
    assert message["payload"]["ui_command"]["params"]["command"] == [
        "python3",
        "web/kids_visual_tools/kids_visual_tools.py",
    ]


def test_board_ui_message_can_launch_specific_migrated_visual_tool() -> None:
    plan = XingbaoCoordinator().plan_text("星宝打开画板")

    message = assistant_output_from_plan(plan, request_id="visual-tools-draw")

    assert message["payload"]["ui_command"]["name"] == "launch_visual_tool"
    assert message["payload"]["ui_command"]["params"]["tool_slug"] == "draw"
    assert message["payload"]["ui_command"]["params"]["tool_title"] == "儿童画板"
    assert message["payload"]["ui_command"]["params"]["command"] == [
        "python3",
        "web/kids_visual_tools/kids_visual_tools.py",
        "--tool",
        "draw",
    ]


def test_board_ui_message_can_return_to_desktop() -> None:
    plan = XingbaoCoordinator().plan_text("星宝我不玩了")

    message = assistant_output_from_plan(plan)

    assert message["payload"]["ui_command"] == {
        "name": "return_to_desktop",
        "params": {},
    }


def test_scene_command_rejects_invalid_ids_before_opening_ui_socket() -> None:
    import pytest

    with pytest.raises(ValueError, match="scene_id"):
        BoardUIClient().send_xingbao_scene(28, source="llm")


def test_plain_chat_does_not_enter_fixed_action_line() -> None:
    plan = XingbaoCoordinator().plan_text("星宝你好呀")

    assert plan_has_board_action(plan) is False


def test_greeting_does_not_invent_a_physical_action() -> None:
    plan = XingbaoCoordinator().plan_text("星宝，你好。")

    assert plan.intent.intent == "greeting"
    assert arm_action_from_plan(plan) == ""
    assert plan_has_board_action(plan) is False


def test_standalone_arm_action_output_keeps_whitelisted_action() -> None:
    message = assistant_arm_action_output("nod", request_id="arm-test")

    assert message == {"arm_action": "nod"}


def test_standalone_high_five_keeps_distinct_reviewed_action() -> None:
    message = assistant_arm_action_output("high_five", request_id="high-five-test")

    assert message == {"arm_action": "high_five"}


def test_standalone_arm_action_rejects_group_and_raw_hardware_values() -> None:
    import pytest

    for action in ("group_1", "group_2", "servo_angle_120"):
        with pytest.raises(ValueError, match="unsupported arm action"):
            assistant_arm_action_output(action)


def test_send_arm_action_uses_raw_utf8_ndjson() -> None:
    import json
    import socketserver
    import threading

    received: list[bytes] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            received.append(self.rfile.readline())
            self.wfile.write(
                (
                    json.dumps(
                        {
                            "type": "command_result",
                            "ok": True,
                            "hardware_feedback": {
                                "implemented": True,
                                "arm_action": "shake_head",
                            },
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        host, port = server.server_address
        result = BoardUIClient(arm_host=host, arm_port=port).send_arm_action("shake_head")
        thread.join(timeout=2.0)

    assert result["ok"] is True
    assert received == [
        (json.dumps({"arm_action": "shake_head"}, ensure_ascii=False) + "\n").encode("utf-8")
    ]


def test_game_result_events_select_arm_ipc_actions() -> None:
    coordinator = XingbaoCoordinator()

    correct = coordinator.plan_event({"type": "game_event", "event": "answer_correct"})
    wrong = coordinator.plan_event({"type": "game_event", "event": "answer_wrong"})

    assert arm_action_from_plan(correct) == ""
    assert arm_action_from_plan(wrong) == ""


def test_send_plan_does_not_invent_an_arm_action_for_generic_game_feedback() -> None:
    import json
    import socketserver
    import threading

    ui_received: list[dict] = []
    arm_received: list[dict] = []

    class UIHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            message = json.loads(self.rfile.readline().decode("utf-8"))
            ui_received.append(message)
            self.wfile.write(b'{"type":"command_result","ok":true}\n')

    class ArmHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            arm_received.append(json.loads(self.rfile.readline().decode("utf-8")))

    with socketserver.TCPServer(("127.0.0.1", 0), UIHandler) as ui_server, socketserver.TCPServer(
        ("127.0.0.1", 0), ArmHandler
    ) as arm_server:
        ui_thread = threading.Thread(target=ui_server.handle_request)
        arm_thread = threading.Thread(target=arm_server.handle_request)
        arm_server.timeout = 0.5
        ui_thread.start()
        arm_thread.start()
        ui_host, ui_port = ui_server.server_address
        arm_host, arm_port = arm_server.server_address
        plan = XingbaoCoordinator().plan_event(
            {"type": "game_event", "event": "answer_correct"}
        )
        result = BoardUIClient(
            host=ui_host,
            port=ui_port,
            arm_host=arm_host,
            arm_port=arm_port,
        ).send_plan(plan)
        ui_thread.join(timeout=2.0)
        arm_thread.join(timeout=2.0)

    assert result["ok"] is True
    assert result["request"]["payload"]["arm_action"] == "stay_still"
    assert ui_received[0]["type"] == "assistant_output"
    assert arm_received == []


def test_game_command_output_uses_current_game_by_default() -> None:
    message = assistant_game_command_output(
        {"intent": "get_stars", "user_text": "目前几颗星"},
        request_id="game-status",
    )

    assert message["request_id"] == "game-status"
    assert message["payload"]["game_command"] == {
        "type": "game_command",
        "game_id": "current_game",
        "intent": "get_stars",
        "user_text": "目前几颗星",
    }


def test_extract_game_response_from_command_result() -> None:
    response = extract_game_response(
        {
            "type": "command_result",
            "ok": True,
            "results": [
                {"ok": True, "action": "set_expression"},
                {"type": "game_response", "ok": True, "message": "当前3颗星"},
            ],
        }
    )

    assert response == {"type": "game_response", "ok": True, "message": "当前3颗星"}


def test_app_trace_records_board_ui_client_result() -> None:
    from app import XingbaoApp

    class FakeBoardClient:
        def send_plan(self, plan):
            request = assistant_output_from_plan(plan, request_id="fake")
            return {
                "ok": True,
                "request": request,
                "response": {"type": "command_result", "ok": True},
            }

    result = XingbaoApp().run_coordinated_text(
        "星宝我要玩游戏啦",
        board_ui_client=FakeBoardClient(),
    )

    assert result["board_ui"]["ok"] is True
    assert result["trace"][-1]["type"] == "board_ui.assistant_output"
    assert result["trace"][-1]["status"] == "sent"
