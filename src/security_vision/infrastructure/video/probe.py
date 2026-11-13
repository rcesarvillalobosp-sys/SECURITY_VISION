"""Prueba de conectividad y snapshots: usa el registro de proveedores, en un hilo, con plazo total."""

from __future__ import annotations

import asyncio
import contextlib
import io
import time

import numpy as np
from PIL import Image

from security_vision.core.interfaces.cameras import ProbeResult, VideoProbe
from security_vision.core.interfaces.video import VideoSource, VideoSourceConfig
from security_vision.core.registry import ProviderRegistry


def encode_jpeg(rgb: np.ndarray, quality: int = 80, max_side: int | None = 1280) -> bytes:
    img = Image.fromarray(rgb)
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class RegistryVideoProbe(VideoProbe):
    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def _run(self, provider: str, config: VideoSourceConfig, with_snapshot: bool) -> ProbeResult:
        t0 = time.perf_counter()
        source = self._registry.create(VideoSource, provider, config)
        try:
            source.connect()
            frame = None
            for _ in range(50):  # algunos decodificadores necesitan varios paquetes
                frame = source.read_frame(timeout=2.0)
                if frame is not None:
                    break
            if frame is None:
                return ProbeResult(False, (time.perf_counter() - t0) * 1000, source.get_metadata(),
                                   "conectado pero sin fotogramas")
            jpeg = encode_jpeg(frame.data) if with_snapshot else None
            return ProbeResult(True, (time.perf_counter() - t0) * 1000, source.get_metadata(), None, jpeg)
        except Exception as exc:
            return ProbeResult(False, (time.perf_counter() - t0) * 1000, None, f"{type(exc).__name__}: {exc}")
        finally:
            with contextlib.suppress(Exception):
                source.disconnect()

    async def probe(self, provider: str, config: VideoSourceConfig, timeout: float,
                    with_snapshot: bool = False) -> ProbeResult:
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._run, provider, config, with_snapshot), timeout)
        except TimeoutError:
            # El hilo puede seguir bloqueado en FFmpeg hasta su propio read_timeout; no bloquea la API.
            return ProbeResult(False, timeout * 1000, None, f"sin respuesta en {timeout:.0f}s")
