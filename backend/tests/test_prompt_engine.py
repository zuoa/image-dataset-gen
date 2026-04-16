from app.services.prompt_engine import NEGATIVE_PROMPT, build_prompt_preview

_BASE_CONFIG = {
    "subject": "industrial drone inspection",
    "categories": ["drone"],
    "image_count": 100,
    "distance": "far",
    "angle": "top",
    "lighting": ["natural"],
    "background": ["city"],
    "aspect_ratio": "1:1",
    "format": "jpg",
    "style": "realistic",
    "api_provider": "gemini",
    "api_key": "demo-key",
    "concurrency": 3,
    "extra_desc": "",
}


def test_prompt_preview_contains_variants():
    preview = build_prompt_preview(_BASE_CONFIG)

    assert preview["negative_prompt"]
    assert len(preview["variants"]) == 5
    assert "photorealistic" in preview["positive_prompt"]


def test_prompt_preview_adds_chinese_traits_for_human_subject():
    config = {
        **_BASE_CONFIG,
        "subject": "construction worker on a rainy street",
        "categories": ["worker", "helmet"],
    }
    preview = build_prompt_preview(config)

    assert "ethnically Chinese" in preview["positive_prompt"]


def test_prompt_preview_defaults_to_detection_suffix():
    preview = build_prompt_preview(_BASE_CONFIG)

    assert "training-ready detection sample" in preview["positive_prompt"]
    assert "multi-scale presence" in preview["positive_prompt"]


def test_prompt_preview_segmentation_suffix():
    config = {**_BASE_CONFIG, "cv_task": "segmentation"}
    preview = build_prompt_preview(config)

    assert "training-ready segmentation sample" in preview["positive_prompt"]
    assert "sharp edges" in preview["positive_prompt"]


def test_prompt_preview_classification_suffix():
    config = {**_BASE_CONFIG, "cv_task": "classification"}
    preview = build_prompt_preview(config)

    assert "training-ready classification sample" in preview["positive_prompt"]
    assert "single centered subject" in preview["positive_prompt"]


def test_prompt_preview_instance_segmentation_suffix():
    config = {**_BASE_CONFIG, "cv_task": "instance_segmentation"}
    preview = build_prompt_preview(config)

    assert "training-ready instance segmentation sample" in preview["positive_prompt"]
    assert "multiple instances" in preview["positive_prompt"]


def test_prompt_preview_includes_category_context():
    config = {**_BASE_CONFIG, "categories": ["pedestrian", "vehicle", "traffic_light"]}
    preview = build_prompt_preview(config)

    assert "focus on detecting pedestrian, vehicle and traffic_light" in preview["positive_prompt"]


def test_prompt_preview_single_category_context():
    config = {**_BASE_CONFIG, "categories": ["drone"]}
    preview = build_prompt_preview(config)

    assert "focus on detecting drone" in preview["positive_prompt"]


def test_prompt_preview_style_quality_suffix_realistic():
    preview = build_prompt_preview(_BASE_CONFIG)

    assert "sharp focus" in preview["positive_prompt"]


def test_prompt_preview_style_quality_suffix_surveillance():
    config = {**_BASE_CONFIG, "style": "surveillance"}
    preview = build_prompt_preview(config)

    assert "authentic footage quality" in preview["positive_prompt"]
    assert "sharp focus" not in preview["positive_prompt"]


def test_variation_pools_include_new_dimensions():
    preview = build_prompt_preview(_BASE_CONFIG)

    for variant in preview["variants"]:
        assert "occlusion" in variant["diversity_vars"]
        assert "subject_count" in variant["diversity_vars"]
        assert "background_complexity" in variant["diversity_vars"]
        assert "subject_scale" in variant["diversity_vars"]


def test_negative_prompt_is_dataset_focused():
    assert "chromatic aberration" in NEGATIVE_PROMPT
    assert "amputated limbs" in NEGATIVE_PROMPT
    assert "overexposed highlights" in NEGATIVE_PROMPT
