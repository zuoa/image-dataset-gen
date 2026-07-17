from __future__ import annotations

import json
import os
import sys
import types
import zipfile
from pathlib import Path

from PIL import Image

from app.runner import (
    _evaluate_with_supervision,
    _resolve_model_name,
    _training_workers,
    train_yolov8,
)


class _FakeTrainer:
    epoch = 0


class _FakeYOLO:
    expected_train_kwargs: dict[str, object] = {}

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.callbacks: dict[str, object] = {}

    def add_callback(self, name: str, callback: object) -> None:
        self.callbacks[name] = callback

    def train(self, **kwargs: object) -> None:
        model_dir = Path(os.environ["TRAINER_MODEL_DIR"]).resolve()
        assert Path.cwd() == model_dir
        assert kwargs["amp"] is False
        for key, value in self.expected_train_kwargs.items():
            assert kwargs[key] == value

        data_yaml = Path(str(kwargs["data"]))
        data_yaml_lines = data_yaml.read_text(encoding="utf-8").splitlines()
        expected_path_line = f"path: {json.dumps(str(data_yaml.parent), ensure_ascii=False)}"
        assert expected_path_line in data_yaml_lines
        assert "val: images/train" in data_yaml_lines

        run_dir = Path(str(kwargs["project"])) / str(kwargs["name"])
        weights_dir = run_dir / "weights"
        weights_dir.mkdir(parents=True, exist_ok=True)
        (weights_dir / "best.pt").write_bytes(b"best")
        (weights_dir / "last.pt").write_bytes(b"last")
        (run_dir / "results.csv").write_text(
            "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)\n"
            "1,0.9,0.8,0.7,0.6\n",
            encoding="utf-8",
        )
        callback = self.callbacks.get("on_train_epoch_end")
        if callable(callback):
            callback(_FakeTrainer())


class _FakeDownloadResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_FakeDownloadResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.body]


class _EmptyPredictionModel:
    def predict(self, **_: object) -> list[object]:
        return []


def test_supervision_evaluation_emits_metrics_matrix_and_issues(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    images_dir = dataset_root / "images" / "val"
    labels_dir = dataset_root / "labels" / "val"
    images_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    image_path = images_dir / "widget_000001.png"
    Image.new("RGB", (100, 80), color=(120, 140, 160)).save(image_path)
    (labels_dir / "widget_000001.txt").write_text(
        "0 0.5 0.5 0.4 0.5\n", encoding="utf-8"
    )
    data_yaml = dataset_root / "data.yaml"
    data_yaml.write_text(
        "train: images/val\nval: images/val\nnames: [widget]\n",
        encoding="utf-8",
    )
    (dataset_root / "dataset-manifest.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "imageId": "image-1",
                        "annotationRevision": 2,
                        "imagePath": "images/val/widget_000001.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    confusion_matrix = tmp_path / "confusion.png"

    report = _evaluate_with_supervision(
        _EmptyPredictionModel(),
        data_yaml,
        confidence_threshold=0.25,
        iou_threshold=0.5,
        confusion_matrix_path=confusion_matrix,
    )

    assert report["metrics"] == {"mAP50": 0.0, "mAP50_95": 0.0}
    assert report["confusionMatrixLabels"] == ["widget", "background"]
    assert report["issues"] == [
        {
            "imageId": "image-1",
            "annotationRevision": 2,
            "imagePath": "images/val/widget_000001.png",
            "issueType": "false_negative",
            "severity": "error",
            "score": 1.0,
            "details": {"class": "widget"},
        }
    ]
    assert confusion_matrix.exists()


def test_train_yolov8_preserves_downloaded_dataset_zip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=_FakeYOLO))
    monkeypatch.setattr(
        _FakeYOLO,
        "expected_train_kwargs",
        {
            "epochs": 200,
            "patience": 50,
            "dropout": 0.1,
            "mixup": 0.15,
            "weight_decay": 0.001,
            "workers": 0,
        },
    )
    model_dir = tmp_path / "models"
    monkeypatch.setenv("TRAINER_MODEL_DIR", str(model_dir))

    job = {"id": "job-1", "config": {"model": "yolov8n.pt"}}
    job_root = tmp_path / "job-1"
    job_root.mkdir()
    dataset_zip = job_root / "dataset.zip"
    with zipfile.ZipFile(dataset_zip, "w") as archive:
        archive.writestr("sample/data.yaml", "path: .\ntrain: images/train\nval: images/val\nnames:\n  0: object\n")
        archive.writestr("sample/images/train/object_000001.jpg", b"image")
        archive.writestr("sample/labels/train/object_000001.txt", "0 0.5 0.5 1 1\n")

    progress_updates: list[int] = []
    result = train_yolov8(job, dataset_zip, tmp_path, progress_updates.append)

    assert dataset_zip.exists()
    assert progress_updates == [5]
    assert result["metrics"]["precision"] == 0.9
    assert {artifact_type for artifact_type, _ in result["artifacts"]} == {
        "best_model",
        "last_model",
        "results_csv",
        "metrics",
    }


