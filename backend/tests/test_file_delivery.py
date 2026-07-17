from pathlib import Path

from app import create_app
from app.config import TestConfig
from app.services.file_delivery import deliver_local_file


def test_x_accel_content_disposition_encodes_unicode_filename(tmp_path: Path):
    class FileDeliveryConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        USE_X_ACCEL_REDIRECT = True

    app = create_app(FileDeliveryConfig)
    archive = tmp_path / "exports" / "dataset.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"archive")

    with app.test_request_context():
        response = deliver_local_file(
            archive,
            mimetype="application/zip",
            download_name="中文数据集.zip",
            as_attachment=True,
        )

    header = response.headers["Content-Disposition"]
    assert header.startswith('attachment; filename="download.zip";')
    assert "filename*=UTF-8''%E4%B8%AD%E6%96%87%E6%95%B0%E6%8D%AE%E9%9B%86.zip" in header
    header.encode("latin-1")
