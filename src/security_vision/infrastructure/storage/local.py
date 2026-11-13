"""Almacenamiento de objetos en disco local (sustituible por S3 compatible con el mismo puerto)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from security_vision.core.interfaces.infrastructure import ObjectStorage, StoredObject

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,400}$")


def validate_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key.split("/") or "//" in key:
        raise ValueError(f"clave de objeto inválida: {key!r}")
    return key


class LocalFileStorage(ObjectStorage):
    def __init__(self, root: Path, signing_key: bytes, url_prefix: str = "/api/v1/files") -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._signing_key = signing_key
        self._url_prefix = url_prefix

    def _path(self, key: str) -> Path:
        p = (self.root / validate_key(key)).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("clave fuera del almacenamiento")
        return p

    def put(self, key: str, data: bytes | BinaryIO, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = data if isinstance(data, bytes) else data.read()
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, path)  # escritura atómica: un lector nunca ve un archivo a medias
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        (path.parent / (path.name + ".ct")).write_text(content_type, encoding="utf-8")
        return StoredObject(key, len(blob), hashlib.sha256(blob).hexdigest(), content_type, datetime.now(UTC))

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def stat(self, key: str) -> tuple[int, datetime, str]:
        p = self._path(key)
        st = p.stat()
        ct_file = p.parent / (p.name + ".ct")
        ct = ct_file.read_text(encoding="utf-8") if ct_file.exists() else "application/octet-stream"
        return st.st_size, datetime.fromtimestamp(st.st_mtime, UTC), ct

    def delete(self, key: str) -> None:
        p = self._path(key)
        p.unlink(missing_ok=True)
        (p.parent / (p.name + ".ct")).unlink(missing_ok=True)

    def signed_url(self, key: str, ttl: timedelta) -> str:
        exp = int((datetime.now(UTC) + ttl).timestamp())
        return f"{self._url_prefix}/{validate_key(key)}?exp={exp}&sig={self.sign(key, exp)}"

    def sign(self, key: str, exp: int) -> str:
        return hmac.new(self._signing_key, f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()

    def verify(self, key: str, exp: int, sig: str) -> bool:
        return exp >= int(datetime.now(UTC).timestamp()) and hmac.compare_digest(self.sign(key, exp), sig)

    def list(self, prefix: str, older_than: datetime | None = None) -> Iterator[StoredObject]:
        base = self.root / prefix if prefix else self.root
        if not base.exists():
            return
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.name.endswith(".ct") or p.name.startswith(".tmp-"):
                continue
            st = p.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, UTC)
            if older_than and mtime >= older_than:
                continue
            yield StoredObject(p.relative_to(self.root).as_posix(), st.st_size, "", "", mtime)
