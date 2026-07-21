from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.dataset_export_service import dataset_export_download_name


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
