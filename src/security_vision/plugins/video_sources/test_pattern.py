"""Fuente de patrón de prueba (equivalente a ``videotestsrc``). Solo para pruebas y diagnóstico.

URI: ``testpattern://?width=640&height=360&fps=15&fail_after=0&fail_connect=0``
- ``fail_after=N``: tras N fotogramas la lectura falla (simula una caída de red).
- ``fail_connect=1``: la conexión siempre falla (simula una cámara apagada).
Su nombre deja claro que no es una cámara real; nunca debe usarse en producción.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import numpy as np

from security_vision.core.interfaces.video import (
    Frame,
    SourceCapabilities,
    SourceMetadata,
    SourceStatus,
    VideoSource,
    VideoSourceConfig,
    VideoSourceError,
)


class TestPatternSource(VideoSource):
    provider_name: ClassVar[str] = "testpattern"
    __test__ = False  # evita que pytest la confunda con una clase de tests

    def __init__(self, config: VideoSourceConfig) -> None:
        super().__init__(config)
        q = {k: v[0] for k, v in parse_qs(urlsplit(config.uri).query).items()}
        self.width = int(q.get("width", config.width or 640))
        self.height = int(q.get("height", config.height or 360))
        self.fps = float(q.get("fps", config.fps or 15))
        self.fail_after = int(q.get("fail_after", 0))
        self.fail_connect = q.get("fail_connect", "0") == "1"
        self._status = SourceStatus.DISCONNECTED
        self._frame_id = 0
        self._since_connect = 0
        self._next_t = 0.0
        self.connect_calls = 0

    @classmethod
    def capabilities(cls) -> SourceCapabilities:
        return SourceCapabilities(schemes=frozenset({"testpattern"}))

    def connect(self) -> None:
        self.connect_calls += 1
        if self.fail_connect:
            self._status = SourceStatus.ERROR
            raise VideoSourceError("conexión rechazada (simulada)")
        self._status = SourceStatus.CONNECTED
        self._since_connect = 0
        self._next_t = time.monotonic()

    def disconnect(self) -> None:
        self._status = SourceStatus.DISCONNECTED

    def read_frame(self, timeout: float) -> Frame | None:
        if self._status is not SourceStatus.CONNECTED:
            raise VideoSourceError("no conectada")
        if self.fail_after and self._since_connect >= self.fail_after:
            self._status = SourceStatus.ERROR
            raise VideoSourceError("stream interrumpido (simulado)")
        delay = self._next_t - time.monotonic()
        if delay > timeout:
            return None
        if delay > 0:
            time.sleep(delay)
        self._next_t = max(self._next_t + 1.0 / self.fps, time.monotonic() - 1.0)
        self._frame_id += 1
        self._since_connect += 1
        x = np.arange(self.width, dtype=np.int64)
        shift = (self._frame_id * 4) % self.width
        row = (((x + shift) % self.width) * 255 // max(1, self.width - 1)).astype(np.uint8)
        data = np.empty((self.height, self.width, 3), dtype=np.uint8)
        data[:, :, 0] = row
        data[:, :, 1] = row[::-1]
        data[:, :, 2] = (self._frame_id * 3) % 256
        return Frame(data=data, frame_id=self._frame_id, captured_at=datetime.now(UTC))

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata("raw", self.width, self.height, self.fps)

    def get_status(self) -> SourceStatus:
        return self._status
