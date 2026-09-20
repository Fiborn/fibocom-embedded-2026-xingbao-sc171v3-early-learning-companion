from tools.verify_memory_book_flow import run_verification


def test_memory_book_shared_data_flow_runs_end_to_end() -> None:
    result = run_verification()

    assert result["ok"] is True
    assert result["history_count"] == 80
    assert result["deleted_summary_absent_from_prompt"] is True
