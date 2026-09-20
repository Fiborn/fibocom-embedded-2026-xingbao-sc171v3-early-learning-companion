import pytest

from core.guided_expression_flow import (
    IDLE,
    WAIT_DESCRIPTION,
    WAIT_DRAWING_CONSENT,
    WAIT_HIGH_LEAVES_CONFIRMATION,
    WAIT_RECAST,
    DinosaurExpressionFlow,
)


def _start(flow: DinosaurExpressionFlow) -> None:
    opening = flow.handle("我叫小宇，我喜欢恐龙")
    assert opening is not None
    assert opening.text == "小宇你好，我记住你喜欢恐龙啦。你最喜欢哪一种呢？"
    assert flow.snapshot().stage == WAIT_DESCRIPTION


def _reach_recast(flow: DinosaurExpressionFlow) -> None:
    _start(flow)
    leaf_prompt = flow.handle("有一种龙特别大，可是我不知道该怎么说")
    assert leaf_prompt is not None
    assert leaf_prompt.scene == "dinosaur_short_leaf_prompt"
    assert leaf_prompt.text == "没关系，我们慢慢说。它能吃到高高的树叶吗？"
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION

    recast = flow.handle("对，它可以吃到高高的树叶")
    assert recast is not None
    assert recast.scene == "dinosaur_short_recast"
    assert "可能是腕龙" in recast.text
    assert flow.snapshot().stage == WAIT_RECAST


def test_finals_short_script_replaces_old_trex_route() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle("我喜欢一种特别特别大的龙，但是我说不清楚")

    assert reply is not None
    assert reply.scene == "dinosaur_short_leaf_prompt"
    assert "霸王龙" not in reply.text
    assert "高高的树叶" in reply.text
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


@pytest.mark.parametrize(
    "utterance",
    [
        "有一种恐龙特别大，可我不知道怎么说",
        "那个龙身体很大，我讲不清楚",
        "我想的是一个很庞大的家伙，但是不知道怎么形容",
        "它的个头很大，我不知道它叫什么",
    ],
)
def test_vague_big_meaning_advances_without_verbatim_match(utterance: str) -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle(utterance)

    assert reply is not None
    assert reply.scene == "dinosaur_short_leaf_prompt"
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


@pytest.mark.parametrize(
    "utterance",
    [
        "我喜欢腕龙，因为它身体很大，脖子很长",
        "我最喜欢万龙，它个头大，还有长脖子",
        "我喜欢万隆，因为它很庞大，而且颈部伸得很远",
        "腕龙是我最爱的恐龙，身体巨大，脖子长长的，还能吃树叶",
    ],
)
def test_complete_meaning_accepts_paraphrases_and_asr_aliases(utterance: str) -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    completed = flow.handle(utterance)

    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"
    assert completed.text == "你自己说得真完整！我也记住你喜欢腕龙啦。来，击掌庆祝一下吧！"
    assert completed.post_tts_arm_action == "high_five"
    assert completed.end_session is True
    assert completed.memory_update["interests"] == ["恐龙", "腕龙"]
    assert flow.snapshot().stage == WAIT_DRAWING_CONSENT


def test_high_leaves_is_optional_in_childs_final_sentence() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    completed = flow.handle("我喜欢腕龙，因为它身体大，脖子长")

    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"


def test_any_complete_final_asr_turn_completes_recast_step() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    completed = flow.handle("我喜欢腕龙")

    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"
    assert completed.post_tts_arm_action == "high_five"
    assert flow.snapshot().stage == WAIT_DRAWING_CONSENT


def test_incomplete_recast_still_advances_after_child_finishes_speaking() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    completed = flow.handle("我喜欢万龙，因为它身体很大")

    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"


def test_recast_wording_is_not_a_live_demo_gate() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    completed = flow.handle("它身体很大，脖子很长")

    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"


def test_recast_advances_once_per_completed_asr_turn() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    completed = flow.handle("我喜欢腕龙，因为它身体很大")

    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"
    assert flow.snapshot().stage == WAIT_DRAWING_CONSENT


