import pytest

from app.api.datasets import _normalize_segment_prediction
from app.clients.segmenter_client import SegmenterClientError


def _prediction(mask_score: float) -> dict:
    return {
        "bbox": [0.5, 0.5, 0.25, 0.5],
        "maskDataUrl": "data:image/png;base64,eA==",
        "maskScore": mask_score,
    }


@pytest.mark.parametrize("mask_score", [float("nan"), float("inf"), float("-inf")])
def test_normalize_segment_prediction_rejects_non_finite_mask_score(mask_score: float):
    with pytest.raises(SegmenterClientError, match="invalid prediction"):
        _normalize_segment_prediction(_prediction(mask_score))
