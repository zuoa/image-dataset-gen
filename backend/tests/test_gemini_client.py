from app.clients.gemini_client import (
    _extract_prediction,
    normalize_aspect_ratio,
    pixel_size_for_aspect_ratio,
)


def test_aspect_ratio_helpers_return_expected_values():
    assert normalize_aspect_ratio("1:1") == "1:1"
    assert normalize_aspect_ratio("3:4") == "3:4"
    assert pixel_size_for_aspect_ratio("16:9") == "1536x864"


def test_extract_prediction_supports_predictions_payload():
    payload = {
        "predictions": [
            {
                "bytesBase64Encoded": "ZmFrZQ==",
                "mimeType": "image/png",
            }
        ]
    }
    prediction = _extract_prediction(payload)
    assert prediction is not None
    assert prediction["mimeType"] == "image/png"


def test_extract_prediction_supports_generated_images_payload():
    payload = {
        "generatedImages": [
            {
                "image": {
                    "imageBytes": "ZmFrZQ==",
                    "mimeType": "image/png",
                }
            }
        ]
    }
    prediction = _extract_prediction(payload)
    assert prediction is not None
    assert prediction["bytesBase64Encoded"] == "ZmFrZQ=="
