from app.service import annotate_payload


def test_annotate_payload_returns_detection_list():
    response = annotate_payload(
        {
            "confidenceThreshold": 0.6,
            "images": [
                {
                    "imageId": "img-1",
                    "ordinal": 1,
                    "seed": 123456,
                    "categoryHint": "forklift",
                },
                {
                    "imageId": "img-2",
                    "ordinal": 7,
                    "seed": 999999,
                    "categoryHint": "forklift",
                },
            ],
        }
    )

    assert len(response["results"]) == 2
    assert response["results"][0]["status"] in {"annotated", "empty"}
    assert response["results"][1]["status"] == "empty"
