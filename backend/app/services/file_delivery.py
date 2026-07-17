from __future__ import annotations

from pathlib import Path
import re
import unicodedata
from urllib.parse import quote

from flask import Response, current_app, send_file

from app.services.storage_backend import ensure_shared_file_access


_UNSAFE_ASCII_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def content_disposition_header(filename: str, *, as_attachment: bool) -> str:
    """Build an ASCII-only header with an RFC 5987 UTF-8 filename."""
    name = Path(filename.replace("\r", "").replace("\n", "")).name.strip() or "download"
    source_stem = Path(name).stem
    ascii_stem = unicodedata.normalize("NFKD", source_stem).encode("ascii", "ignore").decode("ascii")
    ascii_stem = _UNSAFE_ASCII_FILENAME.sub("_", ascii_stem).strip(" .")
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = _UNSAFE_ASCII_FILENAME.sub("_", ascii_name).strip(" .")
    suffix = Path(name).suffix
    if not ascii_stem:
        ascii_suffix = _UNSAFE_ASCII_FILENAME.sub("", suffix)
        ascii_name = f"download{ascii_suffix}"
    ascii_name = ascii_name.replace("\\", "_").replace('"', "_")
    disposition = "attachment" if as_attachment else "inline"
    encoded_name = quote(name, safe="", encoding="utf-8")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


def deliver_local_file(
    path: Path,
    *,
    mimetype: str,
    download_name: str = "",
    as_attachment: bool = False,
):
    if not current_app.config.get("USE_X_ACCEL_REDIRECT", False):
        return send_file(
            path,
            mimetype=mimetype,
            as_attachment=as_attachment,
            download_name=download_name or None,
        )

    root = Path(current_app.config["STORAGE_ROOT"]).resolve()
    resolved = path.resolve()
    if not resolved.is_file() or not resolved.is_relative_to(root):
        return Response(status=404)
    ensure_shared_file_access(resolved, root)
    relative = resolved.relative_to(root).as_posix()
    response = Response(status=200, mimetype=mimetype)
    response.headers["X-Accel-Redirect"] = f"/_protected_assets/{quote(relative)}"
    if download_name:
        response.headers["Content-Disposition"] = content_disposition_header(
            download_name, as_attachment=as_attachment
        )
    return response
