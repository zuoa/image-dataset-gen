from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.dataset_export_service import _build_splits, dataset_export_download_name


def test_dataset_export_download_name_is_descriptive_and_sortable():
    export_job = SimpleNamespace(
        version=3,
        export_format="yolo",
        created_at=datetime(2026, 7, 21, 6, 30, tzinfo=UTC),
        summary_json={"imageCount": 128},
    )

    assert dataset_export_download_name("Road Scene / Demo", export_job) == (
        "road-scene-demo-yolo-20260721T0630Z-n128-v003.zip"
    )


def test_dataset_export_download_name_uses_fallback_count_for_legacy_export():
    export_job = SimpleNamespace(
        version=1,
        export_format="coco",
        created_at=datetime(2026, 7, 21, 14, 30),
        summary_json={},
    )

    assert dataset_export_download_name(
        "城市道路数据集",
        export_job,
        fallback_image_count=24,
    ) == "城市道路数据集-coco-20260721T1430Z-n24-v001.zip"


def test_dataset_export_keeps_augmented_images_with_their_source_split():
    originals = [
        SimpleNamespace(
            id=f"source-{index}",
            ordinal=index,
            augmentation_source_image_id=None,
            diversity_vars={},
        )
        for index in range(1, 5)
    ]
    augmented = [
        SimpleNamespace(
            id=f"augmented-{index}",
            ordinal=index + 4,
            augmentation_source_image_id=f"source-{index}",
            diversity_vars={},
        )
        for index in range(1, 5)
    ]

    splits = _build_splits([*originals, *augmented])
    split_by_id = {
        image.id: split
        for split, images in splits.items()
        for image in images
    }

    for index in range(1, 5):
        assert split_by_id[f"source-{index}"] == split_by_id[f"augmented-{index}"]
    assert {split: len(images) for split, images in splits.items()} == {
        "train": 4,
        "val": 2,
        "test": 2,
    }
