from __future__ import annotations

import csv
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

import requests


ProgressCallback = Callable[[int], None]
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
ULTRALYTICS_ASSETS_RELEASE = "v8.3.0"


def _config_value(config: dict[str, Any], *keys: str, default: object) -> object:
    for key in keys:
        value = config.get(key)
        if value is not None and value != "":
            return value
    return default


def train_yolov8(job: dict[str, Any], dataset_zip: Path, work_root: Path, on_progress: ProgressCallback) -> dict[str, Any]:
    from ultralytics import YOLO

    job_id = str(job["id"])
    config = job.get("config") or {}
    job_root = work_root / job_id
    dataset_root = job_root / "dataset"
    runs_root = job_root / "runs"
    job_root.mkdir(parents=True, exist_ok=True)
    for generated_path in (dataset_root, runs_root):
        if generated_path.exists():
            shutil.rmtree(generated_path)
    dataset_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(dataset_zip) as archive:
        archive.extractall(dataset_root)

    data_yaml = _prepare_data_yaml(_find_data_yaml(dataset_root))
    model_name = _resolve_model_name(str(config.get("model") or "yolov8n.pt"))
    epochs = int(_config_value(config, "epochs", default=200))
    image_size = int(_config_value(config, "imageSize", default=640))
    batch_size = int(_config_value(config, "batchSize", default=16))
    patience = int(_config_value(config, "patience", default=50))
    dropout = float(_config_value(config, "dropout", default=0.1))
    mixup = float(_config_value(config, "mixup", default=0.15))
    weight_decay = float(_config_value(config, "weightDecay", "weight_decay", default=0.001))
    classes_config = config.get("classes") or []
    classes = [int(class_index) for class_index in classes_config] if classes_config else None
    device = str(config.get("device") or "").strip() or None
    amp = _training_amp_enabled(config)
    workers = _training_workers(config)

    model = _load_model(YOLO, model_name)

    def epoch_end(trainer: Any) -> None:
        current_epoch = int(getattr(trainer, "epoch", 0)) + 1
        percent = min(95, max(5, round(current_epoch / max(epochs, 1) * 95)))
        on_progress(percent)

    model.add_callback("on_train_epoch_end", epoch_end)
    train_kwargs: dict[str, object] = {
        "data": str(data_yaml),
        "epochs": epochs,
        "imgsz": image_size,
        "batch": batch_size,
        "patience": patience,
        "dropout": dropout,
        "mixup": mixup,
        "weight_decay": weight_decay,
        "device": device,
        "amp": amp,
        "workers": workers,
        "project": str(runs_root),
        "name": "train",
        "exist_ok": True,
    }
    if classes is not None:
        train_kwargs["classes"] = classes
    _train_model(model, **train_kwargs)

    run_dir = runs_root / "train"
    metrics = _read_metrics(run_dir)
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    artifacts = _collect_artifacts(run_dir, metrics_path)
    return {"metrics": metrics, "artifacts": artifacts}


def predict_yolov8(
    model_path: Path,
    image_path: Path,
    *,
    categories: list[str] | None = None,
    confidence_threshold: float = 0.25,
    image_size: int = 640,
) -> dict[str, Any]:
    from ultralytics import YOLO

    model = _load_model(YOLO, str(model_path))
    results = model.predict(
        source=str(image_path),
        conf=confidence_threshold,
        imgsz=image_size,
        verbose=False,
    )
    return {"detections": _detections_from_ultralytics_results(results, categories or [])}


def _find_data_yaml(dataset_root: Path) -> Path:
    matches = sorted(dataset_root.rglob("data.yaml"))
    if not matches:
        raise RuntimeError("data.yaml not found in dataset archive")
    return matches[0]


def _prepare_data_yaml(data_yaml: Path) -> Path:
    dataset_path = json.dumps(str(data_yaml.parent.resolve()), ensure_ascii=False)
    path_line = f"path: {dataset_path}"
    lines = data_yaml.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("path:"):
            lines[index] = path_line
            break
    else:
        lines.insert(0, path_line)

    train_value = _find_yaml_value(lines, "train")
    val_value = _find_yaml_value(lines, "val")
    if train_value and _split_has_images(data_yaml.parent, train_value):
        if not val_value or not _split_has_images(data_yaml.parent, val_value):
            _set_yaml_value(lines, "val", train_value, after_key="train")

    data_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data_yaml


def _find_yaml_value(lines: list[str], key: str) -> str:
    prefix = f"{key}:"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip("\"'")
    return ""


def _set_yaml_value(lines: list[str], key: str, value: str, after_key: str) -> None:
    replacement = f"{key}: {value}"
    key_prefix = f"{key}:"
    for index, line in enumerate(lines):
        if line.strip().startswith(key_prefix):
            lines[index] = replacement
            return

    after_prefix = f"{after_key}:"
    for index, line in enumerate(lines):
        if line.strip().startswith(after_prefix):
            lines.insert(index + 1, replacement)
            return
    lines.append(replacement)


def _split_has_images(dataset_root: Path, split_value: str) -> bool:
    split_path = Path(split_value)
    if not split_path.is_absolute():
        split_path = dataset_root / split_path
    if split_path.is_file():
        return True
    if not split_path.exists():
        return False
    return any(path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES for path in split_path.rglob("*"))


def _training_amp_enabled(config: dict[str, Any]) -> bool:
    if "amp" in config:
        return _as_bool(config.get("amp"), default=False)
    return _env_bool("TRAINER_YOLO_AMP", default=False)


