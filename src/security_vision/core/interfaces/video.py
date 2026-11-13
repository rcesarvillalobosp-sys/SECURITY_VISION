"""Puerto de fuentes de vídeo. Implementaciones en ``security_vision.plugins.video_sources``."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, SecretStr


class SourceStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(slots=True)
class Frame:
    """Fotograma RGB HxWx3 uint8. Contenedor propio: no acopla el sistema a OpenCV ni a PyAV."""

    data: np.ndarray
    frame_id: int
    captured_at: datetime  # UTC
    source_pts: float | None = None

    @property
    def width(self) -> int:
        return int(self.data.shape[1])

    @property
    def height(self) -> int:
        return int(self.data.shape[0])


class VideoSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uri: str  # rtsp://host/path, usb:0, file:///ruta.mp4 — SIN credenciales embebidas
    username: str | None = None
    password: SecretStr | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    options: dict[str, Any] = {}


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    codec: str | None
    width: int | None
    height: int | None
    nominal_fps: float | None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceCapabilities:
    schemes: frozenset[str]  # {"rtsp", "usb", "file"}
    hardware_decoding: bool = False


class VideoSourceError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class VideoSource(ABC):
    """La reconexión NO es responsabilidad del adaptador: la gestiona el supervisor de cámaras."""

    provider_name: ClassVar[str]

    def __init__(self, config: VideoSourceConfig) -> None:
        self.config = config

    @classmethod
    @abstractmethod
    def capabilities(cls) -> SourceCapabilities: ...

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def read_frame(self, timeout: float) -> Frame | None:
        """Devuelve el siguiente fotograma o ``None`` si no llega en ``timeout`` segundos."""

    @abstractmethod
    def get_metadata(self) -> SourceMetadata: ...

    @abstractmethod
    def get_status(self) -> SourceStatus: ...
