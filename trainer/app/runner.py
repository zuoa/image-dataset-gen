from __future__ import annotations

import csv
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

import requests
import yaml


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

    evaluation_report = run_dir / "evaluation_report.json"
    confusion_matrix_path = run_dir / "confusion_matrix.png"
    best_model = run_dir / "weights" / "best.pt"
    if best_model.exists():
        try:
            evaluation = _evaluate_with_supervision(
                _load_model(YOLO, str(best_model)),
                data_yaml,
                confidence_threshold=0.25,
                iou_threshold=0.5,
                confusion_matrix_path=confusion_matrix_path,
            )
        except Exception:
            evaluation = None
        if evaluation is not None:
            evaluation_report.write_text(
                json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            metrics = {**metrics, **(evaluation.get("metrics") or {})}
            metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    artifacts = _collect_artifacts(
        run_dir,
        metrics_path,
        evaluation_report=evaluation_report,
        confusion_matrix_path=confusion_matrix_path,
    )
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


def _collect_artifacts(
    run_dir: Path,
    metrics_path: Path,
    *,
    evaluation_report: Path | None = None,
    confusion_matrix_path: Path | None = None,
) -> list[tuple[str, Path]]:
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
    if evaluation_report is not None and evaluation_report.exists():
        candidates.append(("evaluation_report", evaluation_report))
    if confusion_matrix_path is not None and confusion_matrix_path.exists():
        candidates.append(("confusion_matrix", confusion_matrix_path))
    return candidates


def _evaluate_with_supervision(
    model: Any,
    data_yaml: Path,
    *,
    confidence_threshold: float,
    iou_threshold: float,
    confusion_matrix_path: Path,
) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import numpy as np
    from PIL import Image
    import supervision as sv
    from supervision.metrics import MeanAveragePrecision

    config = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    categories = _yaml_categories(config.get("names"))
    split_name = "test" if config.get("test") and _split_has_images(data_yaml.parent, str(config["test"])) else "val"
    split_value = str(config.get(split_name) or config.get("train") or "")
    image_paths = _split_image_paths(data_yaml.parent, split_value)
    manifest = _load_export_manifest(data_yaml.parent)
    manifest_by_path = {
        str(item.get("imagePath") or "").replace("\\", "/"): item
        for item in manifest.get("images", [])
        if isinstance(item, dict)
    }

    predictions: list[Any] = []
    targets: list[Any] = []
    image_contexts: list[dict[str, Any]] = []
    for image_path in image_paths:
        with Image.open(image_path) as image:
            image_width, image_height = image.size
        target = _load_yolo_target(
            image_path, data_yaml.parent, image_width, image_height
        )
        result_list = list(
            model.predict(
                source=str(image_path),
                conf=confidence_threshold,
                verbose=False,
            )
            or []
        )
        prediction = (
            sv.Detections.from_ultralytics(result_list[0])
            if result_list
            else sv.Detections.empty()
        )
        predictions.append(prediction)
        targets.append(target)
        relative_path = image_path.relative_to(data_yaml.parent).as_posix()
        manifest_item = manifest_by_path.get(relative_path, {})
        image_contexts.append(
            {
                "imageId": manifest_item.get("imageId"),
                "annotationRevision": manifest_item.get("annotationRevision"),
                "imagePath": relative_path,
            }
        )

    if not predictions:
        return {
            "schemaVersion": 1,
            "supervisionVersion": sv.__version__,
            "split": split_name,
            "metrics": {},
            "perClass": [],
            "confusionMatrix": [],
            "issues": [],
        }

    map_result = MeanAveragePrecision().update(predictions, targets).compute()
    confusion = sv.ConfusionMatrix.from_detections(
        predictions,
        targets,
        categories,
        conf_threshold=confidence_threshold,
        iou_threshold=iou_threshold,
    )
    confusion.plot(
        save_path=str(confusion_matrix_path),
        title=f"{split_name.title()} confusion matrix",
        normalize=True,
    )
    per_class, issues = _evaluation_details(
        predictions,
        targets,
        categories,
        image_contexts,
        iou_threshold,
    )
    return {
        "schemaVersion": 1,
        "supervisionVersion": sv.__version__,
        "split": split_name,
        "config": {
            "confidenceThreshold": confidence_threshold,
            "iouThreshold": iou_threshold,
        },
        "metrics": {
            "mAP50": round(float(map_result.map50), 6),
            "mAP50_95": round(float(map_result.map50_95), 6),
        },
        "perClass": per_class,
        "confusionMatrix": np.asarray(confusion.matrix, dtype=int).tolist(),
        "confusionMatrixLabels": [*categories, "background"],
        "issues": issues,
    }


def _yaml_categories(names: Any) -> list[str]:
    if isinstance(names, dict):
        return [str(value) for _, value in sorted(names.items(), key=lambda item: int(item[0]))]
    if isinstance(names, list):
        return [str(value) for value in names]
    return []


def _split_image_paths(dataset_root: Path, split_value: str) -> list[Path]:
    split_path = Path(split_value)
    if not split_path.is_absolute():
        split_path = dataset_root / split_path
    if split_path.is_file():
        return [
            Path(line.strip()) if Path(line.strip()).is_absolute() else dataset_root / line.strip()
            for line in split_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return sorted(
        path
        for path in split_path.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ) if split_path.exists() else []


def _load_export_manifest(dataset_root: Path) -> dict[str, Any]:
    path = dataset_root / "dataset-manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yolo_target(
    image_path: Path,
    dataset_root: Path,
    image_width: int,
    image_height: int,
):
    import numpy as np
    import supervision as sv

    relative = image_path.relative_to(dataset_root)
    parts = list(relative.parts)
    if "images" in parts:
        parts[parts.index("images")] = "labels"
    label_path = (dataset_root / Path(*parts)).with_suffix(".txt")
    boxes: list[list[float]] = []
    class_ids: list[int] = []
    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            values = line.split()
            if len(values) < 5:
                continue
            class_id = int(float(values[0]))
            x_center, y_center, width, height = [float(value) for value in values[1:5]]
            boxes.append(
                [
                    (x_center - width / 2) * image_width,
                    (y_center - height / 2) * image_height,
                    (x_center + width / 2) * image_width,
                    (y_center + height / 2) * image_height,
                ]
            )
            class_ids.append(class_id)
    return sv.Detections(
        xyxy=np.asarray(boxes, dtype=float).reshape((-1, 4)),
        class_id=np.asarray(class_ids, dtype=int),
    )


def _evaluation_details(
    predictions: list[Any],
    targets: list[Any],
    categories: list[str],
    image_contexts: list[dict[str, Any]],
    iou_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import numpy as np
    import supervision as sv

    counts = {
        index: {"tp": 0, "fp": 0, "fn": 0}
        for index in range(len(categories))
    }
    issues: list[dict[str, Any]] = []

    def add_issue(
        context: dict[str, Any],
        issue_type: str,
        score: float,
        details: dict[str, Any],
    ) -> None:
        if not context.get("imageId"):
            return
        issues.append(
            {
                **context,
                "issueType": issue_type,
                "severity": "error" if issue_type in {"false_negative", "class_confusion"} else "warning",
                "score": round(min(max(float(score), 0.0), 1.0), 6),
                "details": details,
            }
        )

    for prediction, target, context in zip(predictions, targets, image_contexts):
        ious = (
            np.asarray(sv.box_iou_batch(target.xyxy, prediction.xyxy), dtype=float)
            if len(target) and len(prediction)
            else np.empty((len(target), len(prediction)), dtype=float)
        )
        matched_predictions: set[int] = set()
        for target_index in range(len(target)):
            target_class = int(target.class_id[target_index])
            if not 0 <= target_class < len(categories):
                continue
            best_index = int(np.argmax(ious[target_index])) if len(prediction) else -1
            best_iou = float(ious[target_index, best_index]) if best_index >= 0 else 0.0
            if best_index >= 0 and best_iou >= iou_threshold and best_index not in matched_predictions:
                prediction_class = int(prediction.class_id[best_index])
                matched_predictions.add(best_index)
                predicted_name = (
                    categories[prediction_class]
                    if 0 <= prediction_class < len(categories)
                    else f"class_{prediction_class}"
                )
                if prediction_class == target_class:
                    counts[target_class]["tp"] += 1
                else:
                    counts[target_class]["fn"] += 1
                    counts.setdefault(prediction_class, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
                    add_issue(
                        context,
                        "class_confusion",
                        best_iou,
                        {
                            "expectedClass": categories[target_class],
                            "predictedClass": predicted_name,
                            "iou": round(best_iou, 4),
                        },
                    )
            else:
                counts[target_class]["fn"] += 1
                same_class_indexes = [
                    index
                    for index in range(len(prediction))
                    if int(prediction.class_id[index]) == target_class
                ]
                same_class_iou = max(
                    (float(ious[target_index, index]) for index in same_class_indexes),
                    default=0.0,
                )
                if same_class_iou >= 0.1:
                    add_issue(
                        context,
                        "low_iou",
                        1 - same_class_iou,
                        {"class": categories[target_class], "iou": round(same_class_iou, 4)},
                    )
                else:
                    add_issue(
                        context,
                        "false_negative",
                        1.0,
                        {"class": categories[target_class]},
                    )
        for prediction_index in range(len(prediction)):
            if prediction_index in matched_predictions:
                continue
            prediction_class = int(prediction.class_id[prediction_index])
            counts.setdefault(prediction_class, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
            confidence = (
                float(prediction.confidence[prediction_index])
                if prediction.confidence is not None
                else 0.0
            )
            add_issue(
                context,
                "false_positive",
                confidence,
                {
                    "class": (
                        categories[prediction_class]
                        if 0 <= prediction_class < len(categories)
                        else f"class_{prediction_class}"
                    ),
                    "confidence": round(confidence, 6),
                },
            )

    per_class: list[dict[str, Any]] = []
    for class_id, category in enumerate(categories):
        class_counts = counts[class_id]
        precision_denominator = class_counts["tp"] + class_counts["fp"]
        recall_denominator = class_counts["tp"] + class_counts["fn"]
        per_class.append(
            {
                "classId": class_id,
                "category": category,
                **class_counts,
                "precision": round(class_counts["tp"] / precision_denominator, 6) if precision_denominator else 0,
                "recall": round(class_counts["tp"] / recall_denominator, 6) if recall_denominator else 0,
            }
        )
    return per_class, issues


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
