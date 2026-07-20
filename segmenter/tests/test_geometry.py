import base64

import numpy as np
import pytest

from app.geometry import (
    InvalidMaskError,
    mask_png_data_url,
    normalized_bbox_from_mask,
    select_prompted_component,
)


def test_selects_component_containing_first_positive_point():
    mask = np.zeros((10, 20), dtype=bool)
    mask[1:5, 1:6] = True
    mask[3:9, 12:19] = True

    selected = select_prompted_component(
        mask,
        first_positive_point=(3, 2),
        minimum_pixels=1,
    )

    assert selected[2, 3]
    assert not selected[5, 15]
    assert normalized_bbox_from_mask(selected) == pytest.approx([0.175, 0.3, 0.25, 0.4])


def test_falls_back_to_largest_component_when_point_is_background():
    mask = np.zeros((10, 20), dtype=bool)
    mask[1:3, 1:3] = True
    mask[3:9, 12:19] = True

    selected = select_prompted_component(
        mask,
        first_positive_point=(8, 8),
        minimum_pixels=1,
    )

    assert not selected[1, 1]
    assert selected[5, 15]


def test_rejects_empty_or_tiny_masks():
    with pytest.raises(InvalidMaskError):
        select_prompted_component(
            np.zeros((10, 10), dtype=bool),
            first_positive_point=(1, 1),
        )

    tiny = np.zeros((10, 10), dtype=bool)
    tiny[1:3, 1:3] = True
    with pytest.raises(InvalidMaskError):
        select_prompted_component(tiny, first_positive_point=(1, 1))


def test_mask_png_is_an_embeddable_data_url():
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    data_url = mask_png_data_url(mask)
    prefix, encoded = data_url.split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded).startswith(b"\x89PNG")