def test_first_completed_turn_advances_exactly_one_script_step() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle("我喜欢腕龙，因为它身体特别大，脖子特别长")

    assert reply is not None
    assert reply.scene != "dinosaur_expression_completed"
    assert reply.post_tts_arm_action == ""
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


def test_any_opening_answer_advances_to_leaf_question_only() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle("我喜欢腕龙")

    assert reply is not None and reply.scene == "dinosaur_short_leaf_prompt"
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


def test_negative_wording_still_advances_after_a_complete_turn() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle("它不是特别大的")

    assert reply is not None
    assert reply.scene == "dinosaur_short_leaf_prompt"
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


def test_leaf_answer_wording_does_not_block_recast_step() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)
    flow.handle("有一种恐龙身体特别大，可是我说不清")

    reply = flow.handle("不对，它不能吃到高处的树叶")

    assert reply is not None
    assert reply.scene == "dinosaur_short_recast"
    assert "霸王龙" not in reply.text
    assert flow.snapshot().stage == WAIT_RECAST


def test_spoken_refusal_does_not_interrupt_the_fixed_demo_route() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle("算了，我不想说了")

    assert reply is not None
    assert reply.text == "没关系，我们慢慢说。它能吃到高高的树叶吗？"
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


def test_any_completed_turn_advances_without_suspending_the_demo_route() -> None:
    flow = DinosaurExpressionFlow()
    _start(flow)

    reply = flow.handle("我想先玩游戏")
    assert reply is not None
    assert reply.scene == "dinosaur_short_leaf_prompt"
    assert flow.snapshot().suspended is False
    assert flow.snapshot().stage == WAIT_HIGH_LEAVES_CONFIRMATION


def test_completed_interest_can_be_recalled_from_safe_memory() -> None:
    flow = DinosaurExpressionFlow()
    reply = flow.handle(
        "你还记得我喜欢什么恐龙吗",
        memory={"interests": ["恐龙", "腕龙"]},
    )

    assert reply is not None
    assert reply.text == "记得呀，你喜欢身体很大、脖子很长的腕龙。"
    assert reply.end_session is True


def test_trex_recall_also_explicitly_ends_the_reviewed_script() -> None:
    flow = DinosaurExpressionFlow()

    reply = flow.handle(
        "你还记得我喜欢什么恐龙吗",
        memory={"interests": ["恐龙", "霸王龙"]},
    )

    assert reply is not None
    assert reply.text == "记得呀，你喜欢又大又有力量的霸王龙。"
    assert reply.scene == "dinosaur_interest_recalled"
    assert reply.end_session is True


def test_drawing_consent_hands_off_to_real_touch_and_then_resets() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)
    flow.handle("我喜欢腕龙，因为它身体大，脖子长")

    accepted = flow.handle("好呀")

    assert accepted is not None
    assert accepted.text == "那我们去百宝箱画一画吧。"
    assert accepted.scene == "dinosaur_drawing_accepted"
    assert accepted.end_session is True
    assert flow.snapshot().stage == IDLE


def test_unmatched_normal_conversation_is_not_intercepted() -> None:
    flow = DinosaurExpressionFlow()
    assert flow.handle("今天天气怎么样") is None
    assert flow.snapshot().stage == IDLE


def test_reviewed_opening_still_requires_name_and_dinosaur_interest() -> None:
    flow = DinosaurExpressionFlow()
    assert flow.handle("我喜欢恐龙") is None
    assert flow.handle("我叫小宇，我喜欢画画") is None
    assert flow.handle("我叫小宇，我不喜欢恐龙") is None

    opening = flow.handle("你可以叫我小雨，我对恐龙最感兴趣")
    assert opening is not None
    assert opening.text.startswith("小雨你好")
    assert flow.snapshot().stage == WAIT_DESCRIPTION


def test_recovery_input_uses_new_short_script_semantics() -> None:
    flow = DinosaurExpressionFlow()
    _reach_recast(flow)

    recovery_input = flow.recovery_input_for_current_step()
    assert recovery_input == "我喜欢腕龙，因为它身体大，脖子长"

    completed = flow.handle(recovery_input)
    assert completed is not None
    assert completed.scene == "dinosaur_expression_completed"
    assert flow.recovery_input_for_current_step() == "好呀"
