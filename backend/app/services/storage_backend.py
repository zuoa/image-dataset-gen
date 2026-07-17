from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import BinaryIO

from app.extensions import db
from app.models import Asset


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    path: Path
    size_bytes: int
    sha256: str


class LocalStorageBackend:
    name = "local"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, key: str) -> Path:
        normalized = _normalize_key(key)
        path = (self.root / normalized).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("storage key escapes configured root")
        return path

    def put_bytes(self, key: str, payload: bytes) -> StoredObject:
        path = self.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            _fsync_directory(path.parent)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return StoredObject(key=_normalize_key(key), path=path, size_bytes=len(payload), sha256=_sha256(payload))

    def put_stream(self, key: str, stream: BinaryIO, *, chunk_size: int = 1024 * 1024) -> StoredObject:
        path = self.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            _fsync_directory(path.parent)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return StoredObject(
            key=_normalize_key(key), path=path, size_bytes=size_bytes, sha256=digest.hexdigest()
        )

    def exists(self, key: str) -> bool:
        return self.resolve(key).is_file()

    def delete(self, key: str) -> None:
        self.resolve(key).unlink(missing_ok=True)


def local_backend(storage_root: str) -> LocalStorageBackend:
    return LocalStorageBackend(storage_root)


def register_local_asset(
    storage_root: str,
    path: Path,
    *,
    user_id: str,
    dataset_id: str | None,
    kind: str,
    mime_type: str,
    original_filename: str = "",
    width: int = 0,
    height: int = 0,
    metadata: dict[str, object] | None = None,
) -> Asset:
    root = Path(storage_root).expanduser().resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise StorageError("asset path is outside configured storage root")
    storage_key = resolved.relative_to(root).as_posix()
    size_bytes, checksum = hash_file(resolved)
    asset = Asset.query.filter_by(storage_backend="local", storage_key=storage_key).first()
    if asset is None:
        asset = Asset(
            user_id=user_id,
            dataset_id=dataset_id,
            kind=kind,
            storage_backend="local",
            storage_key=storage_key,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=checksum,
            width=width,
            height=height,
            status="ready",
            metadata_json=metadata or {},
        )
        db.session.add(asset)
    else:
        asset.user_id = user_id
        asset.dataset_id = dataset_id
        asset.kind = kind
        asset.original_filename = original_filename
        asset.mime_type = mime_type
        asset.size_bytes = size_bytes
        asset.sha256 = checksum
        asset.width = width
        asset.height = height
        asset.status = "ready"
        asset.deleted_at = None
        asset.metadata_json = metadata or asset.metadata_json or {}
    return asset


def resolve_asset_path(storage_root: str, asset: Asset) -> Path:
    if asset.storage_backend != "local":
        raise StorageError(f"unsupported storage backend: {asset.storage_backend}")
    return local_backend(storage_root).resolve(asset.storage_key)


def hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            size_bytes += len(chunk)
    return size_bytes, digest.hexdigest()


def _normalize_key(key: str) -> str:
    normalized = PurePosixPath(key)
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise StorageError("invalid storage key")
    return normalized.as_posix()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
