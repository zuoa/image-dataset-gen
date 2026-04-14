from pathlib import Path

from app import create_app
from app.config import Config


def test_relative_sqlite_database_path_is_resolved_under_instance_dir(tmp_path: Path):
    class RelativeSqliteConfig(Config):
        SQLALCHEMY_DATABASE_URI = "sqlite:///nested/dev.db"
        STORAGE_ROOT = "tmp-storage"
        FRONTEND_URL = "http://localhost:4173"

    app = create_app(RelativeSqliteConfig, instance_path=tmp_path / "instance")

    expected_db_path = (tmp_path / "instance" / "nested" / "dev.db").resolve()
    expected_storage_root = (Path(app.root_path).parent / "tmp-storage").resolve()

    assert app.config["SQLALCHEMY_DATABASE_URI"] == f"sqlite:///{expected_db_path.as_posix()}"
    assert expected_db_path.parent.exists()
    assert app.config["STORAGE_ROOT"] == str(expected_storage_root)

