import importlib.util
from pathlib import Path


def _load_annotation_storage_module():
    module_path = Path(__file__).resolve().parents[1] / "app" / "services" / "annotation_storage.py"
    spec = importlib.util.spec_from_file_location("annotation_storage_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


annotation_storage = _load_annotation_storage_module()


def test_load_annotation_result_converts_legacy_left_bottom_boxes(tmp_path):
    annotation_storage.save_annotation_result(
        str(tmp_path),
        "dataset-1",
        "image-1",
        [{"category": "worker", "confidence": 0.9, "bbox": [0.2, 0.8, 0.3, 0.4]}],
        bbox_semantics=annotation_storage.LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS,
    )

    result = annotation_storage.load_annotation_result(str(tmp_path), "dataset-1", "image-1")

    assert result == {
        "bboxSemantics": annotation_storage.CENTER_BBOX_SEMANTICS,
        "detections": [
            {
                "category": "worker",
                "confidence": 0.9,
                "bbox": [0.35, 0.6, 0.3, 0.4],
            }
        ],
    }


def test_load_annotation_result_uses_legacy_default_for_unlabeled_gemini_annotations(tmp_path):
    path = tmp_path / "annotations" / "dataset-1"
    path.mkdir(parents=True)
    (path / "image-1.json").write_text(
        '{"detections": [{"category": "worker", "confidence": 0.9, "bbox": [0.2, 0.8, 0.3, 0.4]}]}',
        encoding="utf-8",
    )

    result = annotation_storage.load_annotation_result(
        str(tmp_path),
        "dataset-1",
        "image-1",
        default_bbox_semantics=annotation_storage.infer_default_bbox_semantics({"provider": "vl-auto"}),
    )

    assert result == {
        "bboxSemantics": annotation_storage.CENTER_BBOX_SEMANTICS,
        "detections": [
            {
                "category": "worker",
                "confidence": 0.9,
                "bbox": [0.35, 0.6, 0.3, 0.4],
            }
        ],
    }


def test_infer_default_bbox_semantics_keeps_non_gemini_vl_center_based():
    assert annotation_storage.infer_default_bbox_semantics(
        {"provider": "vl-auto", "vlProvider": "openai_compatible"}
    ) == annotation_storage.CENTER_BBOX_SEMANTICS
    assert annotation_storage.infer_default_bbox_semantics(
        {"provider": "local-fallback"}
    ) == annotation_storage.CENTER_BBOX_SEMANTICS


def test_transform_detections_for_horizontal_flip():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.25, 0.4, 0.2, 0.3]}]

    result = annotation_storage.transform_detections_for_augmentation(
        detections,
        [{"method": "flip", "mode": "horizontal", "size": [100, 100]}],
    )

    assert result[0]["bbox"] == [0.75, 0.4, 0.2, 0.3]


def test_transform_detections_for_crop_clips_to_visible_area():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.15, 0.5, 0.2, 0.4]}]

    result = annotation_storage.transform_detections_for_augmentation(
        detections,
        [{"method": "crop", "crop": [20, 20, 80, 80], "size": [100, 100]}],
    )

    assert result[0]["bbox"] == [0.0417, 0.5, 0.0833, 0.6667]


def test_transform_detections_drops_box_outside_crop():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.1, 0.1, 0.1, 0.1]}]

    result = annotation_storage.transform_detections_for_augmentation(
        detections,
        [{"method": "crop", "crop": [50, 50, 90, 90], "size": [100, 100]}],
    )

    assert result == []


def test_transform_detections_for_right_angle_rotation():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.25, 0.5, 0.2, 0.4]}]

    result = annotation_storage.transform_detections_for_augmentation(
        detections,
        [{"method": "rotate", "angle": 90, "size": [100, 100]}],
    )

    assert result[0]["bbox"] == [0.5, 0.75, 0.4, 0.2]


def test_transform_detections_for_perspective_matches_pil_quad_mapping():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.5, 0.5, 0.3, 0.4]}]

    result = annotation_storage.transform_detections_for_augmentation(
        detections,
        [{"method": "perspective", "quad": [10, 0, 0, 100, 100, 100, 90, 0], "size": [100, 100]}],
    )

    assert result[0]["bbox"] == [0.5, 0.5, 0.3488, 0.4]


def test_transform_detections_keeps_visual_only_ops_unchanged():
    detections = [{"category": "worker", "confidence": 0.9, "bbox": [0.5, 0.5, 0.3, 0.4]}]

    result = annotation_storage.transform_detections_for_augmentation(
        detections,
        [{"method": "blur", "radius": 1.4, "size": [100, 100], "geometry": "none"}],
    )

    assert result == detections
