import importlib.util
from io import BytesIO
import json
from pathlib import Path

import albumentations as A
import numpy as np
from PIL import Image

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/image_storage.py"
SPEC = importlib.util.spec_from_file_location("image_storage_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
image_storage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_storage)


def test_rotate_augmentation_uses_custom_max_angle():
    transform, operation = image_storage._build_augmentation_transform(
        "rotate",
        image_storage.random.Random(17),
        {"rotate": {"max_angle": 4.5}},
        32,
        24,
    )

    assert isinstance(transform, A.Rotate)
    assert transform.limit == (-4.5, 4.5)
    assert operation == {
        "method": "rotate",
        "size": [32, 24],
        "max_angle": 4.5,
        "transform": "Rotate",
    }


def test_flip_augmentation_honors_mode_override():
    transform, operation = image_storage._build_augmentation_transform(
        "flip",
        image_storage.random.Random(17),
        {"flip": {"mode": "horizontal"}},
        4,
        1,
    )
    image = np.zeros((1, 4, 3), dtype=np.uint8)
    image[0, 0] = (255, 0, 0)
    image[0, 3] = (0, 0, 255)
    flipped = transform(image=image)["image"]

    assert flipped[0, 0].tolist() == [0, 0, 255]
    assert flipped[0, 3].tolist() == [255, 0, 0]
    assert operation["mode"] == "horizontal"


def test_save_generated_image_replaces_stale_extension(tmp_path: Path):
    image_storage.save_generated_image(str(tmp_path), "dataset-1", "image-000001", b"old", "image/png")
    stale_path = tmp_path / "images" / "dataset-1" / "image-000001.png"
    assert stale_path.exists()

    saved_path = image_storage.save_generated_image(
        str(tmp_path), "dataset-1", "image-000001", b"new", "image/jpeg"
    )

    assert saved_path == tmp_path / "images" / "dataset-1" / "image-000001.jpg"
    assert saved_path.read_bytes() == b"new"
    assert not stale_path.exists()
    assert image_storage.existing_generated_image(str(tmp_path), "dataset-1", "image-000001") == saved_path


def test_augment_generated_image_transforms_boxes_and_records_replay(tmp_path: Path):
    buffer = BytesIO()
    Image.new("RGB", (10, 8), color=(255, 255, 255)).save(buffer, format="PNG")
    image_storage.save_generated_image(
        str(tmp_path),
        "dataset-1",
        "image-000001",
        buffer.getvalue(),
        "image/png",
    )

    result = image_storage.augment_generated_image(
        str(tmp_path),
        "dataset-1",
        "image-000001",
        "image-000002",
        ["flip"],
        17,
        {"flip": {"mode": "horizontal"}},
        detections=[
            {
                "category": "worker",
                "confidence": 0.9,
                "bbox": [0.25, 0.5, 0.2, 0.4],
            }
        ],
    )

    assert result is not None
    assert result["applied_methods"] == ["flip"]
    assert result["augmentation_ops"] == [
        {
            "method": "flip",
            "mode": "horizontal",
            "size": [10, 8],
            "transform": "HorizontalFlip",
        }
    ]
    assert result["transformed_detections"] == [
        {
            "category": "worker",
            "confidence": 0.9,
            "bbox": [0.75, 0.5, 0.2, 0.4],
        }
    ]
    assert result["augmentation_replay"]["transforms"][0]["applied"] is True
    json.dumps(result["augmentation_replay"])


def test_augmentation_preserves_and_geometrically_transforms_alpha(tmp_path: Path):
    source = Image.new("RGBA", (4, 2), color=(255, 255, 255, 255))
    source.putalpha(Image.fromarray(np.array([[0, 64, 128, 255], [0, 64, 128, 255]], dtype=np.uint8)))
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    image_storage.save_generated_image(
        str(tmp_path),
        "dataset-1",
        "image-000001",
        buffer.getvalue(),
        "image/png",
    )

    result = image_storage.augment_generated_image(
        str(tmp_path),
        "dataset-1",
        "image-000001",
        "image-000002",
        ["flip"],
        17,
        {"flip": {"mode": "horizontal"}},
    )

    assert result is not None
    with Image.open(result["path"]) as augmented:
        assert augmented.mode == "RGBA"
        assert list(augmented.getchannel("A").getdata()) == [255, 128, 64, 0, 255, 128, 64, 0]


def test_occlusion_filter_drops_boxes_that_are_no_longer_visible():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.5, 0.5, 0.4, 0.4]}]
    visibility_mask = np.ones((100, 100), dtype=np.uint8)
    visibility_mask[30:70, 30:70] = 0

    assert image_storage._filter_occluded_detections(detections, visibility_mask) == []
