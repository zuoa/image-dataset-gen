import importlib.util
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/image_storage.py"
SPEC = importlib.util.spec_from_file_location("image_storage_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
image_storage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_storage)


def test_rotate_augmentation_uses_small_angle_range():
    image = Image.new("RGB", (32, 32), color=(255, 255, 255))
    rng = Mock()
    rng.uniform.return_value = 5.0

    rotated = image_storage._apply_augmentation(image, "rotate", rng)

    rng.uniform.assert_called_once_with(
        -image_storage.MAX_ROTATION_ANGLE_DEGREES,
        image_storage.MAX_ROTATION_ANGLE_DEGREES,
    )
    assert rotated.size == image.size


def test_rotate_augmentation_uses_custom_max_angle():
    image = Image.new("RGB", (32, 32), color=(255, 255, 255))
    rng = Mock()
    rng.uniform.return_value = 3.0

    image_storage._apply_augmentation(image, "rotate", rng, {"rotate": {"max_angle": 4.5}})

    rng.uniform.assert_called_once_with(-4.5, 4.5)


def test_flip_augmentation_honors_mode_override():
    image = Image.new("RGB", (4, 1), color=(255, 255, 255))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((3, 0), (0, 0, 255))
    rng = Mock()

    flipped = image_storage._apply_augmentation(image, "flip", rng, {"flip": {"mode": "horizontal"}})

    assert flipped.getpixel((0, 0)) == (0, 0, 255)
    assert flipped.getpixel((3, 0)) == (255, 0, 0)
