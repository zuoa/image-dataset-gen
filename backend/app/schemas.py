from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates_schema


SUPPORTED_ASPECT_RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16")
AUGMENTATION_METHODS = (
    "flip",
    "rotate",
    "crop",
    "color_jitter",
    "blur",
    "noise",
    "occlusion",
    "perspective",
)


def _validate_aspect_ratio(value: str) -> None:
    if value not in SUPPORTED_ASPECT_RATIOS:
        raise ValidationError("aspect_ratio must be one of 1:1, 4:3, 3:4, 16:9, 9:16")


def _ensure_number(settings: dict[str, object], key: str, min_value: float, max_value: float) -> float:
    value = settings.get(key)
    if not isinstance(value, (int, float)):
        raise ValidationError({key: [f"{key} must be a number"]})
    value = float(value)
    if value < min_value or value > max_value:
        raise ValidationError({key: [f"{key} must be between {min_value} and {max_value}"]})
    return value


class RegisterSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate.Length(min=8, max=64))


class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate.Length(min=8, max=64))


class ModelProfileSchema(Schema):
    profileType = fields.String(required=True, validate=validate.OneOf(["image", "llm"]))
    name = fields.String(required=True, validate=validate.Length(min=1, max=120))
    providerId = fields.String(required=True, validate=validate.Length(min=1, max=64))
    baseUrl = fields.String(load_default="", allow_none=True, validate=validate.Length(max=255))
    model = fields.String(required=True, validate=validate.Length(min=1, max=120))
    apiKey = fields.String(required=True, validate=validate.Length(min=8, max=255))
    concurrency = fields.Integer(required=True, validate=validate.Range(min=1, max=10))
    batchSize = fields.Integer(required=True, validate=validate.Range(min=1, max=50))
    jimengWatermark = fields.Boolean(load_default=True)
    notes = fields.String(load_default="", allow_none=True, validate=validate.Length(max=500))

    @validates_schema
    def validate_profile_type(self, data: dict, **_: object) -> None:
        profile_type = data.get("profileType")
        provider_id = data.get("providerId")
        if profile_type == "image" and provider_id not in {"gemini", "jimeng", "stability", "custom"}:
            raise ValidationError({"providerId": ["unsupported image provider"]})
        if profile_type == "llm":
            if provider_id != "openai_compatible":
                raise ValidationError({"providerId": ["llm profile must use openai_compatible provider"]})
            if not (data.get("baseUrl") or "").strip():
                raise ValidationError({"baseUrl": ["baseUrl is required for llm profiles"]})


class PromptPreviewSchema(Schema):
    subject = fields.String(required=True, validate=validate.Length(min=3, max=200))
    categories = fields.List(fields.String(), required=True, validate=validate.Length(min=1))
    image_count = fields.Integer(required=True, validate=validate.Range(min=5, max=500))
    distance = fields.String(required=True, validate=validate.OneOf(["close", "mid", "far"]))
    angle = fields.String(
        required=True, validate=validate.OneOf(["front", "side", "top", "bottom", "random"])
    )
    lighting = fields.List(fields.String(), required=True, validate=validate.Length(min=1))
    background = fields.List(fields.String(), required=True, validate=validate.Length(min=1))
    aspect_ratio = fields.String(required=True, validate=_validate_aspect_ratio)
    format = fields.String(required=True, validate=validate.OneOf(["jpg", "png"]))
    style = fields.String(
        required=True,
        validate=validate.OneOf(["realistic", "illustration", "sketch", "3d", "cartoon"]),
    )
    api_provider = fields.String(
        required=True, validate=validate.OneOf(["gemini", "jimeng", "stability", "custom"])
    )
    api_key = fields.String(load_default="", allow_none=True, validate=validate.Length(max=255))
    concurrency = fields.Integer(required=True, validate=validate.Range(min=1, max=10))
    batch_size = fields.Integer(load_default=10, validate=validate.Range(min=1, max=50))
    budget_limit = fields.Float(load_default=None, allow_none=True)
    extra_desc = fields.String(load_default="", validate=validate.Length(max=500))
    provider_model = fields.String(load_default="", allow_none=True, validate=validate.Length(max=120))
    jimeng_watermark = fields.Boolean(load_default=True)
    llm_enhanced = fields.Boolean(load_default=False)
    is_manual_edited = fields.Boolean(load_default=False)
    manual_prompt = fields.String(load_default="", allow_none=True)

    @validates_schema
    def validate_manual_prompt(self, data: dict, **_: object) -> None:
        if data.get("is_manual_edited") and not data.get("manual_prompt"):
            raise ValidationError({"manual_prompt": ["manual prompt cannot be empty"]})
        if data.get("api_provider") == "jimeng" and data.get("format") != "jpg":
            raise ValidationError({"format": ["jimeng current model only supports jpg output"]})


