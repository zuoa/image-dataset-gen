from io import BytesIO
from pathlib import Path
import stat

from app.services.storage_backend import local_backend


def test_local_backend_writes_shared_readable_files(tmp_path: Path):
    backend = local_backend(str(tmp_path))

    byte_object = backend.put_bytes("images/dataset/image.jpg", b"image")
    stream_object = backend.put_stream("exports/dataset.zip", BytesIO(b"archive"))

    assert stat.S_IMODE(byte_object.path.stat().st_mode) == 0o644
    assert stat.S_IMODE(stream_object.path.stat().st_mode) == 0o644
