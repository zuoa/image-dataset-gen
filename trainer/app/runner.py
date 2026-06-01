from __future__ import annotations

import csv
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[[int], None]
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


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
    epochs = int(config.get("epochs") or 50)
    image_size = int(config.get("imageSize") or 640)
    batch_size = int(config.get("batchSize") or 16)
    patience = int(config.get("patience") or 20)
    device = str(config.get("device") or "").strip() or None

    model = _load_model(YOLO, model_name)

    def epoch_end(trainer: Any) -> None:
        current_epoch = int(getattr(trainer, "epoch", 0)) + 1
        percent = min(95, max(5, round(current_epoch / max(epochs, 1) * 95)))
        on_progress(percent)

    model.add_callback("on_train_epoch_end", epoch_end)
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=image_size,
        batch=batch_size,
        patience=patience,
        device=device,
        project=str(runs_root),
        name="train",
        exist_ok=True,
    )

    run_dir = runs_root / "train"
    metrics = _read_metrics(run_dir)
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    artifacts = _collect_artifacts(run_dir, metrics_path)
    return {"metrics": metrics, "artifacts": artifacts}


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

    return model_name


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


def _read_metrics(run_dir: Path) -> dict[str, Any]:
    results_csv = run_dir / "results.csv"
    if not results_csv.exists():
        return {}

    rows = list(csv.DictReader(results_csv.open("r", encoding="utf-8")))
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
