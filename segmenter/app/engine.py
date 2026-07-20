from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

from app.geometry import mask_png_data_url, normalized_bbox_from_mask, select_prompted_component


class SegmenterError(RuntimeError):
    pass


class SegmenterSessionNotFound(SegmenterError):
    pass


@dataclass
class SegmenterSession:
    predictor: Any
    width: int
    height: int
    created_at: float
    last_accessed_at: float


class Sam2Engine:
    def __init__(
        self,
        *,
        checkpoint: str,
        model_config: str,
        model_name: str,
        session_ttl_seconds: int = 600,
        max_sessions: int = 16,
        device: str = "cuda",
    ) -> None:
        try:
            import torch
            from sam2.build_sam import build_sam2
        except ImportError as exc:
            raise SegmenterError("SAM 2 runtime dependencies are not installed") from exc

        if device.startswith("cuda") and not torch.cuda.is_available():
            raise SegmenterError("CUDA is required but no CUDA device is available")

        self._torch = torch
        self._device = device
        self._model_name = model_name
        self._session_ttl_seconds = max(1, session_ttl_seconds)
        self._max_sessions = max(1, max_sessions)
        self._sessions: OrderedDict[str, SegmenterSession] = OrderedDict()
        self._lock = threading.RLock()
        self._model = build_sam2(model_config, checkpoint, device=device)

    @property
    def model_name(self) -> str:
        return self._model_name

    def create_session(self, image_bytes: bytes) -> tuple[str, int, int, float]:
        try:
            with Image.open(BytesIO(image_bytes)) as source_image:
                max_image_pixels = int(os.getenv("SEGMENTER_MAX_IMAGE_PIXELS", "40000000"))
                if source_image.width * source_image.height > max_image_pixels:
                    raise SegmenterError("image dimensions exceed the configured pixel limit")
                image = source_image.convert("RGB")
        except SegmenterError:
            raise
        except Exception as exc:
            raise SegmenterError("invalid image payload") from exc

        from sam2.sam2_image_predictor import SAM2ImagePredictor

        predictor = SAM2ImagePredictor(self._model)
        with self._lock, self._inference_context():
            self._evict_expired_locked()
            predictor.set_image(np.asarray(image))
            now = time.monotonic()
            session_id = str(uuid.uuid4())
            self._sessions[session_id] = SegmenterSession(
                predictor=predictor,
                width=image.width,
                height=image.height,
                created_at=now,
                last_accessed_at=now,
            )
            self._evict_overflow_locked()

        expires_in = float(self._session_ttl_seconds)
        return session_id, image.width, image.height, expires_in

    def predict(self, session_id: str, points: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock, self._inference_context():
            self._evict_expired_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise SegmenterSessionNotFound("segment session not found or expired")
            session.last_accessed_at = time.monotonic()
            self._sessions.move_to_end(session_id)

            point_coordinates = np.asarray(
                [
                    [
                        float(point["x"]) * max(session.width - 1, 1),
                        float(point["y"]) * max(session.height - 1, 1),
                    ]
                    for point in points
                ],
                dtype=np.float32,
            )
            point_labels = np.asarray(
                [1 if point["label"] == "positive" else 0 for point in points],
                dtype=np.int32,
            )
            masks, scores, _ = session.predictor.predict(
                point_coords=point_coordinates,
                point_labels=point_labels,
                multimask_output=True,
            )

        best_index = int(np.argmax(scores))
        best_score = float(scores[best_index])
        if not np.isfinite(best_score):
            raise SegmenterError("segment prediction returned a non-finite mask score")
        first_positive_index = next(index for index, point in enumerate(points) if point["label"] == "positive")
        selected_mask = select_prompted_component(
            masks[best_index],
            first_positive_point=tuple(point_coordinates[first_positive_index]),
        )
        return {
            "bbox": normalized_bbox_from_mask(selected_mask),
            "maskDataUrl": mask_png_data_url(selected_mask),
            "maskScore": min(max(best_score, 0.0), 1.0),
        }

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            if self._sessions.pop(session_id, None) is None:
                raise SegmenterSessionNotFound("segment session not found or expired")

    def _inference_context(self):
        if self._device.startswith("cuda"):
            return _CombinedContext(
                self._torch.inference_mode(),
                self._torch.autocast("cuda", dtype=self._torch.bfloat16),
            )
        return self._torch.inference_mode()

    def _evict_expired_locked(self) -> None:
        cutoff = time.monotonic() - self._session_ttl_seconds
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.last_accessed_at < cutoff
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def _evict_overflow_locked(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)


class _CombinedContext:
    def __init__(self, *contexts: Any) -> None:
        self._contexts = contexts

    def __enter__(self):
        for context in self._contexts:
            context.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        suppress = False
        for context in reversed(self._contexts):
            suppress = context.__exit__(exc_type, exc_value, traceback) or suppress
        return suppress


def build_engine_from_environment() -> Sam2Engine:
    return Sam2Engine(
        checkpoint=os.getenv("SEGMENTER_CHECKPOINT", "/opt/models/sam2.1_hiera_small.pt"),
        model_config=os.getenv(
            "SEGMENTER_MODEL_CONFIG",
            "configs/sam2.1/sam2.1_hiera_s.yaml",
        ),
        model_name=os.getenv("SEGMENTER_MODEL_NAME", "sam2.1_hiera_small"),
        session_ttl_seconds=int(os.getenv("SEGMENTER_SESSION_TTL_SECONDS", "600")),
        max_sessions=int(os.getenv("SEGMENTER_MAX_SESSIONS", "16")),
        device=os.getenv("SEGMENTER_DEVICE", "cuda"),
    )
