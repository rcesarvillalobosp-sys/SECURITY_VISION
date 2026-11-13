"""Utilidades compartidas por los motores de inferencia."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from security_vision.core.interfaces.inference import DeviceInfo, EngineMetrics, ModelArtifact


class ModelIntegrityError(RuntimeError):
    pass


def verify_artifact(artifact: ModelArtifact) -> Path:
    """Nunca se carga un modelo cuyo sha256 no coincide con el registrado."""
    h = hashlib.sha256()
    with artifact.path.open("rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    if h.hexdigest() != artifact.sha256:
        raise ModelIntegrityError(f"sha256 de {artifact.path.name} no coincide con el registro")
    return artifact.path


class LatencyRecorder:
    def __init__(self, window: int = 1000) -> None:
        self._samples: deque[float] = deque(maxlen=window)
        self._calls = 0
        self._lock = threading.Lock()

    def time(self) -> _Timer:
        return _Timer(self)

    def add(self, ms: float) -> None:
        with self._lock:
            self._samples.append(ms)
            self._calls += 1

    def metrics(self, device: DeviceInfo | None) -> EngineMetrics:
        with self._lock:
            arr = np.array(self._samples) if self._samples else None
            calls = self._calls
        if arr is None:
            return EngineMetrics(calls, None, None, device)
        return EngineMetrics(calls, float(np.percentile(arr, 50)), float(np.percentile(arr, 95)), device)


class _Timer:
    def __init__(self, rec: LatencyRecorder) -> None:
        self.rec = rec
        self.ms = 0.0

    def __enter__(self) -> _Timer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000
        self.rec.add(self.ms)
