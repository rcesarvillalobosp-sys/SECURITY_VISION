"""Adquisición controlada: solo descarga fuentes autorizadas y conserva originales inmutables.

Estructura en disco::

    raw/<source_id>/<version>/
        <archivo original>          # tal cual se descargó, solo lectura
        PROVENANCE.json             # URL, fecha, sha256, tamaño, licencia en el momento
        extracted/                  # extracción fiel del original, solo lectura
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .sources import SourceManifest, UsePurpose


class AcquisitionError(Exception):
    pass


def source_dir(raw_root: Path, manifest: SourceManifest) -> Path:
    return raw_root / manifest.id / manifest.version


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def make_read_only(root: Path) -> None:
    paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for p in paths:
        os.chmod(p, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def assert_authorized(manifest: SourceManifest, purpose: UsePurpose) -> None:
    if not manifest.is_authorized(purpose):
        raise AcquisitionError(
            f"'{manifest.id}' no está autorizada para {purpose.value} "
            f"(licencia: {manifest.license.name}, estado: {manifest.license.status.value}). "
            "No se descarga."
        )
    if manifest.download is None:
        raise AcquisitionError(f"'{manifest.id}' no define descarga automática")


def download(manifest: SourceManifest, raw_root: Path, purpose: UsePurpose) -> Path:
    """Descarga el original si está autorizado. Idempotente: no re-descarga si ya existe y es íntegro."""
    import httpx  # dependencia opcional del grupo ml

    assert_authorized(manifest, purpose)
    spec = manifest.download
    assert spec is not None
    target_dir = source_dir(raw_root, manifest)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / spec.filename
    provenance_path = target_dir / "PROVENANCE.json"

    if target.exists() and provenance_path.exists():
        recorded = json.loads(provenance_path.read_text(encoding="utf-8"))
        if sha256_file(target) == recorded["sha256"]:
            return target
        raise AcquisitionError(f"{target} existe pero no coincide con su PROVENANCE.json: revisar manualmente")

    partial = target.with_suffix(target.suffix + ".partial")
    with httpx.stream("GET", spec.url, follow_redirects=True, timeout=60.0) as resp:
        resp.raise_for_status()
        final_url = str(resp.url)
        with partial.open("wb") as fh:
            for block in resp.iter_bytes(1 << 20):
                fh.write(block)

    size = partial.stat().st_size
    if spec.expected_size is not None and size != spec.expected_size:
        partial.unlink()
        raise AcquisitionError(f"tamaño inesperado: {size} != {spec.expected_size}")
    digest = sha256_file(partial)
    if spec.sha256 is not None and digest != spec.sha256:
        partial.unlink()
        raise AcquisitionError("sha256 no coincide con el manifiesto")
    partial.rename(target)

    provenance = {
        "source_id": manifest.id,
        "version": manifest.version,
        "url": spec.url,
        "final_url": final_url,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "sha256": digest,
        "size_bytes": size,
        "purpose_authorized": purpose.value,
        "license": manifest.license.model_dump(mode="json"),
        "provenance": manifest.provenance.model_dump(mode="json"),
    }
    provenance_path.write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
    make_read_only(target)
    make_read_only(provenance_path)
    return target


def _safe_member_path(dest: Path, member: str) -> Path:
    """Evita zip-slip: rutas absolutas, '..' o unidades de Windows."""
    pure = PurePosixPath(member.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or (pure.parts and ":" in pure.parts[0]):
        raise AcquisitionError(f"ruta insegura en el archivo: {member!r}")
    resolved = (dest / Path(*pure.parts)).resolve()
    if not resolved.is_relative_to(dest.resolve()):
        raise AcquisitionError(f"ruta fuera del destino: {member!r}")
    return resolved


def extract(archive: Path, dest: Path) -> Path:
    """Extrae una copia fiel (solo lectura). No modifica el archivo original."""
    marker = dest / ".extracted.json"
    if marker.exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            out = _safe_member_path(dest, info.filename)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                while block := src.read(1 << 20):
                    dst.write(block)
            count += 1
    make_read_only(dest)
    marker.write_text(
        json.dumps({"archive": archive.name, "archive_sha256": sha256_file(archive), "files": count}),
        encoding="utf-8",
    )
    return dest