def _training_workers(config: dict[str, Any]) -> int:
    value = _config_value(
        config,
        "workers",
        "numWorkers",
        "num_workers",
        default=os.getenv("TRAINER_YOLO_WORKERS", "0"),
    )
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return _as_bool(value, default=default)


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_model_name(model_name: str) -> str:
    model_dir = Path(os.getenv("TRAINER_MODEL_DIR", "/app/models")).resolve()
    model_dir.mkdir(parents=True, exist_ok=True)

    requested = Path(model_name)
    if requested.is_absolute() and requested.exists():
        return str(requested)
    if requested.parent != Path(".") and requested.exists():
        return str(requested.resolve())

    cached = model_dir / requested.name
    if cached.exists():
        return str(cached)

    if requested.parent == Path(".") and requested.suffix == ".pt":
        downloaded = _download_model_from_configured_mirror(requested.name, cached)
        if downloaded is not None:
            return str(downloaded)

    return model_name


def _download_model_from_configured_mirror(filename: str, output_path: Path) -> Path | None:
    url = _model_download_url(filename)
    if not url:
        return None

    timeout = int(os.getenv("TRAINER_MODEL_DOWNLOAD_TIMEOUT_SECONDS", "300"))
    temp_path = output_path.with_suffix(f"{output_path.suffix}.part")
    if temp_path.exists():
        temp_path.unlink()

    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with temp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        if temp_path.stat().st_size == 0:
            raise RuntimeError("downloaded model file is empty")
        temp_path.replace(output_path)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"failed to download model {filename} from {url}: {exc}") from exc

    return output_path


def _model_download_url(filename: str) -> str:
    release = os.getenv("TRAINER_MODEL_ASSETS_RELEASE", ULTRALYTICS_ASSETS_RELEASE).strip()
    github_url = f"https://github.com/ultralytics/assets/releases/download/{release}/{filename}"
    template = os.getenv("TRAINER_MODEL_URL_TEMPLATE", "").strip()
    if template:
        return template.format(filename=filename, release=release, github_url=github_url)

    base_url = os.getenv("TRAINER_MODEL_BASE_URL", "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}/{filename}"

    return ""


def _load_model(yolo_factory: Any, model_name: str) -> Any:
    requested = Path(model_name)
    if requested.is_absolute() or requested.parent != Path("."):
        return yolo_factory(model_name)

    model_dir = Path(os.getenv("TRAINER_MODEL_DIR", "/app/models")).resolve()
    original_cwd = Path.cwd()
    os.chdir(model_dir)
    try:
        return yolo_factory(model_name)
    finally:
        os.chdir(original_cwd)


def _train_model(model: Any, **kwargs: object) -> None:
    model_dir = Path(os.getenv("TRAINER_MODEL_DIR", "/app/models")).resolve()
    model_dir.mkdir(parents=True, exist_ok=True)
    original_cwd = Path.cwd()
    os.chdir(model_dir)
    try:
        model.train(**kwargs)
    finally:
        os.chdir(original_cwd)


def _read_metrics(run_dir: Path) -> dict[str, Any]:
    results_csv = run_dir / "results.csv"
    if not results_csv.exists():
        return {}

    with results_csv.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    latest = rows[-1]
    return {
        "epochsCompleted": _as_number(latest.get("epoch")),
        "precision": _as_number(_find_metric(latest, "precision")),
        "recall": _as_number(_find_metric(latest, "recall")),
        "mAP50": _as_number(_find_metric(latest, "mAP50")),
        "mAP50_95": _as_number(_find_metric(latest, "mAP50-95")),
    }


def _find_metric(row: dict[str, str], needle: str) -> str | None:
    normalized = needle.lower().replace("_", "").replace("-", "")
    for key, value in row.items():
        key_normalized = key.lower().replace("_", "").replace("-", "").replace("(", "").replace(")", "")
        if normalized in key_normalized:
            return value
    return None


def _as_number(value: str | None) -> float | int | None:
    if value is None or str(value).strip() == "":
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 6)


def _collect_artifacts(run_dir: Path, metrics_path: Path) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    best = run_dir / "weights" / "best.pt"
    last = run_dir / "weights" / "last.pt"
    results = run_dir / "results.csv"
    if best.exists():
        candidates.append(("best_model", best))
    if last.exists():
        candidates.append(("last_model", last))
    if results.exists():
        candidates.append(("results_csv", results))
    if metrics_path.exists():
        candidates.append(("metrics", metrics_path))
    return candidates


def _detections_from_ultralytics_results(results: object, categories: list[str]) -> list[dict[str, Any]]:
    result_list = list(results or [])
    if not result_list:
        return []
    result = result_list[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    xywhn_values = _to_plain_list(getattr(boxes, "xywhn", []))
    confidence_values = _to_plain_list(getattr(boxes, "conf", []))
    class_values = _to_plain_list(getattr(boxes, "cls", []))
    names = getattr(result, "names", {}) or {}

    detections: list[dict[str, Any]] = []
    for index, bbox in enumerate(xywhn_values):
        class_id = int(class_values[index]) if index < len(class_values) else -1
        confidence = float(confidence_values[index]) if index < len(confidence_values) else 0.0
        detections.append(
            {
                "category": _category_name(class_id, categories, names),
                "classId": class_id,
                "confidence": round(confidence, 6),
                "bbox": [_clamp(float(value)) for value in list(bbox)[:4]],
            }
        )
    return detections


def _category_name(class_id: int, categories: list[str], names: object) -> str:
    if 0 <= class_id < len(categories):
        return str(categories[class_id])
    if isinstance(names, dict):
        value = names.get(class_id) or names.get(str(class_id))
        if value:
            return str(value)
    return f"class_{class_id}" if class_id >= 0 else "object"


def _to_plain_list(value: object) -> list:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        return value.tolist()
    if value is None:
        return []
    return list(value)  # type: ignore[arg-type]


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(max(value, minimum), maximum)
