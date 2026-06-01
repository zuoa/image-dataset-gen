from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

from app.runner import _resolve_model_name, train_yolov8


class _FakeTrainer:
    epoch = 0


class _FakeYOLO:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.callbacks: dict[str, object] = {}

    def add_callback(self, name: str, callback: object) -> None:
        self.callbacks[name] = callback

    def train(self, **kwargs: object) -> None:
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


def test_train_yolov8_preserves_downloaded_dataset_zip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=_FakeYOLO))
    monkeypatch.setenv("TRAINER_MODEL_DIR", str(tmp_path / "models"))

    job = {"id": "job-1", "config": {"model": "yolov8n.pt", "epochs": 1}}
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
    assert progress_updates == [95]
    assert result["metrics"]["precision"] == 0.9
    assert {artifact_type for artifact_type, _ in result["artifacts"]} == {
        "best_model",
        "last_model",
        "results_csv",
        "metrics",
    }


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
