from experiment.sentin_edge_affective_validation import (
    FER2013_LABELS,
    XINGBAO_EMOTION_CODES,
    json_safe,
    should_disable_default_delegates,
    parse_label_order,
    select_classification_output,
    validate_grayscale_face_input,
)


def test_parse_label_order_maps_the_complete_fer2013_contract_to_xingbao_codes():
    """A changed/missing model-output label must never silently change emitted events."""
    labels = parse_label_order("angry,disgust,fear,happy,sad,surprise,neutral")

    assert labels == FER2013_LABELS
    assert [XINGBAO_EMOTION_CODES[label] for label in labels] == [3, 6, 5, 1, 2, 4, 8]
    assert "contempt" not in labels


def test_parse_label_order_rejects_incomplete_or_duplicate_output_labels():
    """A seven-output tensor needs each FER2013 class exactly once before validation can run."""
    for value in (
        "angry,disgust,fear,happy,sad,surprise",
        "angry,disgust,fear,happy,sad,surprise,angry",
    ):
        try:
            parse_label_order(value)
        except ValueError:
            continue
        raise AssertionError(f"expected invalid label order to be rejected: {value}")


def test_select_classification_output_uses_the_seven_class_tensor_not_embedding():
    """Swapping TFLite outputs must not make the 256-feature embedding drive emotions."""
    outputs = [
        {"index": 27, "shape": [1, 256], "name": "embedding"},
        {"index": 29, "shape": [1, 7], "name": "classification"},
    ]

    assert select_classification_output(outputs)["index"] == 29


def test_select_classification_output_accepts_an_explicit_eight_class_ferplus_head():
    """An 8-class FER+ head must not be rejected as a seven-class FER2013 model."""
    outputs = [
        {"index": 47, "shape": [1, 256], "name": "embedding"},
        {"index": 49, "shape": [1, 8], "name": "classification"},
    ]

    assert select_classification_output(outputs, class_count=8)["index"] == 49


def test_parse_label_order_accepts_the_native_eight_class_ferplus_contract():
    """FER+ has a distinct eight-class contract, including contempt."""
    labels = parse_label_order("neutral,happiness,surprise,sadness,anger,disgust,fear,contempt")

    assert labels[-1] == "contempt"
    assert len(labels) == 8


def test_validate_grayscale_face_input_accepts_the_legacy_64_pixel_fer_model():
    """A valid fixed grayscale FER model must not be rejected solely for using 64px input."""
    detail = {"shape": [1, 64, 64, 1], "dtype": "float32"}

    validate_grayscale_face_input(detail)


def test_json_safe_serializes_tflite_dtype_types_for_the_isolated_worker_report():
    """A successful inference must not be misreported as a failure during JSON serialization."""
    assert json_safe({"dtype": float}) == {"dtype": "float"}


def test_htp_validation_disables_xnnpack_so_delegate_partitions_are_attributable_to_qnn():
    """Default TFLite delegates would otherwise make CPU XNNPACK look like HTP coverage."""
    assert should_disable_default_delegates("htp") is True
    assert should_disable_default_delegates("cpu") is False
