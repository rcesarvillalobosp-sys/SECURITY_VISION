"""Puerto de fuentes de vídeo. Implementaciones en ``security_vision.plugins.video_sources``."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
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


class Frame:
    """Fotograma RGB HxWx3 uint8. Contenedor propio: no acopla el sistema a OpenCV ni a PyAV.

    Puede crearse **perezoso** (``Frame.lazy``): guarda una función que produce los píxeles RGB y solo la
    ejecuta la primera vez que alguien lee ``data``. La captura entrega 15 a 25 fotogramas/s pero el análisis
    usa 2 a 5: convertir a RGB solo los que se usan ahorra la mitad de la CPU de captura (Fase 9).
    """

    __slots__ = ("_data", "_height", "_loader", "_width", "captured_at", "frame_id", "source_pts")

    def __init__(self, data: np.ndarray, frame_id: int, captured_at: datetime,
                 source_pts: float | None = None) -> None:
        self._data: np.ndarray | None = data
        self._loader: Callable[[], np.ndarray] | None = None
        self._height, self._width = int(data.shape[0]), int(data.shape[1])
        self.frame_id = frame_id
        self.captured_at = captured_at  # UTC
        self.source_pts = source_pts

    @classmethod
    def lazy(cls, loader: Callable[[], np.ndarray], width: int, height: int, frame_id: int,
             captured_at: datetime, source_pts: float | None = None) -> Frame:
        f = cls.__new__(cls)
        f._data, f._loader = None, loader
        f._width, f._height = int(width), int(height)
        f.frame_id, f.captured_at, f.source_pts = frame_id, captured_at, source_pts
        return f

    @property
    def data(self) -> np.ndarray:
        d = self._data
        if d is None:
            # Si dos hilos llegan a la vez ambos convierten (mismo resultado): carrera benigna, sin candado
            loader = self._loader
            if loader is None:
                raise RuntimeError("fotograma sin datos")
            d = loader()
            self._data, self._loader = d, None
        return d

    @property
    def materialized(self) -> bool:
        return self._data is not None

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def __repr__(self) -> str:
        return f"Frame(id={self.frame_id}, {self._width}x{self._height}, materializado={self.materialized})"


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


class VideoPublisher(ABC):
    """Publica fotogramas hacia un servidor de medios (p. ej. cámara USB -> MediaMTX)."""

    @abstractmethod
    def publish(self, frame: Frame) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
