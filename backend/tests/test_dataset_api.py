from io import BytesIO
from pathlib import Path
import zipfile
from unittest.mock import patch
from types import SimpleNamespace

from billiard.exceptions import SoftTimeLimitExceeded
from PIL import Image
import pytest
from sqlalchemy import event

from app import _backfill_detection_categories, create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Dataset, DatasetImage, DatasetTask, TaskItem
from app.services.annotation_storage import load_annotation_result, save_annotation_result
from app.services.image_storage import existing_generated_image, save_generated_image


def _png_bytes(color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _transparent_png_bytes() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGBA", (4, 4), color=(255, 0, 0, 0))
    image.putpixel((1, 1), (0, 255, 0, 96))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _avi_video_bytes(tmp_path: Path, frame_count: int = 6, size: tuple[int, int] = (8, 8)) -> bytes:
    import cv2
    import numpy as np

    video_path = tmp_path / "sample.avi"
    width, height = size
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (width, height))
    assert writer.isOpened()
    for index in range(frame_count):
        frame = np.full((height, width, 3), (index * 30, 120, 220 - index * 20), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return video_path.read_bytes()


def _auth_headers(client, username: str = "dataset-user") -> dict[str, str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "Dataset123!"},
    )
    token = register.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _create_dataset(client, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "name": "street pedestrian dataset",
            "categories": ["pedestrian", "umbrella"],
            "description": "dataset-level workflow",
        },
    )
    assert response.status_code == 201
    return response.get_json()["dataset"]["id"]


def test_create_dataset_rejects_duplicate_normalized_categories(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-duplicate-categories")

    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={"name": "duplicate category dataset", "categories": ["cat", " cat "]},
    )

    assert response.status_code == 422
    assert response.get_json()["errors"]["categories"] == ["category names must be unique"]


def _create_generation_task(client, dataset_id: str, headers: dict[str, str]) -> str:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/generation",
        headers=headers,
        json={
            "subject": "rainy crosswalk pedestrians",
            "categories": ["pedestrian", "umbrella"],
            "image_count": 5,
            "distance": "mid",
            "angle": "front",
            "lighting": ["night"],
            "background": ["city"],
            "aspect_ratio": "1:1",
            "format": "jpg",
            "style": "realistic",
            "api_provider": "gemini",
            "api_key": "demo-api-key",
            "concurrency": 2,
            "batch_size": 4,
            "extra_desc": "",
        },
    )
    assert response.status_code == 201
    return response.get_json()["task"]["id"]


