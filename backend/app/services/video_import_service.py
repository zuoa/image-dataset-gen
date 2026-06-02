from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import shutil

from PIL import Image
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DEFAULT_VIDEO_FRAME_INTERVAL = 30
DEFAULT_VIDEO_FRAME_INTERVAL_MODE = "frames"
DEFAULT_VIDEO_FRAME_INTERVAL_SECONDS = 1.0
DEFAULT_VIDEO_OUTPUT_FORMAT = "jpg"
DEFAULT_VIDEO_JPEG_QUALITY = 95
DEFAULT_VIDEO_FILENAME_PREFIX = "frame"
DEFAULT_VIDEO_TARGET_SIZE = "original"
VIDEO_TARGET_SIZE_MAX_DIMENSIONS = {
    "original": None,
    "1080p": 1080,
    "720p": 720,
    "640": 640,
}


@dataclass(frozen=True)
class ExtractedVideoFrame:
    source_frame_index: int
    source_ordinal: int
    output_filename: str
    image_bytes: bytes
    mime_type: str


def is_allowed_video_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_VIDEO_EXTENSIONS


def sanitize_filename_prefix(value: str | None) -> str:
    raw = (value or "").strip() or DEFAULT_VIDEO_FILENAME_PREFIX
    sanitized = "".join(char for char in raw if char.isalnum() or char in {"_", "-"}).strip("_-")
    return sanitized or DEFAULT_VIDEO_FILENAME_PREFIX


def normalize_video_target_size(value: str | None) -> str:
    normalized = (value or DEFAULT_VIDEO_TARGET_SIZE).strip().lower()
    return normalized if normalized in VIDEO_TARGET_SIZE_MAX_DIMENSIONS else DEFAULT_VIDEO_TARGET_SIZE


def normalize_video_frame_interval_mode(value: str | None) -> str:
    normalized = (value or DEFAULT_VIDEO_FRAME_INTERVAL_MODE).strip().lower()
    return "seconds" if normalized == "seconds" else DEFAULT_VIDEO_FRAME_INTERVAL_MODE


def video_target_size_max_dimension(value: str | None) -> int | None:
    return VIDEO_TARGET_SIZE_MAX_DIMENSIONS[normalize_video_target_size(value)]


def save_video_import_source(storage_root: str, task_id: str, upload: FileStorage) -> str:
    source_dir = Path(storage_root) / "import_sources" / task_id
    source_dir.mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(upload.filename or "source-video")
    if not safe_name:
        safe_name = "source-video"
    source_path = source_dir / safe_name
    upload.save(source_path)
    return str(source_path.relative_to(storage_root))


def resolve_video_import_source(storage_root: str, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("missing video source path")
    storage_path = Path(storage_root).resolve()
    source_path = (storage_path / relative_path).resolve()
    source_path.relative_to(storage_path / "import_sources")
    return source_path


def cleanup_video_import_source(storage_root: str, relative_path: str) -> None:
    try:
        source_path = resolve_video_import_source(storage_root, relative_path)
    except ValueError:
        return
    source_dir = source_path.parent
    import_sources_dir = (Path(storage_root).resolve() / "import_sources").resolve()
    if source_dir.exists() and source_dir.parent == import_sources_dir:
        shutil.rmtree(source_dir, ignore_errors=True)


def iter_video_frames(
    source_path: Path,
    *,
    frame_interval: int,
    output_format: str,
    jpeg_quality: int,
    filename_prefix: str,
    max_images: int,
    target_max_dimension: int | None = None,
    skip_selected_frames: int = 0,
):
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("后端尚未安装视频抽帧依赖 opencv-python-headless。") from exc

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError("无法读取上传的视频文件。")

    selected_count = 0
    frame_index = 0
    frame_interval = max(1, int(frame_interval))
    max_images = max(1, int(max_images))

    try:
        while selected_count < max_images:
            success, frame = capture.read()
            if not success:
                break

            if frame_index % frame_interval == 0:
                source_ordinal = selected_count + 1
                if selected_count >= skip_selected_frames:
                    yield _encode_frame(
                        frame,
                        source_frame_index=frame_index,
                        source_ordinal=source_ordinal,
                        output_format=output_format,
                        jpeg_quality=jpeg_quality,
                        filename_prefix=filename_prefix,
                        target_max_dimension=target_max_dimension,
                    )
                selected_count += 1

            frame_index += 1
    finally:
        capture.release()


def video_frame_count(source_path: Path) -> int:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("后端尚未安装视频抽帧依赖 opencv-python-headless。") from exc

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError("无法读取上传的视频文件。")
    try:
        return max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    finally:
        capture.release()


def video_frame_rate(source_path: Path) -> float:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("后端尚未安装视频抽帧依赖 opencv-python-headless。") from exc

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError("无法读取上传的视频文件。")
    try:
        return max(0.0, float(capture.get(cv2.CAP_PROP_FPS) or 0))
    finally:
        capture.release()


def expected_extracted_frame_count(total_frames: int, frame_interval: int, max_images: int) -> int:
    if total_frames <= 0:
        return 0
    interval = max(1, int(frame_interval))
    return min(max(1, int(max_images)), ((total_frames - 1) // interval) + 1)


def _encode_frame(
    frame,
    *,
    source_frame_index: int,
    source_ordinal: int,
    output_format: str,
    jpeg_quality: int,
    filename_prefix: str,
    target_max_dimension: int | None,
) -> ExtractedVideoFrame:
    import cv2

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb_frame)
    image = _resize_to_max_dimension(image, target_max_dimension)
    output = BytesIO()
    normalized_format = "png" if output_format == "png" else "jpg"
    if normalized_format == "png":
        image.save(output, format="PNG")
        mime_type = "image/png"
    else:
        image.convert("RGB").save(output, format="JPEG", quality=max(1, min(100, int(jpeg_quality))))
        mime_type = "image/jpeg"

    return ExtractedVideoFrame(
        source_frame_index=source_frame_index,
        source_ordinal=source_ordinal,
        output_filename=f"{filename_prefix}_{source_ordinal - 1:06d}.{normalized_format}",
        image_bytes=output.getvalue(),
        mime_type=mime_type,
    )


def _resize_to_max_dimension(image: Image.Image, target_max_dimension: int | None) -> Image.Image:
    if target_max_dimension is None:
        return image

    target = max(1, int(target_max_dimension))
    width, height = image.size
    longest_edge = max(width, height)
    if longest_edge <= target:
        return image

    scale = target / longest_edge
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    try:
        resampling_filter = Image.Resampling.LANCZOS
    except AttributeError:
        resampling_filter = Image.LANCZOS
    return image.resize(new_size, resampling_filter)
