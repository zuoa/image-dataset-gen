from pathlib import Path
import stat

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


def test_x_accel_repairs_existing_file_permissions(tmp_path: Path):
    class FileDeliveryConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        USE_X_ACCEL_REDIRECT = True

    app = create_app(FileDeliveryConfig)
    image_dir = tmp_path / "images" / "dataset-id"
    image_dir.mkdir(parents=True)
    image = image_dir / "image-000001.jpg"
    image.write_bytes(b"image")
    tmp_path.chmod(0o700)
    (tmp_path / "images").chmod(0o700)
    image_dir.chmod(0o700)
    image.chmod(0o600)

    with app.test_request_context():
        response = deliver_local_file(image, mimetype="image/jpeg")

    assert response.headers["X-Accel-Redirect"] == (
        "/_protected_assets/images/dataset-id/image-000001.jpg"
    )
    assert stat.S_IMODE(image.stat().st_mode) == 0o644
    assert stat.S_IMODE(tmp_path.stat().st_mode) & 0o011 == 0o011
    assert stat.S_IMODE((tmp_path / "images").stat().st_mode) & 0o011 == 0o011
    assert stat.S_IMODE(image_dir.stat().st_mode) & 0o011 == 0o011
