"""Regression checks for the board dialogue-VAD calibration launch contract."""

from pathlib import Path
import unittest


class BoardVADRuntimeConfigTests(unittest.TestCase):
    def test_launcher_exposes_validated_dialogue_vad_threshold(self) -> None:
        script = (Path(__file__).parents[1] / "deploy" / "board_start_demo.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("XINGBAO_DIALOGUE_VAD_MANUAL_THRESHOLD", script)
        self.assertIn("--vad-manual-threshold $DIALOGUE_VAD_MANUAL_THRESHOLD", script)
        self.assertIn("must be in (0, 20000]", script)

    def test_launcher_exposes_validated_dialogue_vad_end_silence(self) -> None:
        script = (Path(__file__).parents[1] / "deploy" / "board_start_demo.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("XINGBAO_DIALOGUE_VAD_END_SILENCE_MS", script)
        self.assertIn("--vad-end-silence-ms $DIALOGUE_VAD_END_SILENCE_MS", script)
        self.assertIn("must be in [300, 1500]", script)


if __name__ == "__main__":
    unittest.main()
