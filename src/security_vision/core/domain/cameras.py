"""Cámaras: entidad, tipos de fuente y validación de URIs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import PurePath
from urllib.parse import urlsplit
from uuid import UUID

from .errors import ValidationError


class SourceType(StrEnum):
    RTSP = "rtsp"
    USB = "usb"
    FILE = "file"
    TEST = "test"  # patrón sintético: solo desarrollo/diagnóstico


@dataclass(slots=True)
class Camera:
    id: UUID
    name: str
    source_type: SourceType
    source_uri: str  # SIN credenciales
    analysis_fps: float = 2.0
    enabled: bool = True
    site_id: UUID | None = None
    width: int | None = None
    height: int | None = None
    target_fps: float | None = None
    location: dict[str, str] = field(default_factory=dict)
    mediamtx_path: str | None = None
    credentials_encrypted: bytes | None = None
    default_profile_id: UUID | None = None
    last_status: str | None = None
    last_status_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def has_credentials(self) -> bool:
        return self.credentials_encrypted is not None


_USB_RE = re.compile(r"^usb:[^\x00-\x1f\"]{1,200}$")


def validate_source(source_type: SourceType, uri: str, *, allow_test: bool, files_root: str | None) -> str:
    """Valida y normaliza la URI. Nunca acepta credenciales embebidas (van cifradas aparte)."""
    uri = uri.strip()
    if not uri or len(uri) > 1000:
        raise ValidationError("URI vacía o demasiado larga")
    if source_type is SourceType.RTSP:
        parts = urlsplit(uri)
        if parts.scheme not in ("rtsp", "rtsps") or not parts.hostname:
            raise ValidationError("una cámara RTSP necesita una URI rtsp:// o rtsps:// con host")
        if parts.username or parts.password or "@" in parts.netloc:
            raise ValidationError("no incluyas usuario/contraseña en la URI: usa el campo de credenciales")
        return uri
    if source_type is SourceType.USB:
        if not _USB_RE.match(uri):
            raise ValidationError("formato USB: usb:<nombre o índice del dispositivo>")
        return uri
    if source_type is SourceType.FILE:
        if not files_root:
            raise ValidationError("las fuentes de archivo están deshabilitadas (SV_VIDEO_FILES_DIR)")
        rel = uri.removeprefix("file://")
        p = PurePath(rel)
        if p.is_absolute() or ".." in p.parts or ":" in rel:
            raise ValidationError("ruta de archivo relativa a SV_VIDEO_FILES_DIR, sin '..'")
        return rel.replace("\\", "/")
    if source_type is SourceType.TEST:
        if not allow_test:
            raise ValidationError("las fuentes de prueba están deshabilitadas en este entorno")
        if not uri.startswith("testpattern://"):
            raise ValidationError("fuente de prueba: testpattern://?...")
        return uri
    raise ValidationError(f"tipo de fuente no soportado: {source_type}")
