from core.listening_loop import ListeningLoop


class FakeWakeWordDetector:
    def __init__(self) -> None:
        self.calls = 0

    def wait_for_wake_word(self) -> str:
        self.calls += 1
        return "星宝星宝"


def test_listening_loop_runs_one_turn_after_each_wake_word() -> None:
    detector = FakeWakeWordDetector()
    events: list[str] = []
    sleeps: list[float] = []

    completed = ListeningLoop(
        detector=detector,
        play_wake_ack=lambda: events.append("ack"),
        on_wake=lambda: events.append("turn") or {"ok": True},
        on_turn_complete=lambda _result: events.append("complete"),
        cooldown_seconds=0.5,
        sleep=sleeps.append,
    ).run(max_turns=2)

    assert completed == 2
    assert detector.calls == 2
    assert events == ["ack", "turn", "complete", "ack", "turn", "complete"]
    assert sleeps == [0.5, 0.5]
