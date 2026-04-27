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
