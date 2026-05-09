from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[[int], None]


def train_yolov8(job: dict[str, Any], dataset_zip: Path, work_root: Path, on_progress: ProgressCallback) -> dict[str, Any]:
    from ultralytics import YOLO

    job_id = str(job["id"])
    config = job.get("config") or {}
    job_root = work_root / job_id
    dataset_root = job_root / "dataset"
    runs_root = job_root / "runs"
    if job_root.exists():
        shutil.rmtree(job_root)
    dataset_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(dataset_zip) as archive:
        archive.extractall(dataset_root)

    data_yaml = _find_data_yaml(dataset_root)
    model_name = str(config.get("model") or "yolov8n.pt")
    epochs = int(config.get("epochs") or 50)
    image_size = int(config.get("imageSize") or 640)
    batch_size = int(config.get("batchSize") or 16)
    patience = int(config.get("patience") or 20)
    device = str(config.get("device") or "").strip() or None

    model = YOLO(model_name)

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
