from __future__ import annotations

import hashlib
import random
from typing import Any


DISTANCE_MAP = {
    "close": "close-up shot, subject fills most of the frame",
    "mid": "medium shot, balanced subject and context",
    "far": "wide establishing shot, subject small in the scene",
}

ANGLE_MAP = {
    "front": "front view",
    "side": "side view",
    "top": "top-down perspective",
    "bottom": "low angle perspective",
    "random": "dynamic camera perspective",
}

STYLE_MAP = {
    "realistic": "photorealistic, DSLR photo, sharp focus, 8k detail",
    "illustration": "digital illustration, concept art, clean forms",
    "sketch": "pencil sketch, monochrome texture, hand-drawn lines",
    "3d": "3D render, ray tracing, studio material realism",
    "cartoon": "cartoon style, bold outlines, graphic shapes",
    "surveillance": "CCTV surveillance footage, grainy texture, wide angle lens, low resolution, timestamp overlay, security camera perspective",
}

PROVIDER_LANGUAGE = {
    "gemini": "en",
    "jimeng": "zh",
    "stability": "en",
    "custom": "en",
}

PROVIDER_RATE = {
    "gemini": 0.045,
    "jimeng": 0.028,
    "stability": 0.032,
    "custom": 0.04,
}

CV_TASK_MAP = {
    "detection": "subject clearly visible, multi-scale presence, multi-position placement, partial occlusion possible, training-ready detection sample",
    "segmentation": "clear subject-background boundary, sharp edges, distinct pixel-level contours, training-ready segmentation sample",
    "classification": "single centered subject, clean uncluttered background, unambiguous class identity, training-ready classification sample",
    "instance_segmentation": "multiple instances with varying overlap, clear individual contours, distinguishable overlapping subjects, training-ready instance segmentation sample",
}

STYLE_QUALITY_SUFFIX = {
    "realistic": "high quality, sharp focus, dataset-ready framing",
    "illustration": "clean lines, consistent style, dataset-ready framing",
    "sketch": "clear strokes, consistent line weight, dataset-ready framing",
    "3d": "clean render, studio quality, dataset-ready framing",
    "cartoon": "bold outlines, consistent style, dataset-ready framing",
    "surveillance": "authentic footage quality, realistic noise pattern, dataset-ready framing",
}

NEGATIVE_PROMPT = (
    "blurry, out of focus, low resolution, watermark, text overlay, logo stamp, "
    "duplicate subjects, deformed anatomy, amputated limbs, extra fingers, "
    "mutated proportions, heavy motion blur, chromatic aberration, "
    "overexposed highlights, completely dark silhouette, misaligned composition"
)

VARIATION_POOLS = {
    "timeOfDay": ["golden hour", "midday sun", "overcast light", "dusk", "dawn"],
    "weather": ["clear sky", "light clouds", "foggy air", "rainy mood", "snowy atmosphere"],
    "lens": [
        "shallow depth of field",
        "bokeh background",
        "wide angle lens",
        "telephoto compression",
        "high contrast finish",
    ],
    "composition": [
        "rule of thirds",
        "centered composition",
        "leading lines",
        "symmetrical layout",
        "diagonal composition",
    ],
    "occlusion": [
        "fully visible subject",
        "lightly occluded subject",
        "heavily occluded subject",
    ],
    "subject_count": [
        "single isolated subject",
        "few subjects 2 to 5",
        "dense crowd more than 5",
    ],
    "background_complexity": [
        "clean minimal background",
        "moderate background detail",
        "cluttered complex background",
    ],
    "subject_scale": [
        "large prominent subject",
        "medium balanced subject",
        "small distant subject",
    ],
}

HUMAN_KEYWORDS = {
    "person",
    "people",
    "human",
    "man",
    "woman",
    "boy",
    "girl",
    "adult",
    "child",
    "worker",
    "pedestrian",
    "driver",
    "student",
    "teacher",
    "doctor",
    "nurse",
    "police",
    "citizen",
    "face",
    "portrait",
    "人物",
    "人像",
    "中国人",
    "男人",
    "女人",
    "男孩",
    "女孩",
    "行人",
    "工人",
    "司机",
    "学生",
    "老师",
    "医生",
    "护士",
    "警察",
}


def estimate_cost(config: dict[str, Any]) -> float:
    unit_price = PROVIDER_RATE.get(config["api_provider"], PROVIDER_RATE["custom"])
    return round(unit_price * config["image_count"], 2)


def _build_category_context(categories: list[str]) -> str:
    if not categories:
        return ""
    if len(categories) == 1:
        return f"focus on detecting {categories[0]}"
    first_items = ", ".join(categories[:-1])
    return f"focus on detecting {first_items} and {categories[-1]}"


def build_prompt_preview(config: dict[str, Any]) -> dict[str, Any]:
    style = config["style"]
    cv_task = config.get("cv_task") or "detection"
    quality_suffix = STYLE_QUALITY_SUFFIX.get(style, STYLE_QUALITY_SUFFIX["realistic"])
    cv_suffix = CV_TASK_MAP.get(cv_task, CV_TASK_MAP["detection"])
    category_context = _build_category_context(config.get("categories", []))

    parts = [
        config["subject"],
        DISTANCE_MAP[config["distance"]],
        ANGLE_MAP[config["angle"]],
        STYLE_MAP[style],
        f'lighting: {", ".join(config["lighting"])}',
        f'background: {", ".join(config["background"])}',
        quality_suffix,
        cv_suffix,
    ]
    if category_context:
        parts.append(category_context)

    base_prompt = ", ".join(parts)

    if requires_chinese_human_traits(config):
        base_prompt = (
            f"{base_prompt}, portray the human subject as ethnically Chinese with natural Chinese facial features"
        )

    if config.get("extra_desc"):
        base_prompt = f"{base_prompt}, extra context: {config['extra_desc']}"

    language = PROVIDER_LANGUAGE.get(config["api_provider"], "en")
    manual_prompt = config.get("manual_prompt") if config.get("is_manual_edited") else None

    variants = generate_prompt_variants(config, base_prompt, 5)

    return {
        "positive_prompt": manual_prompt or base_prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "variants": variants,
        "language": language,
        "estimated_cost": estimate_cost(config),
        "token_safe": len((manual_prompt or base_prompt).split()) < 120,
    }


def requires_chinese_human_traits(config: dict[str, Any]) -> bool:
    values = [
        str(config.get("subject", "")),
        str(config.get("extra_desc", "")),
        " ".join(str(item) for item in config.get("categories", [])),
    ]
    haystack = " ".join(values).lower()
    return any(keyword in haystack for keyword in HUMAN_KEYWORDS)


def generate_prompt_variants(
    config: dict[str, Any], base_prompt: str, count: int
) -> list[dict[str, Any]]:
    seed_source = "|".join(
        [
            config["subject"],
            ",".join(config["categories"]),
            config["distance"],
            config["angle"],
            config["style"],
        ]
    )
    seed = int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest(), 16) % (10**8)
    generator = random.Random(seed)
    variants: list[dict[str, Any]] = []
    used_signatures: set[str] = set()

    while len(variants) < count:
        diversity_vars = {
            key: generator.choice(values)
            for key, values in VARIATION_POOLS.items()
        }
        signature = "|".join(diversity_vars.values())
        if signature in used_signatures:
            continue
        used_signatures.add(signature)
        prompt = f"{base_prompt}, " + ", ".join(diversity_vars.values())
        variants.append(
            {
                "seed": generator.randint(100000, 999999),
                "diversity_vars": diversity_vars,
                "prompt": prompt,
            }
        )

    return variants
