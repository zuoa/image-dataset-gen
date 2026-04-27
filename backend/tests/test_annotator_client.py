import json
import importlib.util
import sys
import types
from pathlib import Path

from PIL import Image


def _load_annotator_client_module():
    app_module = types.ModuleType("app")
    models_module = types.ModuleType("app.models")
    services_module = types.ModuleType("app.services")
    image_storage_module = types.ModuleType("app.services.image_storage")

    class Dataset:  # pragma: no cover - used only as an import stub
        pass

    models_module.Dataset = Dataset
    image_storage_module.existing_generated_image = lambda *args, **kwargs: None

    sys.modules.setdefault("app", app_module)
    sys.modules["app.models"] = models_module
    sys.modules["app.services"] = services_module
    sys.modules["app.services.image_storage"] = image_storage_module

    module_path = Path(__file__).resolve().parents[1] / "app" / "clients" / "annotator_client.py"
    spec = importlib.util.spec_from_file_location("annotator_client_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


annotator_client = _load_annotator_client_module()


def test_build_vl_prompt_uses_qwen_friendly_object_wrapper_and_tight_box_rules():
    prompt = annotator_client._build_vl_prompt(
        "street pedestrian dataset",
        ["pedestrian", "umbrella"],
        "night rain crosswalk with multiple pedestrians and reflective road surface " * 5,
        img_w=1024,
        img_h=1024,
        provider="openai_compatible",
        target_category="pedestrian",
    )

    assert '{"detections": [{"bbox_2d": [x1, y1, x2, y2]' in prompt
    assert "Never use one large box to cover multiple nearby objects." in prompt
    assert "Only return detections whose label matches 'pedestrian'." in prompt
    assert prompt.count("night rain crosswalk") < 5


def test_build_vl_prompt_uses_bbox_2d_for_gemini_outputs_too():
    prompt = annotator_client._build_vl_prompt(
        "street pedestrian dataset",
        ["pedestrian"],
        "single pedestrian crossing the street",
        img_w=1280,
        img_h=720,
        provider="gemini",
    )

    assert '{"detections": [{"bbox_2d": [x1, y1, x2, y2]' in prompt
    assert "Image dimensions: 1280 x 720 pixels." in prompt
    assert "[x1, y1] is the top-left corner" in prompt


def test_parse_vl_response_accepts_bbox_2d_without_confidence():
    raw = json.dumps(
        {
            "detections": [
                {
                    "bbox_2d": [10, 20, 110, 220],
                    "label": "Pedestrian",
                }
            ]
        }
    )

    detections = annotator_client._parse_vl_response(raw, 0.5, {"pedestrian"}, 200, 400)

    assert detections == [
        {
            "category": "pedestrian",
            "confidence": 1.0,
            "bbox": [0.3, 0.3, 0.5, 0.5],
        }
    ]


def test_merge_detections_prefers_tighter_box_when_confidence_is_close():
    merged = annotator_client._merge_detections(
        [
            {
                "category": "pedestrian",
                "confidence": 0.91,
                "bbox": [0.5, 0.5, 0.4, 0.4],
            },
            {
                "category": "pedestrian",
                "confidence": 0.89,
                "bbox": [0.5, 0.5, 0.36, 0.36],
            },
        ]
    )

    assert merged == [
        {
            "category": "pedestrian",
            "confidence": 0.89,
            "bbox": [0.5, 0.5, 0.36, 0.36],
        }
    ]


def test_tighten_single_detection_maps_crop_result_back_to_image(monkeypatch):
    monkeypatch.setattr(
        annotator_client,
        "_call_vl_model",
        lambda *args, **kwargs: json.dumps(
            {
                "detections": [
                    {
                        "bbox_2d": [32, 28, 96, 100],
                        "label": "pedestrian",
                        "confidence": 0.93,
                    }
                ]
            }
        ),
    )

    image = Image.new("RGB", (200, 200), color="white")
    tightened = annotator_client._tighten_single_detection(
        provider="openai_compatible",
        model="Qwen2.5-VL-7B-Instruct",
        api_key="demo",
        base_url="http://example.com/v1",
        pil_img=image,
        detection={
            "category": "pedestrian",
            "confidence": 0.88,
            "bbox": [0.5, 0.5, 0.4, 0.4],
        },
        img_w=200,
        img_h=200,
    )

    assert tightened["category"] == "pedestrian"
    assert tightened["confidence"] == 0.93
    assert tightened["bbox"] == [0.5, 0.5, 0.32, 0.36]
