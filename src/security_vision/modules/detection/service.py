"""Servicio de detección compartido por todas las cámaras de un worker.

Una sola instancia del modelo (la VRAM es limitada) protegida por un candado; las cámaras se
turnan. El micro-batching entre cámaras llegará en la Fase 9 sin cambiar esta interfaz.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field

from security_vision.core.domain.vision import Detection
from security_vision.core.interfaces.inference import DetectionModel
from security_vision.core.interfaces.video import Frame


@dataclass
class DetectionStats:
    calls: int = 0
    errors: int = 0
    by_class: Counter[str] = field(default_factory=Counter)


class DetectionService:
    def __init__(self, model: DetectionModel) -> None:
        self.model = model
        self.stats = DetectionStats()
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self.model.spec.model_id

    def detect(self, frame: Frame, camera_id: str) -> list[Detection]:
        with self._lock:
            try:
                dets = self.model.detect([frame], [camera_id])[0]
            except Exception:
                self.stats.errors += 1
                raise
            self.stats.calls += 1
        self.stats.by_class.update(d.class_name for d in dets)
        return dets
