from app.services.prompt_engine import build_prompt_preview


def test_prompt_preview_contains_variants():
    preview = build_prompt_preview(
        {
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
    )

    assert preview["negative_prompt"]
    assert len(preview["variants"]) == 5
    assert "photorealistic" in preview["positive_prompt"]


def test_prompt_preview_adds_chinese_traits_for_human_subject():
    preview = build_prompt_preview(
        {
            "subject": "construction worker on a rainy street",
            "categories": ["worker", "helmet"],
            "image_count": 20,
            "distance": "mid",
            "angle": "front",
            "lighting": ["night"],
            "background": ["city"],
            "aspect_ratio": "1:1",
            "format": "jpg",
            "style": "realistic",
            "api_provider": "gemini",
            "api_key": "demo-key",
            "concurrency": 3,
            "extra_desc": "",
        }
    )

    assert "ethnically Chinese" in preview["positive_prompt"]
