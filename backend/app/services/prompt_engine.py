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

NEGATIVE_PROMPT = (
    "blurry, low quality, watermark, text overlay, duplicate subjects, deformed anatomy"
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


def build_prompt_preview(config: dict[str, Any]) -> dict[str, Any]:
    base_prompt = (
        f'{config["subject"]}, '
        f'{DISTANCE_MAP[config["distance"]]}, '
        f'{ANGLE_MAP[config["angle"]]}, '
        f'{STYLE_MAP[config["style"]]}, '
        f'lighting: {", ".join(config["lighting"])}, '
        f'background: {", ".join(config["background"])}, '
        "high quality, professional composition, dataset-ready framing"
    )

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
