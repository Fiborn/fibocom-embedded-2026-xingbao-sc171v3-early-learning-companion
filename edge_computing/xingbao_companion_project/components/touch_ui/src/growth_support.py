"""Reviewed first-mistake support for normal touch-game sessions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SupportSequence:
    kind: str
    support_id: str
    question_id: str
    target_id: str
    target_label: str
    invitation_text: str = ""
    retry_text: str = ""
    success_text: str = ""
    # The six-point visual high-five has a 12 second hardware watchdog.  Keep
    # the game in its invitation state until the fixed move has completed.
    high_five_hold_seconds: float = 24.5


class FirstMistakeSupport:
    """Offer one hint and one high-five after the first wrong shape answer."""

    def __init__(self):
        self.reset()

    def reset(self, game_id=""):
        self.game_id = str(game_id or "")
        self.used = False
        self.awaiting_retry = False
        self.retry_succeeded = False
        self.support_id = ""
        self.question_id = ""
        self.target_id = ""
        self.target_label = ""
        self.phase = ""
        self.action = ""

    def observe_answer(
        self,
        *,
        game_id,
        correct,
        question_id,
        target_id,
        target_label,
    ):
        game_id = str(game_id or "")
        question_id = str(question_id or "")
        target_id = str(target_id or "")
        target_label = str(target_label or target_id)

        if (
            self.awaiting_retry
            and bool(correct)
            and question_id
            and question_id == self.question_id
        ):
            self.awaiting_retry = False
            self.retry_succeeded = True
            self.phase = "retry_success"
            self.action = ""
            return SupportSequence(
                kind="retry_success",
                support_id=self.support_id,
                question_id=question_id,
                target_id=target_id,
                target_label=target_label,
                success_text="答对啦！你听完提示又试了一次，这次成功啦！",
            )

        if bool(correct) or self.used or game_id != "shape":
            return None

        self.game_id = game_id
        self.used = True
        self.awaiting_retry = True
        self.retry_succeeded = False
        self.support_id = str(uuid.uuid4())
        self.question_id = question_id
        self.target_id = target_id
        self.target_label = target_label
        self.phase = "invitation"
        self.action = ""
        hint = _shape_hint(target_id, target_label)
        return SupportSequence(
            kind="first_mistake",
            support_id=self.support_id,
            question_id=question_id,
            target_id=target_id,
            target_label=target_label,
            invitation_text=(
                "没关系，第一次没有答对也很正常。"
                f"我给你一个小提示：{hint}"
                f"这一题还是请找到{target_label}在哪里。"
                "来，和我击个掌，我们一起再试一次吧！"
            ),
            retry_text=f"好，我们现在是一起闯关的搭档啦！再看看，{hint}",
        )

    def start_high_five(self):
        if not self.awaiting_retry or not self.support_id:
            return False
        self.phase = "high_five"
        self.action = "high_five"
        return True

    def start_retry_prompt(self):
        if not self.awaiting_retry:
            return False
        self.phase = "retry_prompt"
        self.action = ""
        return True

    def finish_retry_prompt(self):
        if self.phase != "retry_prompt":
            return False
        self.phase = "awaiting_retry"
        self.action = ""
        return True

    def public_state(self):
        if not self.used:
            return {}
        return {
            "support_id": self.support_id,
            "phase": self.phase,
            "action": self.action,
            "question_id": self.question_id,
            "target_id": self.target_id,
            "target_label": self.target_label,
            "awaiting_retry": self.awaiting_retry,
            "retry_succeeded": self.retry_succeeded,
        }


def _shape_hint(target_id, target_label):
    hints = {
        "triangle": "三角形有三个尖尖的角。",
        "circle": "圆形像一个圆圆的轮子，没有尖角。",
        "square": "正方形有四条一样长的边和四个角。",
        "rectangle": "长方形有四个角，两条长边和两条短边。",
        "star": "星形周围有一个个尖尖的角。",
        "heart": "爱心上面有两个圆圆的弯，下面是尖尖的。",
        "ellipse": "椭圆形像一个被轻轻拉长的圆。",
    }
    return hints.get(str(target_id or ""), "仔细看看它最特别的形状。")
