import unittest

from core.voice_events import VoiceEvent, VoiceInteractionPipeline


class VoiceEventTests(unittest.TestCase):
    def test_runtime_voice_events_are_supported(self) -> None:
        pipeline = VoiceInteractionPipeline()
        for event_type in (
            "wake_ui_session_end_suppressed",
            "arm_action_skipped",
            "finals_post_high_five_showcase_queued",
            "xingbao_scene",
            "xingbao_scene_failed",
            "llm_conversation_end_requested",
        ):
            with self.subTest(event_type=event_type):
                event = pipeline.emit(event_type, reason="guided_expression")
                self.assertEqual(event.type, event_type)


if __name__ == "__main__":
    unittest.main()
