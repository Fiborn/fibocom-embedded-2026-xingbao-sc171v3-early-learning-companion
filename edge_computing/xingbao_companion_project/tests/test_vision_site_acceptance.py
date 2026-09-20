from tools.vision_site_acceptance import _parse_frame_payloads


def test_site_acceptance_parser_ignores_logs_and_keeps_frame_json() -> None:
    output = "\n".join(
        [
            "model warmup",
            '{"frame":0,"faces":[],"return_code":0,'
            '"drink_return_code":0,"emotion_return_code":0}',
            '{"type":"vision_state"}',
        ]
    )

    frames = _parse_frame_payloads(output)

    assert len(frames) == 1
    assert frames[0]["frame"] == 0
