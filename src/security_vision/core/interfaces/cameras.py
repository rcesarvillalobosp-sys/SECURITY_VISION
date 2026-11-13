"""Puertos del módulo de cámaras."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ..domain.cameras import Camera
from .video import SourceMetadata, VideoSourceConfig


class CameraRepository(ABC):
    @abstractmethod
    async def list(self, *, enabled_only: bool = False) -> list[Camera]: ...

    @abstractmethod
    async def get(self, camera_id: UUID) -> Camera | None: ...

    @abstractmethod
    async def add(self, camera: Camera) -> None: ...

    @abstractmethod
    async def update(self, camera: Camera) -> None: ...

    @abstractmethod
    async def delete(self, camera_id: UUID) -> None: ...

    @abstractmethod
    async def name_exists(self, name: str, site_id: UUID | None, exclude: UUID | None = None) -> bool: ...

    @abstractmethod
    async def record_status(self, camera_id: UUID, status: str, detail: str | None, at: datetime) -> None: ...


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    elapsed_ms: float
    metadata: SourceMetadata | None = None
    error: str | None = None
    snapshot_jpeg: bytes | None = field(default=None, repr=False)


class VideoProbe(ABC):
    """Prueba de conectividad: abre la fuente, lee un fotograma y cierra, con un plazo total."""

    @abstractmethod
    async def probe(self, provider: str, config: VideoSourceConfig, timeout: float,
                    with_snapshot: bool = False) -> ProbeResult: ...


@dataclass(frozen=True)
class DiscoveredCamera:
    kind: str  # "usb" | "onvif"
    name: str
    address: str
    details: dict[str, str] = field(default_factory=dict)


class MediaServer(ABC):
    """Servidor de medios (MediaMTX): distribuye cada cámara a navegador (WebRTC) y worker."""

    @abstractmethod
    async def ensure_path(self, name: str, source_url: str | None) -> None:
        """Crea/actualiza la ruta. ``source_url`` None = ruta de publicación (USB republicada)."""

    @abstractmethod
    async def remove_path(self, name: str) -> None: ...

    @abstractmethod
    def read_url(self, name: str) -> str:
        """URL RTSP desde la que el worker lee la cámara a través del servidor."""

    @abstractmethod
    def webrtc_url(self, name: str) -> str: ...

    def read_credentials(self) -> tuple[str | None, str | None]:
        """Credenciales con las que el worker lee del servidor (None = lectura anónima)."""
        return None, None