class TaskSchema(PromptPreviewSchema):
    api_key = fields.String(load_default="", allow_none=True, validate=validate.Length(max=255))
    status = fields.String(load_default="draft")


class TaskActionSchema(Schema):
    multiplier = fields.Integer(load_default=5, validate=validate.Range(min=1, max=20))
    augmentation_methods = fields.List(
        fields.String(validate=validate.OneOf(AUGMENTATION_METHODS)),
        load_default=["flip", "color_jitter", "blur"],
        validate=validate.Length(min=1, max=8),
    )
    augmentation_settings = fields.Dict(keys=fields.String(), values=fields.Dict(), load_default=dict)
    confidence_threshold = fields.Float(
        load_default=0.6, validate=validate.Range(min=0.3, max=0.95)
    )
    export_format = fields.String(
        load_default="yolo", validate=validate.OneOf(["yolo", "coco", "voc", "csv"])
    )
    image_format = fields.String(
        load_default="keep", validate=validate.OneOf(["keep", "jpg", "png"])
    )
    include_readme = fields.Boolean(load_default=True)

    @validates_schema
    def validate_augmentation_settings(self, data: dict, **_: object) -> None:
        settings = data.get("augmentation_settings") or {}
        if not isinstance(settings, dict):
            raise ValidationError({"augmentation_settings": ["augmentation_settings must be an object"]})

        errors: dict[str, dict[str, list[str]]] = {}
        selected_methods = set(data.get("augmentation_methods") or [])
        for method, method_settings in settings.items():
            if method not in AUGMENTATION_METHODS:
                errors[method] = {"_schema": ["unsupported augmentation method"]}
                continue
            if method not in selected_methods:
                continue
            if not isinstance(method_settings, dict):
                errors[method] = {"_schema": ["method settings must be an object"]}
                continue

            try:
                if method == "flip":
                    mode = method_settings.get("mode")
                    if mode is not None and mode not in {"random", "horizontal", "vertical"}:
                        raise ValidationError({"mode": ["mode must be random, horizontal or vertical"]})
                elif method == "rotate":
                    _ensure_number(method_settings, "max_angle", 0, 20)
                elif method == "crop":
                    min_scale = _ensure_number(method_settings, "min_scale", 0.6, 0.98)
                    max_scale = _ensure_number(method_settings, "max_scale", 0.6, 0.99)
                    if min_scale > max_scale:
                        raise ValidationError({"max_scale": ["max_scale must be greater than or equal to min_scale"]})
                elif method == "color_jitter":
                    _ensure_number(method_settings, "strength", 0, 0.4)
                elif method == "blur":
                    _ensure_number(method_settings, "max_radius", 0, 4)
                elif method == "noise":
                    _ensure_number(method_settings, "max_sigma", 0, 40)
                elif method == "occlusion":
                    min_ratio = _ensure_number(method_settings, "min_ratio", 0.05, 0.35)
                    max_ratio = _ensure_number(method_settings, "max_ratio", 0.05, 0.4)
                    if min_ratio > max_ratio:
                        raise ValidationError({"max_ratio": ["max_ratio must be greater than or equal to min_ratio"]})
                elif method == "perspective":
                    _ensure_number(method_settings, "max_warp", 0, 0.15)
            except ValidationError as exc:
                errors[method] = exc.normalized_messages()

        if errors:
            raise ValidationError({"augmentation_settings": errors})


class SubjectAssistSchema(Schema):
    subject = fields.String(required=True, validate=validate.Length(min=3, max=200))
    llmProfileId = fields.String(required=True, validate=validate.Length(min=1, max=64))


class SelectionSchema(Schema):
    mode = fields.String(
        required=True, validate=validate.OneOf(["single", "all", "none", "invert"])
    )
    image_id = fields.String(load_default="", allow_none=True)
    selected = fields.Boolean(load_default=None, allow_none=True)


class AnnotationDetectionSchema(Schema):
    category = fields.String(required=True, validate=validate.Length(min=1, max=120))
    confidence = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    bbox = fields.List(
        fields.Float(validate=validate.Range(min=0, max=1)),
        required=True,
        validate=validate.Length(equal=4),
    )

    @validates_schema
    def validate_bbox_area(self, data: dict, **_: object) -> None:
        _, _, width, height = data["bbox"]
        if width <= 0 or height <= 0:
            raise ValidationError({"bbox": ["bbox width and height must be greater than zero"]})


class AnnotationUpdateSchema(Schema):
    detections = fields.List(
        fields.Nested(AnnotationDetectionSchema),
        required=True,
        validate=validate.Length(max=50),
    )
