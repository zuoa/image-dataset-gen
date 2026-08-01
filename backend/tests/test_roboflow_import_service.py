from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from app import create_app
from app.config import TestConfig
from app.services.roboflow_import_service import (
    RoboflowImportError,
    _prepare_roboflow_export,
)


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_roboflow_export_matches_case_insensitive_sibling_labels_and_polygons(
    tmp_path: Path,
):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path / "storage")

    export_root = tmp_path / "export"
    images_dir = export_root / "TRAIN"
    labels_dir = images_dir / "LABELS"
    labels_dir.mkdir(parents=True)
    (export_root / "data.yaml").write_text("names: [vehicle]\n", encoding="utf-8")
    (images_dir / "SAMPLE.PNG").write_bytes(_png_bytes())
    coordinates = [0.1, 0.2, 0.4, 0.2, 0.4, 0.8, 0.1, 0.8]
    (labels_dir / "sample.TXT").write_text(
        "0 " + " ".join(str(value) for value in coordinates) + "\n",
        encoding="utf-8",
    )

    app = create_app(DatasetConfig)
    with app.app_context():
        prepared, categories, skipped = _prepare_roboflow_export(export_root, [])

    assert categories == ["vehicle"]
    assert skipped == []
    assert len(prepared) == 1
    assert prepared[0].label_path == labels_dir / "sample.TXT"
    assert prepared[0].detections == [
        {
            "category": "vehicle",
            "confidence": 1.0,
            "bbox": [0.25, 0.5, 0.3, 0.6],
            "sourceYoloCoordinates": coordinates,
        }
    ]


def test_prepare_roboflow_export_rejects_nonempty_labels_when_nothing_can_be_parsed(
    tmp_path: Path,
):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path / "storage")

    export_root = tmp_path / "export"
    images_dir = export_root / "train" / "images"
    labels_dir = export_root / "train" / "labels"
    images_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    (export_root / "data.yaml").write_text("names: [vehicle]\n", encoding="utf-8")
    (images_dir / "sample.png").write_bytes(_png_bytes())
    (labels_dir / "sample.txt").write_text(
        "0 unsupported-label-payload\n",
        encoding="utf-8",
    )

    app = create_app(DatasetConfig)
    with app.app_context(), pytest.raises(
        RoboflowImportError,
        match="已停止导入以避免标注丢失",
    ):
        _prepare_roboflow_export(export_root, [])