def test_training_workers_defaults_to_zero(monkeypatch) -> None:
    monkeypatch.delenv("TRAINER_YOLO_WORKERS", raising=False)

    assert _training_workers({}) == 0


def test_training_workers_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("TRAINER_YOLO_WORKERS", "2")

    assert _training_workers({}) == 2
    assert _training_workers({"workers": 4}) == 4
    assert _training_workers({"numWorkers": 3}) == 3
    assert _training_workers({"workers": -1}) == 0
    assert _training_workers({"workers": "invalid"}) == 0


def test_train_yolov8_passes_regularization_and_class_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=_FakeYOLO))
    monkeypatch.setattr(
        _FakeYOLO,
        "expected_train_kwargs",
        {"dropout": 0.2, "mixup": 0.25, "weight_decay": 0.002, "classes": [0]},
    )
    model_dir = tmp_path / "models"
    monkeypatch.setenv("TRAINER_MODEL_DIR", str(model_dir))

    job = {
        "id": "job-1",
        "config": {
            "model": "yolov8n.pt",
            "dropout": 0.2,
            "mixup": 0.25,
            "weightDecay": 0.002,
            "classes": [0],
        },
    }
    job_root = tmp_path / "job-1"
    job_root.mkdir()
    dataset_zip = job_root / "dataset.zip"
    with zipfile.ZipFile(dataset_zip, "w") as archive:
        archive.writestr("sample/data.yaml", "path: .\ntrain: images/train\nval: images/val\nnames:\n  0: object\n")
        archive.writestr("sample/images/train/object_000001.jpg", b"image")
        archive.writestr("sample/labels/train/object_000001.txt", "0 0.5 0.5 1 1\n")

    result = train_yolov8(job, dataset_zip, tmp_path, lambda _: None)

    assert result["metrics"]["mAP50"] == 0.7


def test_resolve_model_downloads_from_configured_base_url(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "models"
    calls: list[tuple[str, bool, int]] = []

    def fake_get(url: str, stream: bool, timeout: int) -> _FakeDownloadResponse:
        calls.append((url, stream, timeout))
        return _FakeDownloadResponse(b"model-weights")

    monkeypatch.setenv("TRAINER_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("TRAINER_MODEL_BASE_URL", "https://mirror.example.com/ultralytics/v8.3.0/")
    monkeypatch.setenv("TRAINER_MODEL_DOWNLOAD_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr("app.runner.requests.get", fake_get)

    resolved = _resolve_model_name("yolov8s.pt")

    assert resolved == str(model_dir / "yolov8s.pt")
    assert (model_dir / "yolov8s.pt").read_bytes() == b"model-weights"
    assert calls == [("https://mirror.example.com/ultralytics/v8.3.0/yolov8s.pt", True, 12)]