def test_dataset_image_cursor_pages_without_duplicates(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-cursor")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        for ordinal in range(1, 6):
            db.session.add(
                DatasetImage(
                    dataset_id=dataset_id,
                    source_type="import",
                    source_ordinal=ordinal,
                    ordinal=ordinal,
                    status="uploaded",
                    seed=ordinal,
                    prompt_text=f"image {ordinal}",
                    diversity_vars={},
                    preview_svg="",
                    selected=True,
                    annotation_status="pending",
                )
            )
        dataset.image_count = 5
        dataset.selected_count = 5
        db.session.commit()

    first = client.get(
        f"/api/v1/datasets/{dataset_id}?images_limit=2", headers=headers
    ).get_json()["dataset"]
    assert [image["ordinal"] for image in first["images"]] == [1, 2]
    assert first["imagesNextCursor"]

    second = client.get(
        f"/api/v1/datasets/{dataset_id}?images_limit=2&images_cursor={first['imagesNextCursor']}",
        headers=headers,
    ).get_json()["dataset"]
    assert [image["ordinal"] for image in second["images"]] == [3, 4]
    assert {image["id"] for image in first["images"]}.isdisjoint(
        image["id"] for image in second["images"]
    )


def test_dataset_list_supports_keyset_cursor(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-list-cursor")
    for index in range(3):
        response = client.post(
            "/api/v1/datasets",
            headers=headers,
            json={"name": f"dataset number {index}", "categories": ["object"]},
        )
        assert response.status_code == 201

    first = client.get("/api/v1/datasets?limit=2", headers=headers).get_json()
    assert len(first["datasets"]) == 2
    assert first["nextCursor"]
    second = client.get(
        f"/api/v1/datasets?limit=2&cursor={first['nextCursor']}", headers=headers
    ).get_json()
    assert len(second["datasets"]) == 1
    assert {item["id"] for item in first["datasets"]}.isdisjoint(
        item["id"] for item in second["datasets"]
    )


def test_create_dataset_idempotency_key_replays_original_response(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = {
        **_auth_headers(client, "dataset-idempotency"),
        "Idempotency-Key": "create-dataset-1",
    }
    request_body = {"name": "idempotent dataset", "categories": ["object"]}
    first = client.post("/api/v1/datasets", headers=headers, json=request_body)
    second = client.post("/api/v1/datasets", headers=headers, json=request_body)
    assert first.status_code == second.status_code == 201
    assert first.get_json()["dataset"]["id"] == second.get_json()["dataset"]["id"]

    conflict = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={"name": "different dataset", "categories": ["object"]},
    )
    assert conflict.status_code == 409

    with app.app_context():
        assert Dataset.query.filter_by(name="idempotent dataset").count() == 1


def _fetch_images(client, dataset_id: str, headers: dict[str, str]) -> list[dict]:
    response = client.get(f"/api/v1/datasets/{dataset_id}", headers=headers)
    assert response.status_code == 200
    return response.get_json()["dataset"]["images"]


def test_detection_category_backfill_skips_empty_images(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-category-backfill")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None

        for ordinal in range(1, 4):
            dataset.images.append(
                DatasetImage(
                    dataset_id=dataset.id,
                    source_type="import",
                    source_ordinal=ordinal,
                    ordinal=ordinal,
                    status="uploaded",
                    seed=ordinal,
                    prompt_text=f"empty image {ordinal}",
                    diversity_vars={},
                    preview_svg="",
                    selected=True,
                    annotation_status="empty",
                    detection_categories=[],
                )
            )

        annotated_image = DatasetImage(
            dataset_id=dataset.id,
            source_type="import",
            source_ordinal=4,
            ordinal=4,
            status="uploaded",
            seed=4,
            prompt_text="annotated image",
            diversity_vars={},
            preview_svg="",
            selected=True,
            annotation_status="annotated",
            detection_categories=[],
        )
        dataset.images.append(annotated_image)
        db.session.flush()
        annotated_image_id = annotated_image.id
        save_annotation_result(
            str(tmp_path),
            dataset.id,
            annotated_image_id,
            [
                {
                    "category": "pedestrian",
                    "bbox": [0.5, 0.5, 0.5, 0.5],
                    "confidence": 0.9,
                }
            ],
        )
        db.session.commit()

        _backfill_detection_categories(app, batch_size=1)

        db.session.expire_all()
        assert db.session.get(DatasetImage, annotated_image_id).detection_categories == ["pedestrian"]


def test_list_datasets_uses_lightweight_payload_without_loading_images(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-list-lightweight")
    dataset_id = _create_dataset(client, headers)
    image_queries: list[str] = []

    def collect_image_queries(conn, cursor, statement, parameters, context, executemany):
        if "dataset_images" in statement.lower():
            image_queries.append(statement)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        task = DatasetTask(
            dataset_id=dataset.id,
            user_id=dataset.user_id,
            task_type="import",
            task_name="导入批次 1",
            subject=dataset.name,
            image_count=3,
            categories=dataset.categories,
            config_json={"source": "zip"},
            prompt_json={},
            status="completed",
            progress_percent=100,
            images_generated=3,
            selected_count=3,
            api_provider="local",
        )
        db.session.add(task)
        dataset.tasks.append(task)
        for ordinal in range(1, 4):
            image = DatasetImage(
                dataset_id=dataset.id,
                source_task_id=task.id,
                source_type="import",
                source_ordinal=ordinal,
                ordinal=ordinal,
                status="uploaded",
                seed=ordinal,
                prompt_text=f"image {ordinal}",
                diversity_vars={},
                preview_svg="",
                selected=True,
                annotation_status="pending",
                detection_categories=[],
            )
            db.session.add(image)
            dataset.images.append(image)
            task.images.append(image)
        dataset.image_count = 3
        dataset.selected_count = 3
        dataset.task_count = 1
        db.session.commit()
        task_id = task.id
        event.listen(db.engine, "before_cursor_execute", collect_image_queries)

    try:
        response = client.get("/api/v1/datasets", headers=headers)
    finally:
        with app.app_context():
            event.remove(db.engine, "before_cursor_execute", collect_image_queries)

    assert response.status_code == 200
    payload = response.get_json()
    listed_dataset = payload["datasets"][0]
    assert listed_dataset["id"] == dataset_id
    assert listed_dataset["images"] == []
    assert listed_dataset["imagesTotal"] == 3
    assert "imageClassCounts" not in listed_dataset
    assert "imageSplitCounts" not in listed_dataset
    assert "imageAnnotationCounts" not in listed_dataset
    assert listed_dataset["latestTask"]["id"] == task_id
    assert "sourceImageIds" not in listed_dataset["latestTask"]
    assert image_queries == []


def test_get_dataset_uses_paginated_payload_without_task_source_ids(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-detail-lightweight")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        source_ids: list[str] = []
        for ordinal in range(1, 4):
            image = DatasetImage(
                dataset_id=dataset.id,
                source_type="import",
                source_ordinal=ordinal,
                ordinal=ordinal,
                status="uploaded",
                seed=ordinal,
                prompt_text=f"image {ordinal}",
                diversity_vars={},
                preview_svg="",
                selected=True,
                annotation_status="pending",
                detection_categories=[],
            )
            db.session.add(image)
            dataset.images.append(image)
            db.session.flush()
            source_ids.append(image.id)

        task = DatasetTask(
            dataset_id=dataset.id,
            user_id=dataset.user_id,
            task_type="augmentation",
            task_name="增强批次 1",
            subject=dataset.name,
            image_count=3,
            categories=dataset.categories,
            config_json={
                "augmentation": {
                    "sourceImageIds": source_ids,
                    "sourceCount": len(source_ids),
                    "completedImages": 0,
                    "progressPercent": 0,
                }
            },
            prompt_json={},
            status="running",
            progress_percent=0,
            images_generated=0,
            selected_count=0,
            api_provider="local",
        )
        db.session.add(task)
        dataset.tasks.append(task)
        dataset.image_count = 3
        dataset.selected_count = 3
        dataset.task_count = 1
        db.session.commit()

    response = client.get(
        f"/api/v1/datasets/{dataset_id}?images_offset=0&images_limit=1",
        headers=headers,
    )

    assert response.status_code == 200
    dataset = response.get_json()["dataset"]
    assert len(dataset["images"]) == 1
    assert dataset["imagesTotal"] == 3
    assert dataset["tasks"][0]["taskName"] == "增强批次 1"
    assert "sourceImageIds" not in dataset["tasks"][0]
    assert "sourceImageIds" not in dataset["tasks"][0]["config"]["augmentation"]


def test_get_dataset_filters_split_class_and_annotation_from_queries(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-detail-query-filters")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        for ordinal in range(1, 13):
            selected = ordinal <= 10
            categories = ["umbrella"] if ordinal % 2 == 0 else ["pedestrian"]
            image = DatasetImage(
                dataset_id=dataset.id,
                source_type="import",
                source_ordinal=ordinal,
                ordinal=ordinal,
                status="uploaded",
                seed=ordinal,
                prompt_text=f"image {ordinal}",
                diversity_vars={},
                preview_svg="",
                selected=selected,
                annotation_status="annotated" if ordinal % 2 == 0 else "pending",
                detection_categories=categories,
            )
            db.session.add(image)
        dataset.image_count = 12
        dataset.selected_count = 10
        db.session.commit()

    train_response = client.get(
        f"/api/v1/datasets/{dataset_id}?images_offset=0&images_limit=20&filter_split=train",
        headers=headers,
    )
    assert train_response.status_code == 200
    train_dataset = train_response.get_json()["dataset"]
    assert train_dataset["imagesTotal"] == 7
    assert [image["ordinal"] for image in train_dataset["images"]] == list(range(1, 8))
    assert {image["split"] for image in train_dataset["images"]} == {"train"}

    class_response = client.get(
        f"/api/v1/datasets/{dataset_id}?images_offset=0&images_limit=20"
        "&filter_class=umbrella&filter_annotation=annotated",
        headers=headers,
    )
    assert class_response.status_code == 200
    class_dataset = class_response.get_json()["dataset"]
    assert class_dataset["imagesTotal"] == 6
    assert [image["ordinal"] for image in class_dataset["images"]] == [2, 4, 6, 8, 10, 12]
    assert class_dataset["imageClassCounts"]["umbrella"] == 6


def test_get_dataset_filters_by_image_source_group_and_reports_counts(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-detail-source-filter")
    dataset_id = _create_dataset(client, headers)
    source_types = [
        "generation",
        "import",
        "video",
        "roboflow",
        "augmentation",
        "augmentation",
        "generation",
    ]

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        for ordinal, source_type in enumerate(source_types, start=1):
            db.session.add(
                DatasetImage(
                    dataset_id=dataset.id,
                    source_type=source_type,
                    source_ordinal=ordinal,
                    ordinal=ordinal,
                    status="ready",
                    seed=ordinal,
                    prompt_text=f"{source_type} image {ordinal}",
                    diversity_vars={},
                    preview_svg="",
                    selected=True,
                    annotation_status="annotated" if ordinal % 2 == 0 else "pending",
                    detection_categories=["pedestrian"],
                )
            )
        dataset.image_count = len(source_types)
        dataset.selected_count = len(source_types)
        db.session.commit()

    imported_response = client.get(
        f"/api/v1/datasets/{dataset_id}?images_limit=2&filter_source=imported",
        headers=headers,
    )
    assert imported_response.status_code == 200
    imported_dataset = imported_response.get_json()["dataset"]
    assert imported_dataset["imagesTotal"] == 3
    assert [image["sourceType"] for image in imported_dataset["images"]] == ["import", "video"]
    assert imported_dataset["imagesNextCursor"]
    assert imported_dataset["imageSourceCounts"] == {
        "generation": 2,
        "imported": 3,
        "augmentation": 2,
    }

    imported_next_response = client.get(
        f"/api/v1/datasets/{dataset_id}?images_limit=2&filter_source=imported"
        f"&images_cursor={imported_dataset['imagesNextCursor']}",
        headers=headers,
    )
    assert imported_next_response.status_code == 200
    imported_next = imported_next_response.get_json()["dataset"]
    assert [image["sourceType"] for image in imported_next["images"]] == ["roboflow"]

    augmented_response = client.get(
        f"/api/v1/datasets/{dataset_id}?images_limit=20"
        "&filter_source=augmentation&filter_annotation=annotated",
        headers=headers,
    )
    assert augmented_response.status_code == 200
    augmented_dataset = augmented_response.get_json()["dataset"]
    assert augmented_dataset["imagesTotal"] == 1
    assert [image["ordinal"] for image in augmented_dataset["images"]] == [6]


def test_selection_bulk_update_avoids_loading_image_rows(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-selection-bulk-query")
    dataset_id = _create_dataset(client, headers)
    image_row_selects: list[str] = []

    def collect_image_row_selects(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.lower().split())
        if not normalized.startswith("select") or "from dataset_images" not in normalized:
            return
        if "count(" in normalized or "json_each" in normalized or "max(" in normalized or "row_number()" in normalized:
            return
        image_row_selects.append(statement)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        task = DatasetTask(
            dataset_id=dataset.id,
            user_id=dataset.user_id,
            task_type="import",
            task_name="导入批次 1",
            subject=dataset.name,
            image_count=8,
            categories=dataset.categories,
            config_json={"source": "zip"},
            prompt_json={},
            status="completed",
            progress_percent=100,
            images_generated=8,
            selected_count=8,
            api_provider="local",
        )
        db.session.add(task)
        db.session.flush()
        for ordinal in range(1, 9):
            db.session.add(
                DatasetImage(
                    dataset_id=dataset.id,
                    source_task_id=task.id,
                    source_type="import",
                    source_ordinal=ordinal,
                    ordinal=ordinal,
                    status="uploaded",
                    seed=ordinal,
                    prompt_text=f"image {ordinal}",
                    diversity_vars={},
                    preview_svg="",
                    selected=True,
                    annotation_status="pending",
                    detection_categories=[],
                )
            )
        dataset.image_count = 8
        dataset.selected_count = 8
        dataset.task_count = 1
        db.session.commit()
        event.listen(db.engine, "before_cursor_execute", collect_image_row_selects)

    try:
        response = client.patch(
            f"/api/v1/datasets/{dataset_id}/selection",
            headers=headers,
            json={"mode": "none"},
        )
    finally:
        with app.app_context():
            event.remove(db.engine, "before_cursor_execute", collect_image_row_selects)

    assert response.status_code == 200
    dataset = response.get_json()["dataset"]
    assert dataset["selectedCount"] == 0
    assert dataset["tasks"][0]["selectedCount"] == 0
    assert image_row_selects == []


def test_generation_task_writes_images_into_dataset_pool(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-generation")
    dataset_id = _create_dataset(client, headers)
    task_id = _create_generation_task(client, dataset_id, headers)

    with app.app_context():
        stored_task = db.session.get(DatasetTask, task_id)
        assert "api_key" not in stored_task.config_json
        assert stored_task.api_key_encrypted

    with patch(
        "app.worker_tasks.generate_gemini_image",
        return_value={"image_bytes": _png_bytes(), "mime_type": "image/png", "prompt": "ok"},
    ):
        response = client.post(f"/api/v1/datasets/{dataset_id}/tasks/{task_id}/start", headers=headers, json={})

    assert response.status_code == 200
    payload = response.get_json()
    dataset = payload["dataset"]
    task = payload["task"]
    assert dataset["imageCount"] == 5
    assert task["imagesGenerated"] == 5
    images = _fetch_images(client, dataset_id, headers)
    assert len(images) == 5
    assert all(image["datasetId"] == dataset_id for image in images)
    assert all(image["sourceTaskId"] == task_id for image in images)
    assert all(image["sourceType"] == "generation" for image in images)


def test_generation_start_falls_back_to_inline_execution_when_queue_is_unavailable(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-inline-fallback")
    dataset_id = _create_dataset(client, headers)
    task_id = _create_generation_task(client, dataset_id, headers)

    with (
        patch(
            "app.worker_tasks.generate_gemini_image",
            return_value={"image_bytes": _png_bytes(), "mime_type": "image/png", "prompt": "ok"},
        ),
        patch("app.worker_tasks.generate_dataset_task_images.delay", side_effect=RuntimeError("queue unavailable")),
    ):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/{task_id}/start",
            headers=headers,
            json={},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["task"]["imagesGenerated"] == 5
    assert payload["dataset"]["imageCount"] == 5


def test_import_and_export_operate_at_dataset_level(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-import")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample-a.png", _transparent_png_bytes())
        archive.writestr("sample-b.png", _transparent_png_bytes())
    archive_buffer.seek(0)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert import_response.status_code == 200
    import_payload = import_response.get_json()
    dataset = import_payload["dataset"]
    assert dataset["imageCount"] == 2
    assert dataset["selectedCount"] == 2
    assert dataset["taskCount"] == 1
    images = _fetch_images(client, dataset_id, headers)
    assert all(image["sourceType"] == "import" for image in images)
    with app.app_context():
        imported_dataset = db.session.get(Dataset, dataset_id)
        assert imported_dataset is not None
        assert imported_dataset.next_image_ordinal == 3

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201
    export_payload = export_response.get_json()
    assert export_payload["export"]["status"] == "ready"
    assert export_payload["export"]["summary"]["imageFormat"] == "png"

    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.mimetype == "application/zip"

    archive = zipfile.ZipFile(BytesIO(download.data))
    image_names = [name for name in archive.namelist() if name.endswith(".png")]
    assert image_names
    exported_image = Image.open(BytesIO(archive.read(image_names[0])))
    assert exported_image.mode == "RGBA"


def test_import_yolo_archive_preserves_annotations_and_split(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-yolo-import")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "export/data.yaml",
            "train: images/train\nval: images/val\nnames: [pedestrian, umbrella]\n",
        )
        archive.writestr("export/images/train/sample.png", _png_bytes())
        archive.writestr(
            "export/labels/train/sample.txt",
            "0 0.500000 0.500000 0.250000 0.500000\n",
        )
    archive_buffer.seek(0)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    task = response.get_json()["task"]
    assert task["status"] == "completed"
    runtime = task["config"]["runtime"]
    assert runtime["annotatedCount"] == 1
    assert runtime["detectedFormat"] == "yolo"
    assert runtime["emptyAnnotationCount"] == 0
    assert runtime["importedCount"] == 1
    assert runtime["skippedCount"] == 0
    assert runtime["skippedFiles"] == []
    image = _fetch_images(client, dataset_id, headers)[0]
    assert image["annotationStatus"] == "annotated"
    assert image["split"] == "train"
    assert image["detections"] == [
        {
            "category": "pedestrian",
            "confidence": 1.0,
            "bbox": [0.5, 0.5, 0.25, 0.5],
        }
    ]


def test_import_rejects_malformed_yolo_archive_with_actionable_error(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-invalid-yolo-import")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("data.yaml", "train: images/train\n")
        archive.writestr("images/train/sample.png", _png_bytes())
        archive.writestr("labels/train/sample.txt", "0 0.5 0.5 0.2 0.2\n")
    archive_buffer.seek(0)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    task = response.get_json()["task"]
    assert task["status"] == "failed"
    assert "无法解析 YOLO 标注" in task["config"]["runtime"]["workerError"]


def test_selection_can_target_visible_image_scope(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-selection-scope")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample-a.png", _transparent_png_bytes())
        archive.writestr("sample-b.png", _transparent_png_bytes())
    archive_buffer.seek(0)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert import_response.status_code == 200
    image_ids = [image["id"] for image in _fetch_images(client, dataset_id, headers)]

    response = client.patch(
        f"/api/v1/datasets/{dataset_id}/selection",
        headers=headers,
        json={"mode": "none", "image_ids": [image_ids[0]]},
    )

    assert response.status_code == 200
    dataset = response.get_json()["dataset"]
    fetched = _fetch_images(client, dataset_id, headers)
    by_id = {image["id"]: image for image in fetched}
    assert [by_id[image_ids[0]]["selected"], by_id[image_ids[1]]["selected"]] == [False, True]
    assert dataset["selectedCount"] == 1


def test_delete_single_dataset_image_updates_pool_stats_and_assets(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-delete-single")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample-a.png", _transparent_png_bytes())
        archive.writestr("sample-b.png", _transparent_png_bytes())
    archive_buffer.seek(0)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert import_response.status_code == 200
    image = _fetch_images(client, dataset_id, headers)[0]
    image_path = existing_generated_image(str(tmp_path), dataset_id, f"image-{image['ordinal']:06d}")
    assert image_path is not None
    assert image_path.exists()

    annotation_response = client.patch(
        f"/api/v1/datasets/{dataset_id}/images/{image['id']}/annotations",
        headers=headers,
        json={"detections": [{"category": "pedestrian", "confidence": 0.8, "bbox": [0.5, 0.5, 0.2, 0.2]}]},
    )
    assert annotation_response.status_code == 200
    annotation_path = Path(tmp_path) / "annotations" / dataset_id / f"{image['id']}.json"
    assert annotation_path.exists()

    delete_response = client.delete(f"/api/v1/datasets/{dataset_id}/images/{image['id']}", headers=headers)

    assert delete_response.status_code == 200
    payload = delete_response.get_json()
    assert payload["deletedImageIds"] == [image["id"]]
    assert payload["deletedCount"] == 1
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 1
    assert dataset["selectedCount"] == 1
    assert dataset["tasks"][0]["imagesGenerated"] == 1
    assert dataset["tasks"][0]["selectedCount"] == 1
    assert all(item["id"] != image["id"] for item in _fetch_images(client, dataset_id, headers))
    assert not image_path.exists()
    assert not annotation_path.exists()


def test_annotation_update_rejects_unknown_category_without_writing_revision(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-unknown-annotation-category")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample.png", _png_bytes())
    archive_buffer.seek(0)
    imported = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 200
    image = _fetch_images(client, dataset_id, headers)[0]

    response = client.patch(
        f"/api/v1/datasets/{dataset_id}/images/{image['id']}/annotations",
        headers=headers,
        json={
            "detections": [
                {"category": "vehicle", "confidence": 0.8, "bbox": [0.5, 0.5, 0.2, 0.2]}
            ]
        },
    )

    assert response.status_code == 422
    assert response.get_json()["unknownCategories"] == ["vehicle"]
    assert not (Path(tmp_path) / "annotations" / dataset_id / f"{image['id']}.json").exists()


def test_generation_soft_limit_releases_lease_for_resume(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-generation-soft-limit")
    dataset_id = _create_dataset(client, headers)
    task_id = _create_generation_task(client, dataset_id, headers)

    with app.app_context():
        task = db.session.get(DatasetTask, task_id)
        task.status = "running"
        db.session.commit()

        from app.worker_tasks import generate_dataset_task_images

        with patch(
            "app.worker_tasks._generate_dataset_asset",
            side_effect=SoftTimeLimitExceeded(),
        ), pytest.raises(SoftTimeLimitExceeded):
            generate_dataset_task_images.run(task_id)

        db.session.expire_all()
        task = db.session.get(DatasetTask, task_id)
        item = TaskItem.query.filter_by(task_id=task_id, item_index=1).one()
        assert task.status == "running"
        assert task.completed_at is None
        assert item.status == "queued"
        assert item.lease_expires_at is None
        assert item.last_error == "soft time limit reached"


def test_delete_multiple_dataset_images_clears_pool(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-delete-bulk")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample-a.png", _transparent_png_bytes())
        archive.writestr("sample-b.png", _transparent_png_bytes())
    archive_buffer.seek(0)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert import_response.status_code == 200
    image_ids = [image["id"] for image in _fetch_images(client, dataset_id, headers)]

    delete_response = client.delete(
        f"/api/v1/datasets/{dataset_id}/images",
        headers=headers,
        json={"image_ids": image_ids},
    )

    assert delete_response.status_code == 200
    payload = delete_response.get_json()
    assert payload["deletedImageIds"] == image_ids
    assert payload["deletedCount"] == 2
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 0
    assert dataset["selectedCount"] == 0
    assert dataset["tasks"][0]["imagesGenerated"] == 0
    assert dataset["tasks"][0]["selectedCount"] == 0
    assert _fetch_images(client, dataset_id, headers) == []


def test_video_import_extracts_frames_into_dataset_pool_and_export_names(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-import")
    dataset_id = _create_dataset(client, headers)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=6)), "sample.avi"),
            "frame_interval_mode": "frames",
            "frame_interval": "2",
            "output_format": "png",
            "jpeg_quality": "95",
            "filename_prefix": "video_frame",
            "target_size": "original",
        },
        content_type="multipart/form-data",
    )

    assert import_response.status_code == 201
    payload = import_response.get_json()
    assert payload["summary"]["importedCount"] == 3
    assert payload["task"]["taskType"] == "import"
    assert payload["task"]["status"] == "completed"
    assert payload["task"]["config"]["source"] == "video"
    assert payload["task"]["config"]["video"]["frameInterval"] == 2
    assert payload["task"]["config"]["video"]["targetSize"] == "original"
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 3
    assert dataset["selectedCount"] == 3
    images = _fetch_images(client, dataset_id, headers)
    assert {image["sourceType"] for image in images} == {"video"}
    assert images[0]["diversityVars"]["outputFilename"] == "video_frame_000000.png"

    second_import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=6)), "sample-again.avi"),
            "frame_interval_mode": "frames",
            "frame_interval": "2",
            "output_format": "png",
            "jpeg_quality": "95",
            "filename_prefix": "video_frame",
        },
        content_type="multipart/form-data",
    )
    assert second_import_response.status_code == 201

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201

    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    assert download.status_code == 200
    archive = zipfile.ZipFile(BytesIO(download.data))
    image_names = [name for name in archive.namelist() if name.endswith(".png")]
    label_names = [name for name in archive.namelist() if name.endswith(".txt")]
    assert len(image_names) == 6
    assert len(label_names) == 6
    assert any(name.endswith("video_frame_000000_000001.png") for name in image_names)
    assert any(name.endswith("video_frame_000000_000004.png") for name in image_names)


def test_video_import_supports_seconds_interval(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-seconds-import")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=6)), "sample.avi"),
            "frame_interval_mode": "seconds",
            "frame_interval_seconds": "0.4",
            "output_format": "png",
            "jpeg_quality": "95",
            "filename_prefix": "second_frame",
            "target_size": "original",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    payload = response.get_json()
    video_config = payload["task"]["config"]["video"]
    assert video_config["frameIntervalMode"] == "seconds"
    assert video_config["frameIntervalSeconds"] == 0.4
    assert video_config["frameRate"] == 5.0
    assert video_config["effectiveFrameInterval"] == 2
    assert video_config["expectedFrames"] == 3
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 3
    images = _fetch_images(client, dataset_id, headers)
    assert [image["diversityVars"]["sourceFrame"] for image in images] == ["0", "2", "4"]
    assert images[0]["diversityVars"]["outputFilename"] == "second_frame_000000.png"


def test_video_import_defaults_to_seconds_interval(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-default-seconds")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=26)), "sample.avi"),
            "output_format": "png",
            "jpeg_quality": "95",
            "filename_prefix": "default_second_frame",
            "target_size": "original",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    payload = response.get_json()
    video_config = payload["task"]["config"]["video"]
    assert video_config["frameIntervalMode"] == "seconds"
    assert video_config["frameIntervalSeconds"] == 5.0
    assert video_config["frameRate"] == 5.0
    assert video_config["effectiveFrameInterval"] == 25
    assert video_config["expectedFrames"] == 2
    assert payload["dataset"]["imageCount"] == 2


def test_video_import_resizes_frames_to_target_size(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-resize")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=1, size=(800, 600))), "sample.avi"),
            "frame_interval": "1",
            "output_format": "jpg",
            "jpeg_quality": "90",
            "filename_prefix": "resized_frame",
            "target_size": "720p",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    payload = response.get_json()
    video_config = payload["task"]["config"]["video"]
    assert video_config["targetSize"] == "720p"
    assert video_config["targetMaxDimension"] == 720
    image_path = existing_generated_image(str(tmp_path), dataset_id, "image-000001")
    assert image_path is not None
    with Image.open(image_path) as image:
        assert max(image.size) == 720
        assert min(image.size) == 540


def test_video_import_replaces_stale_static_image_variant(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        IMAGE_BASE_URL = "http://assets.local/images"

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-stale-static")
    dataset_id = _create_dataset(client, headers)
    save_generated_image(str(tmp_path), dataset_id, "image-000001", _png_bytes((255, 0, 0)), "image/png")

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=1)), "sample.avi"),
            "frame_interval": "1",
            "output_format": "jpg",
            "jpeg_quality": "90",
            "filename_prefix": "fresh_frame",
            "target_size": "original",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    image = _fetch_images(client, dataset_id, headers)[0]
    assert image["previewSvg"] == f"http://assets.local/images/{dataset_id}/image-000001.jpg?v={image['id']}"
    assert not (tmp_path / "images" / dataset_id / "image-000001.png").exists()
    image_path = existing_generated_image(str(tmp_path), dataset_id, "image-000001")
    assert image_path is not None
    assert image_path.name == "image-000001.jpg"


def test_video_import_saves_source_before_database_insert(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-save-before-db")
    dataset_id = _create_dataset(client, headers)
    saved: dict[str, str] = {}

    def fake_save_video_source(storage_root: str, task_id: str, upload) -> str:
        assert storage_root == str(tmp_path)
        assert task_id
        assert not db.session.new
        saved["task_id"] = task_id
        return f"import_sources/{task_id}/{upload.filename}"

    with patch("app.api.datasets.save_video_import_source", side_effect=fake_save_video_source), patch(
        "app.api.datasets._dispatch_background_task"
    ):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/video",
            headers=headers,
            data={
                "video": (BytesIO(b"video-bytes"), "sample.mp4"),
                "frame_interval": "1",
                "output_format": "jpg",
                "jpeg_quality": "90",
                "filename_prefix": "frame",
                "target_size": "original",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 201
    assert response.get_json()["task"]["id"] == saved["task_id"]


def test_video_import_marks_task_failed_when_extraction_fails(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-extraction-fails")
    dataset_id = _create_dataset(client, headers)

    with patch("app.worker_tasks.video_frame_count", side_effect=RuntimeError("metadata read failed")):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/video",
            headers=headers,
            data={
                "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=1)), "sample.avi"),
                "frame_interval": "1",
                "output_format": "jpg",
                "jpeg_quality": "90",
                "filename_prefix": "frame",
                "target_size": "original",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 201
    task = response.get_json()["task"]
    assert task["status"] == "failed"
    assert task["config"]["video"]["status"] == "failed"
    assert task["config"]["video"]["error"] == "metadata read failed"


def test_video_import_rejects_unsupported_file_type(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-invalid")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={"video": (BytesIO(b"not a video"), "sample.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "只支持上传" in response.get_json()["message"]


def test_roboflow_import_downloads_images_and_yolo_annotations(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-import")
    dataset_id = _create_dataset(client, headers)

    class FakeRoboflowVersion:
        def download(self, model_format: str, location: str, overwrite: bool = False):
            assert model_format == "yolov8"
            assert overwrite is True
            assert not Path(location).exists()
            root = Path(location) / "workspace-project-1"
            images_dir = root / "train" / "images"
            labels_dir = root / "train" / "labels"
            images_dir.mkdir(parents=True)
            labels_dir.mkdir(parents=True)
            (root / "data.yaml").write_text("names:\n- pedestrian\n- umbrella\n", encoding="utf-8")
            (images_dir / "sample-a.png").write_bytes(_png_bytes())
            (labels_dir / "sample-a.txt").write_text("1 0.500000 0.600000 0.250000 0.300000\n", encoding="utf-8")
            (images_dir / "sample-b.png").write_bytes(_png_bytes((20, 40, 60)))
            return SimpleNamespace(location=str(root))

    class FakeRoboflowProject:
        def version(self, version: str):
            assert version == "1"
            return FakeRoboflowVersion()

    class FakeRoboflowWorkspace:
        def project(self, project: str):
            assert project == "street-project"
            return FakeRoboflowProject()

    class FakeRoboflowClient:
        def workspace(self, workspace: str):
            assert workspace == "demo-workspace"
            return FakeRoboflowWorkspace()

    with patch("app.services.roboflow_import_service._make_roboflow_client", return_value=FakeRoboflowClient()):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
            headers=headers,
            json={
                "apiKey": "roboflow-test-key",
                "workspace": "demo-workspace",
                "project": "street-project",
                "version": "1",
                "format": "yolov8",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["importedCount"] == 2
    assert payload["summary"]["annotatedCount"] == 1
    assert payload["summary"]["emptyAnnotationCount"] == 1
    assert payload["task"]["taskType"] == "import"
    assert payload["task"]["config"]["source"] == "roboflow"
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 2
    assert dataset["annotation"]["provider"] == "roboflow"
    images = _fetch_images(client, dataset_id, headers)
    assert {image["sourceType"] for image in images} == {"roboflow"}

    annotated_image = next(image for image in images if image["annotationStatus"] == "annotated")
    assert annotated_image["detections"] == [
        {
            "category": "umbrella",
            "confidence": 1.0,
            "bbox": [0.5, 0.6, 0.25, 0.3],
        }
    ]

    stored = load_annotation_result(str(tmp_path), dataset_id, annotated_image["id"])
    assert stored is not None
    assert stored["detections"][0]["category"] == "umbrella"


def test_roboflow_import_decodes_labels_with_imported_category_order(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-category-order")
    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "name": "mixed category dataset",
            "categories": ["vehicle"],
            "description": "existing categories should not shift imported Roboflow class ids",
        },
    )
    assert response.status_code == 201
    dataset_id = response.get_json()["dataset"]["id"]

    class FakeRoboflowVersion:
        def download(self, model_format: str, location: str, overwrite: bool = False):
            root = Path(location) / "workspace-project-1"
            images_dir = root / "train" / "images"
            labels_dir = root / "train" / "labels"
            images_dir.mkdir(parents=True)
            labels_dir.mkdir(parents=True)
            (root / "data.yaml").write_text("names:\n- pedestrian\n- umbrella\n", encoding="utf-8")
            (images_dir / "sample-a.png").write_bytes(_png_bytes())
            (labels_dir / "sample-a.txt").write_text("1 0.500000 0.600000 0.250000 0.300000\n", encoding="utf-8")
            return SimpleNamespace(location=str(root))

    class FakeRoboflowProject:
        def version(self, version: str):
            return FakeRoboflowVersion()

    class FakeRoboflowWorkspace:
        def project(self, project: str):
            return FakeRoboflowProject()

    class FakeRoboflowClient:
        def workspace(self, workspace: str):
            return FakeRoboflowWorkspace()

    with patch("app.services.roboflow_import_service._make_roboflow_client", return_value=FakeRoboflowClient()):
        import_response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
            headers=headers,
            json={
                "apiKey": "roboflow-test-key",
                "workspace": "demo-workspace",
                "project": "street-project",
                "version": "1",
                "format": "yolov8",
            },
        )

    assert import_response.status_code == 200
    dataset = import_response.get_json()["dataset"]
    assert dataset["categories"] == ["vehicle", "pedestrian", "umbrella"]
    images = _fetch_images(client, dataset_id, headers)
    assert images[0]["detections"][0]["category"] == "umbrella"

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201
    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    archive = zipfile.ZipFile(BytesIO(download.data))
    label_name = next(name for name in archive.namelist() if name.endswith(".txt"))
    assert archive.read(label_name).decode("utf-8").startswith("2 0.500000 0.600000 0.250000 0.300000")


def test_roboflow_import_extracts_downloaded_zip_archives(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-zip")
    dataset_id = _create_dataset(client, headers)

    class FakeRoboflowVersion:
        def download(self, model_format: str, location: str, overwrite: bool = False):
            assert overwrite is True
            assert not Path(location).exists()
            archive_path = Path(location) / "roboflow-export.zip"
            archive_path.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("export/data.yaml", "names: ['pedestrian', 'umbrella']\n")
                archive.writestr("export/valid/images/sample-a.png", _png_bytes())
                archive.writestr("export/valid/labels/sample-a.txt", "0 0.500000 0.500000 0.400000 0.400000\n")
            return SimpleNamespace(location=str(archive_path))

    class FakeRoboflowProject:
        def version(self, version: str):
            assert version == "release-v2"
            return FakeRoboflowVersion()

    class FakeRoboflowWorkspace:
        def project(self, project: str):
            return FakeRoboflowProject()

    class FakeRoboflowClient:
        def workspace(self, workspace: str):
            return FakeRoboflowWorkspace()

    with patch("app.services.roboflow_import_service._make_roboflow_client", return_value=FakeRoboflowClient()):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
            headers=headers,
            json={
                "apiKey": "roboflow-test-key",
                "workspace": "demo-workspace",
                "project": "street-project",
                "version": "release-v2",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["importedCount"] == 1
    assert payload["summary"]["annotatedCount"] == 1
    assert _fetch_images(client, dataset_id, headers)[0]["detections"][0]["category"] == "pedestrian"


def test_roboflow_import_requires_api_key_payload(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-missing-key")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
        headers=headers,
        json={"workspace": "demo", "project": "project", "version": "1"},
    )

    assert response.status_code == 422
    assert "apiKey" in response.get_json()["errors"]


def test_augmentation_task_uses_source_snapshot_after_selection_changes(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-augmentation-source-snapshot")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        source_image = DatasetImage(
            dataset_id=dataset.id,
            source_type="generation",
            source_ordinal=1,
            ordinal=1,
            status="ready",
            seed=17,
            prompt_text="first source",
            diversity_vars={"source": "first"},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="pending",
            detection_categories=[],
        )
        db.session.add(source_image)
        db.session.flush()
        source_image_id = source_image.id
        save_generated_image(
            app.config["STORAGE_ROOT"],
            dataset.id,
            "image-000001",
            _png_bytes((20, 40, 60)),
            "image/png",
        )
        dataset.image_count = 1
        dataset.selected_count = 1
        db.session.commit()

    with patch("app.api.datasets._dispatch_background_task"):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/augmentation",
            headers=headers,
            json={"multiplier": 2, "augmentation_methods": ["flip"]},
        )

    assert response.status_code == 201
    task_payload = response.get_json()["task"]
    task_id = task_payload["id"]
    assert "sourceImageIds" not in task_payload["config"]["augmentation"]

    with app.app_context():
        source_image = db.session.get(DatasetImage, source_image_id)
        assert source_image is not None
        source_image.selected = False

        new_source = DatasetImage(
            dataset_id=dataset_id,
            source_type="generation",
            source_ordinal=2,
            ordinal=2,
            status="ready",
            seed=29,
            prompt_text="second source",
            diversity_vars={"source": "second"},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="pending",
            detection_categories=[],
        )
        db.session.add(new_source)
        save_generated_image(
            app.config["STORAGE_ROOT"],
            dataset_id,
            "image-000002",
            _png_bytes((70, 90, 120)),
            "image/png",
        )
        db.session.commit()

        from app.worker_tasks import augment_dataset_task_images

        augment_dataset_task_images.apply(args=(task_id,), throw=True)

        task = db.session.get(DatasetTask, task_id)
        assert task is not None
        source_ids = (task.config_json or {})["augmentation"]["sourceImageIds"]
        assert source_ids == [source_image_id]

        augmented = DatasetImage.query.filter_by(source_task_id=task_id).one()
        assert augmented.status == "augmented"
        assert "first source" in augmented.prompt_text
        assert augmented.diversity_vars["source"] == "first"
        assert task.status == "completed"


def test_augmentation_inherits_transformed_annotations(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-augmentation-annotations")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        source_image = DatasetImage(
            dataset_id=dataset.id,
            source_type="generation",
            source_ordinal=1,
            ordinal=1,
            status="ready",
            seed=17,
            prompt_text="annotated source",
            diversity_vars={},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="annotated",
            detection_categories=["pedestrian"],
            confidence_score=0.88,
        )
        db.session.add(source_image)
        db.session.flush()
        source_image_id = source_image.id
        save_generated_image(
            app.config["STORAGE_ROOT"],
            dataset.id,
            "image-000001",
            _png_bytes((20, 40, 60)),
            "image/png",
        )
        save_annotation_result(
            app.config["STORAGE_ROOT"],
            dataset.id,
            source_image.id,
            [{"category": "pedestrian", "confidence": 0.88, "bbox": [0.25, 0.5, 0.2, 0.4]}],
        )
        dataset.image_count = 1
        dataset.selected_count = 1
        db.session.commit()

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/augmentation",
        headers=headers,
        json={
            "multiplier": 2,
            "augmentation_methods": ["flip"],
            "augmentation_settings": {"flip": {"mode": "horizontal"}},
        },
    )

    assert response.status_code == 201
    images = _fetch_images(client, dataset_id, headers)
    augmented = next(image for image in images if image["sourceType"] == "augmentation")
    assert augmented["annotationStatus"] == "annotated"
    assert augmented["detections"] == [
        {"category": "pedestrian", "confidence": 0.88, "bbox": [0.75, 0.5, 0.2, 0.4]}
    ]

    stored = load_annotation_result(str(tmp_path), dataset_id, augmented["id"])
    assert stored is not None
    assert stored["detections"][0]["bbox"] == [0.75, 0.5, 0.2, 0.4]

    with app.app_context():
        source = db.session.get(DatasetImage, source_image_id)
        assert source is not None
        augmented_model = db.session.get(DatasetImage, augmented["id"])
        assert augmented_model is not None
        assert source.annotation_status == "annotated"
        assert augmented_model.detection_categories == ["pedestrian"]
        assert augmented_model.confidence_score == 0.88

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201

    download = client.get(f"/api/v1/datasets/{dataset_id}/exports/1/download", headers=headers)
    assert download.status_code == 200
    archive = zipfile.ZipFile(BytesIO(download.data))
    augmented_labels = [
        archive.read(name).decode("utf-8")
        for name in archive.namelist()
        if name.endswith("pedestrian_000002.txt")
    ]
    assert augmented_labels == ["0 0.750000 0.500000 0.200000 0.400000\n"]


def test_augmentation_inherits_empty_annotations(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-augmentation-empty-annotations")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset is not None
        source_image = DatasetImage(
            dataset_id=dataset.id,
            source_type="generation",
            source_ordinal=1,
            ordinal=1,
            status="ready",
            seed=17,
            prompt_text="empty source",
            diversity_vars={},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="empty",
            detection_categories=[],
            confidence_score=None,
        )
        db.session.add(source_image)
        db.session.flush()
        save_generated_image(
            app.config["STORAGE_ROOT"],
            dataset.id,
            "image-000001",
            _png_bytes((20, 40, 60)),
            "image/png",
        )
        dataset.image_count = 1
        dataset.selected_count = 1
        db.session.commit()

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/augmentation",
        headers=headers,
        json={"multiplier": 2, "augmentation_methods": ["flip"]},
    )

    assert response.status_code == 201
    augmented = next(
        image for image in _fetch_images(client, dataset_id, headers) if image["sourceType"] == "augmentation"
    )
    assert augmented["annotationStatus"] == "empty"
    stored = load_annotation_result(str(tmp_path), dataset_id, augmented["id"])
    assert stored == {"bboxSemantics": "center_size", "detections": []}


def test_retry_failed_augmentation_task_resets_augmentation_status(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-augmentation-retry")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        source_image = DatasetImage(
            dataset_id=dataset_id,
            source_type="generation",
            source_ordinal=1,
            ordinal=1,
            status="ready",
            seed=17,
            prompt_text="street scene",
            diversity_vars={"weather": "rain"},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="pending",
        )
        db.session.add(source_image)
        db.session.flush()

        save_generated_image(
            app.config["STORAGE_ROOT"],
            dataset_id,
            "image-000001",
            _png_bytes((20, 40, 60)),
            "image/png",
        )

        task = DatasetTask(
            dataset_id=dataset_id,
            user_id=source_image.dataset.user_id,
            task_type="augmentation",
            task_name="增强批次 1",
            subject=source_image.dataset.name,
            image_count=1,
            categories=source_image.dataset.categories,
            config_json={
                "augmentation": {
                    "multiplier": 2,
                    "methods": ["flip"],
                    "settings": {},
                    "sourceCount": 1,
                    "sourceImageIds": [source_image.id],
                    "estimatedAddedImages": 1,
                    "totalImagesToCreate": 1,
                    "completedImages": 0,
                    "progressPercent": 0,
                    "status": "failed",
                    "error": "simulated_failure",
                    "updatedAt": "2025-01-01T00:00:00",
                }
            },
            prompt_json={},
            status="failed",
            progress_percent=0,
            api_provider="local",
        )
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/{task_id}/retry",
        headers=headers,
        json={},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["task"]["status"] == "completed"
    assert payload["task"]["imagesGenerated"] == 1
    assert payload["task"]["config"]["augmentation"]["status"] == "completed"
    assert payload["dataset"]["imageCount"] == 2


def test_assist_subject_returns_categories_and_description(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-assist")

    profiles_response = client.get("/api/v1/system/model-profiles", headers=headers)
    assert profiles_response.status_code == 200
    llm_profile = next(
        profile
        for profile in profiles_response.get_json()["profiles"]
        if profile["profileType"] == "llm"
    )

    with patch(
        "app.api.datasets.suggest_subject_fields",
        return_value={
            "categories": ["pedestrian", "umbrella"],
            "extra_desc": "夜间雨天路口，突出行人遮挡、雨伞形态和车灯眩光影响。",
        },
    ):
        response = client.post(
            "/api/v1/datasets/assist-subject",
            headers=headers,
            json={
                "subject": "雨天城市道路行人检测",
                "llmProfileId": llm_profile["id"],
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["categories"] == ["pedestrian", "umbrella"]
    assert payload["extra_desc"] == "夜间雨天路口，突出行人遮挡、雨伞形态和车灯眩光影响。"
