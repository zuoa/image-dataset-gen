from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

CENTER_BBOX_SEMANTICS = "center_size"
LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS = "left_bottom_size_legacy"


def annotation_dir(storage_root: str, task_id: str) -> Path:
    path = Path(storage_root) / "annotations" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotation_path(storage_root: str, task_id: str, image_id: str) -> Path:
    return annotation_dir(storage_root, task_id) / f"{image_id}.json"


def save_annotation_result(
    storage_root: str,
    task_id: str,
    image_id: str,
    detections: list[dict[str, Any]],
    *,
    bbox_semantics: str = CENTER_BBOX_SEMANTICS,
) -> None:
    annotation_path(storage_root, task_id, image_id).write_text(
        json.dumps(
            {
                "bboxSemantics": bbox_semantics,
                "detections": detections,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_annotation_result(
    storage_root: str,
    task_id: str,
    image_id: str,
    *,
    default_bbox_semantics: str | None = None,
) -> dict[str, Any] | None:
    path = annotation_path(storage_root, task_id, image_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_annotation_result(payload, default_bbox_semantics=default_bbox_semantics)


def extract_detection_categories(
    storage_root: str,
    task_id: str,
    image_id: str,
) -> list[str]:
    result = load_annotation_result(storage_root, task_id, image_id)
    if not result:
        return []
    return sorted(
        {
            str(detection["category"])
            for detection in result.get("detections", [])
            if detection.get("category")
        }
    )


def infer_default_bbox_semantics(annotation_summary: dict[str, Any] | None) -> str:
    summary = annotation_summary or {}
    if summary.get("provider") != "vl-auto":
        return CENTER_BBOX_SEMANTICS

    # Historic Gemini VL auto-annotations were stored as [left, bottom, width, height].
    vl_provider = str(summary.get("vlProvider") or "gemini")
    if vl_provider == "gemini":
        return LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS
    return CENTER_BBOX_SEMANTICS


def normalize_annotation_result(
    payload: dict[str, Any],
    *,
    default_bbox_semantics: str | None = None,
) -> dict[str, Any]:
    semantics = str(payload.get("bboxSemantics") or default_bbox_semantics or CENTER_BBOX_SEMANTICS)
    detections = payload.get("detections", [])
    if semantics == LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS:
        detections = [_legacy_left_bottom_detection_to_center(detection) for detection in detections]
        semantics = CENTER_BBOX_SEMANTICS
    return {
        **payload,
        "bboxSemantics": semantics,
        "detections": detections,
    }


def transform_detections_for_augmentation(
    detections: list[dict[str, Any]],
    augmentation_ops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    transformed: list[dict[str, Any]] = []
    for detection in detections:
        bbox = detection.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            current_bbox = [float(value) for value in bbox]
        except (TypeError, ValueError):
            continue

        for op in augmentation_ops:
            next_bbox = _transform_bbox_for_op(current_bbox, op)
            if next_bbox is None:
                current_bbox = []
                break
            current_bbox = next_bbox

        if current_bbox:
            transformed.append({**detection, "bbox": current_bbox})
    return transformed


def _legacy_left_bottom_detection_to_center(detection: dict[str, Any]) -> dict[str, Any]:
    bbox = detection.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return detection
    try:
        left, bottom, width, height = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return detection
    return {
        **detection,
        "bbox": _clip_bbox(left + width / 2, bottom - height / 2, width, height),
    }


def _clip_bbox(x_center: float, y_center: float, width: float, height: float) -> list[float]:
    width = min(max(width, 0.001), 1.0)
    height = min(max(height, 0.001), 1.0)
    x_center = min(max(x_center, width / 2), 1.0 - width / 2)
    y_center = min(max(y_center, height / 2), 1.0 - height / 2)
    return [round(x_center, 4), round(y_center, 4), round(width, 4), round(height, 4)]


def _transform_bbox_for_op(bbox: list[float], op: dict[str, Any]) -> list[float] | None:
    method = str(op.get("method") or "")
    width, height = _op_size(op)
    if width <= 0 or height <= 0:
        return bbox

    if method == "flip":
        left, top, right, bottom = _bbox_to_pixel_bounds(bbox, width, height)
        if op.get("mode") == "horizontal":
            return _bbox_from_pixel_bounds(width - right, top, width - left, bottom, width, height)
        if op.get("mode") == "vertical":
            return _bbox_from_pixel_bounds(left, height - bottom, right, height - top, width, height)
        return bbox

    if method == "crop":
        crop = op.get("crop")
        if not isinstance(crop, list) or len(crop) != 4:
            return bbox
        try:
            crop_left, crop_top, crop_right, crop_bottom = [float(value) for value in crop]
        except (TypeError, ValueError):
            return bbox
        crop_width = crop_right - crop_left
        crop_height = crop_bottom - crop_top
        if crop_width <= 0 or crop_height <= 0:
            return None

        left, top, right, bottom = _bbox_to_pixel_bounds(bbox, width, height)
        clipped_left = max(left, crop_left)
        clipped_top = max(top, crop_top)
        clipped_right = min(right, crop_right)
        clipped_bottom = min(bottom, crop_bottom)
        if clipped_right <= clipped_left or clipped_bottom <= clipped_top:
            return None

        return _bbox_from_pixel_bounds(
            (clipped_left - crop_left) * width / crop_width,
            (clipped_top - crop_top) * height / crop_height,
            (clipped_right - crop_left) * width / crop_width,
            (clipped_bottom - crop_top) * height / crop_height,
            width,
            height,
        )

    if method == "rotate":
        angle = float(op.get("angle") or 0.0)
        polygon = _bbox_to_pixel_polygon(bbox, width, height)
        transformed = [_rotate_point(point, angle, width / 2, height / 2) for point in polygon]
        clipped = _clip_polygon_to_rect(transformed, width, height)
        return _bbox_from_polygon(clipped, width, height)

    if method == "perspective":
        quad = op.get("quad")
        if not isinstance(quad, list) or len(quad) != 8:
            return bbox
        try:
            values = [float(value) for value in quad]
        except (TypeError, ValueError):
            return bbox
        source_quad = [
            (values[0], values[1]),
            (values[2], values[3]),
            (values[4], values[5]),
            (values[6], values[7]),
        ]
        clipped = _clip_polygon_to_convex_polygon(_bbox_to_pixel_polygon(bbox, width, height), source_quad)
        if not clipped:
            return None
        transformed = [
            transformed_point
            for point in clipped
            if (transformed_point := _inverse_quad_point(point, source_quad, width, height)) is not None
        ]
        return _bbox_from_polygon(transformed, width, height)

    return bbox


def _op_size(op: dict[str, Any]) -> tuple[float, float]:
    size = op.get("size")
    if not isinstance(size, list) or len(size) != 2:
        return 1.0, 1.0
    try:
        return float(size[0]), float(size[1])
    except (TypeError, ValueError):
        return 1.0, 1.0


def _bbox_to_pixel_bounds(bbox: list[float], width: float, height: float) -> tuple[float, float, float, float]:
    x_center, y_center, box_width, box_height = bbox
    left = (x_center - box_width / 2) * width
    top = (y_center - box_height / 2) * height
    right = (x_center + box_width / 2) * width
    bottom = (y_center + box_height / 2) * height
    return left, top, right, bottom


def _bbox_to_pixel_polygon(bbox: list[float], width: float, height: float) -> list[tuple[float, float]]:
    left, top, right, bottom = _bbox_to_pixel_bounds(bbox, width, height)
    return [(left, top), (right, top), (right, bottom), (left, bottom)]


def _bbox_from_pixel_bounds(
    left: float,
    top: float,
    right: float,
    bottom: float,
    width: float,
    height: float,
) -> list[float] | None:
    clipped_left = max(0.0, min(width, left))
    clipped_top = max(0.0, min(height, top))
    clipped_right = max(0.0, min(width, right))
    clipped_bottom = max(0.0, min(height, bottom))
    if clipped_right <= clipped_left or clipped_bottom <= clipped_top:
        return None

    box_width = (clipped_right - clipped_left) / width
    box_height = (clipped_bottom - clipped_top) / height
    x_center = (clipped_left + clipped_right) / 2 / width
    y_center = (clipped_top + clipped_bottom) / 2 / height
    return _clip_bbox(x_center, y_center, box_width, box_height)


def _bbox_from_polygon(
    polygon: list[tuple[float, float]],
    width: float,
    height: float,
) -> list[float] | None:
    if not polygon:
        return None
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return _bbox_from_pixel_bounds(min(xs), min(ys), max(xs), max(ys), width, height)


def _rotate_point(point: tuple[float, float], angle: float, cx: float, cy: float) -> tuple[float, float]:
    radians = math.radians(angle)
    cos_value = math.cos(radians)
    sin_value = math.sin(radians)
    dx = point[0] - cx
    dy = point[1] - cy
    return cx + cos_value * dx + sin_value * dy, cy - sin_value * dx + cos_value * dy


def _clip_polygon_to_rect(
    polygon: list[tuple[float, float]],
    width: float,
    height: float,
) -> list[tuple[float, float]]:
    clipped = polygon
    for inside, intersect in (
        (lambda point: point[0] >= 0.0, lambda start, end: _intersect_vertical(start, end, 0.0)),
        (lambda point: point[0] <= width, lambda start, end: _intersect_vertical(start, end, width)),
        (lambda point: point[1] >= 0.0, lambda start, end: _intersect_horizontal(start, end, 0.0)),
        (lambda point: point[1] <= height, lambda start, end: _intersect_horizontal(start, end, height)),
    ):
        clipped = _clip_polygon_edge(clipped, inside, intersect)
        if not clipped:
            return []
    return clipped


def _clip_polygon_to_convex_polygon(
    polygon: list[tuple[float, float]],
    clip_polygon: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not polygon or len(clip_polygon) < 3:
        return []

    orientation = 1.0 if _polygon_signed_area(clip_polygon) >= 0 else -1.0
    clipped = polygon
    for index, start in enumerate(clip_polygon):
        end = clip_polygon[(index + 1) % len(clip_polygon)]
        clipped = _clip_polygon_edge(
            clipped,
            lambda point, start=start, end=end: orientation * _cross(start, end, point) >= -1e-9,
            lambda line_start, line_end, start=start, end=end: _intersect_lines(
                line_start,
                line_end,
                start,
                end,
            ),
        )
        if not clipped:
            return []
    return clipped


def _clip_polygon_edge(
    polygon: list[tuple[float, float]],
    inside: Callable[[tuple[float, float]], bool],
    intersect: Callable[[tuple[float, float], tuple[float, float]], tuple[float, float]],
) -> list[tuple[float, float]]:
    if not polygon:
        return []

    output: list[tuple[float, float]] = []
    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                output.append(intersect(previous, current))
            output.append(current)
        elif previous_inside:
            output.append(intersect(previous, current))
        previous = current
        previous_inside = current_inside
    return output


def _intersect_vertical(
    start: tuple[float, float],
    end: tuple[float, float],
    x: float,
) -> tuple[float, float]:
    dx = end[0] - start[0]
    if abs(dx) < 1e-12:
        return x, start[1]
    ratio = (x - start[0]) / dx
    return x, start[1] + ratio * (end[1] - start[1])


def _intersect_horizontal(
    start: tuple[float, float],
    end: tuple[float, float],
    y: float,
) -> tuple[float, float]:
    dy = end[1] - start[1]
    if abs(dy) < 1e-12:
        return start[0], y
    ratio = (y - start[1]) / dy
    return start[0] + ratio * (end[0] - start[0]), y


def _polygon_signed_area(polygon: list[tuple[float, float]]) -> float:
    area = 0.0
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return area / 2.0


def _cross(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])


def _intersect_lines(
    segment_start: tuple[float, float],
    segment_end: tuple[float, float],
    clip_start: tuple[float, float],
    clip_end: tuple[float, float],
) -> tuple[float, float]:
    segment_dx = segment_end[0] - segment_start[0]
    segment_dy = segment_end[1] - segment_start[1]
    clip_dx = clip_end[0] - clip_start[0]
    clip_dy = clip_end[1] - clip_start[1]
    denominator = segment_dx * clip_dy - segment_dy * clip_dx
    if abs(denominator) < 1e-12:
        return segment_end
    ratio = (
        (clip_start[0] - segment_start[0]) * clip_dy
        - (clip_start[1] - segment_start[1]) * clip_dx
    ) / denominator
    return segment_start[0] + ratio * segment_dx, segment_start[1] + ratio * segment_dy


def _inverse_quad_point(
    point: tuple[float, float],
    source_quad: list[tuple[float, float]],
    width: float,
    height: float,
) -> tuple[float, float] | None:
    nw, sw, se, ne = source_quad
    ax = ne[0] - nw[0]
    ay = ne[1] - nw[1]
    bx = sw[0] - nw[0]
    by = sw[1] - nw[1]
    cx = se[0] - sw[0] - ne[0] + nw[0]
    cy = se[1] - sw[1] - ne[1] + nw[1]

    s, t = _initial_quad_inverse_guess(point, nw, (ax, ay), (bx, by))
    for _ in range(20):
        mapped_x = nw[0] + ax * s + bx * t + cx * s * t
        mapped_y = nw[1] + ay * s + by * t + cy * s * t
        error_x = mapped_x - point[0]
        error_y = mapped_y - point[1]
        if abs(error_x) + abs(error_y) < 1e-7:
            break

        dx_ds = ax + cx * t
        dx_dt = bx + cx * s
        dy_ds = ay + cy * t
        dy_dt = by + cy * s
        determinant = dx_ds * dy_dt - dx_dt * dy_ds
        if abs(determinant) < 1e-12:
            return None

        delta_s = (error_x * dy_dt - dx_dt * error_y) / determinant
        delta_t = (dx_ds * error_y - error_x * dy_ds) / determinant
        s -= delta_s
        t -= delta_t

    if not math.isfinite(s) or not math.isfinite(t):
        return None
    return max(0.0, min(1.0, s)) * width, max(0.0, min(1.0, t)) * height


def _initial_quad_inverse_guess(
    point: tuple[float, float],
    origin: tuple[float, float],
    s_axis: tuple[float, float],
    t_axis: tuple[float, float],
) -> tuple[float, float]:
    px = point[0] - origin[0]
    py = point[1] - origin[1]
    determinant = s_axis[0] * t_axis[1] - t_axis[0] * s_axis[1]
    if abs(determinant) < 1e-12:
        return 0.5, 0.5
    s = (px * t_axis[1] - t_axis[0] * py) / determinant
    t = (s_axis[0] * py - px * s_axis[1]) / determinant
    return max(0.0, min(1.0, s)), max(0.0, min(1.0, t))
