from __future__ import annotations

import base64
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


class InvalidMaskError(ValueError):
    pass


def select_prompted_component(
    mask: np.ndarray,
    *,
    first_positive_point: tuple[float, float],
    minimum_pixels: int = 16,
) -> np.ndarray:
    binary = np.asarray(mask, dtype=np.uint8)
    if binary.ndim != 2:
        raise InvalidMaskError("mask must be two-dimensional")
    if not binary.any():
        raise InvalidMaskError("mask is empty")

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if component_count <= 1:
        raise InvalidMaskError("mask has no foreground component")

    height, width = binary.shape
    point_x = min(max(int(round(first_positive_point[0])), 0), width - 1)
    point_y = min(max(int(round(first_positive_point[1])), 0), height - 1)
    selected_label = int(labels[point_y, point_x])
    if selected_label == 0:
        selected_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))

    selected_pixels = int(stats[selected_label, cv2.CC_STAT_AREA])
    if selected_pixels < minimum_pixels:
        raise InvalidMaskError("mask component is too small")
    return labels == selected_label


def normalized_bbox_from_mask(mask: np.ndarray) -> list[float]:
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2 or not binary.any():
        raise InvalidMaskError("cannot compute a bounding box from an empty mask")

    ys, xs = np.nonzero(binary)
    image_height, image_width = binary.shape
    left = float(xs.min()) / image_width
    top = float(ys.min()) / image_height
    right = float(xs.max() + 1) / image_width
    bottom = float(ys.max() + 1) / image_height
    width = right - left
    height = bottom - top
    return [
        min(max(left + width / 2, 0.0), 1.0),
        min(max(top + height / 2, 0.0), 1.0),
        min(max(width, 0.0), 1.0),
        min(max(height, 0.0), 1.0),
    ]


def mask_png_data_url(mask: np.ndarray, *, max_dimension: int = 1024) -> str:
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise InvalidMaskError("mask must be two-dimensional")
    alpha = Image.fromarray((binary.astype(np.uint8) * 118))
    if max(alpha.size) > max_dimension:
        scale = max_dimension / max(alpha.size)
        alpha = alpha.resize(
            (max(1, round(alpha.width * scale)), max(1, round(alpha.height * scale))),
            Image.Resampling.NEAREST,
        )
    rgba = Image.new("RGBA", alpha.size, (45, 212, 191, 0))
    rgba.putalpha(alpha)
    buffer = BytesIO()
    rgba.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
