import pytest
from marshmallow import ValidationError

from app.schemas import TaskActionSchema


def test_task_action_schema_accepts_policy_v2_augmentation_families():
    payload = TaskActionSchema().load(
        {
            "augmentation_policy_version": 2,
            "augmentation_methods": [
                "flip",
                "affine",
                "safe_crop",
                "target_occlusion",
                "lighting",
                "degradation",
            ],
            "augmentation_settings": {
                "flip": {"mode": "horizontal", "probability": 0.5},
                "affine": {
                    "min_scale": 0.85,
                    "max_scale": 1.15,
                    "max_translate": 0.04,
                    "max_rotate": 8,
                    "max_shear": 3,
                    "probability": 0.55,
                },
                "safe_crop": {"erosion_rate": 0, "probability": 0.3},
                "target_occlusion": {
                    "min_holes": 1,
                    "max_holes": 2,
                    "min_ratio": 0.18,
                    "max_ratio": 0.38,
                    "probability": 0.3,
                },
                "lighting": {"strength": 0.18, "probability": 0.55},
                "degradation": {"strength": 0.5, "probability": 0.35},
            },
        }
    )

    assert payload["augmentation_policy_version"] == 2
    assert payload["augmentation_methods"][-1] == "degradation"


def test_task_action_schema_rejects_invalid_policy_probability():
    with pytest.raises(ValidationError):
        TaskActionSchema().load(
            {
                "augmentation_policy_version": 2,
                "augmentation_methods": ["lighting"],
                "augmentation_settings": {
                    "lighting": {"strength": 0.18, "probability": 1.1}
                },
            }
        )
