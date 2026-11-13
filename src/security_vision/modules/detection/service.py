"""Servicio de detección compartido por todas las cámaras de un worker.

Una sola instancia del modelo (la VRAM es limitada). Desde la Fase 9:

- **Preproceso en paralelo:** cada cámara prepara su fotograma (redimensionar, normalizar) en su propio
  hilo, FUERA del turno de GPU. Antes se hacía dentro del candado y las cámaras se esperaban también
  para trabajo de CPU.
- **Micro-batching voraz:** un hilo despachador toma TODAS las peticiones que haya en cola (hasta
  ``max_batch``) y las infiere en una sola llamada. Con poca carga la cola tiene una petición y no se
  añade espera; bajo carga las peticiones se agrupan y la GPU trabaja con lotes. Opcionalmente,
  ``max_wait_ms`` espera unos milisegundos a que llegue alguna más.

La interfaz pública (``detect(frame, camera_id)``) no cambia.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import Counter
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from security_vision.core.domain.vision import Detection
from security_vision.core.interfaces.inference import DetectionModel
from security_vision.core.interfaces.video import Frame
from security_vision.modules.analytics.timings import StageTimings


@dataclass
class DetectionStats:
    calls: int = 0  # fotogramas inferidos
    batches: int = 0  # llamadas al modelo
    errors: int = 0
    by_class: Counter[str] = field(default_factory=Counter)
    batch_sizes: Counter[int] = field(default_factory=Counter)


@dataclass
class _Request:
    frame: Frame
    camera_id: str
    prepared: Any
    enqueued: float
    future: Future = field(default_factory=Future)


class DetectionService:
    def __init__(self, model: DetectionModel, *, max_batch: int = 4, max_wait_ms: float = 0.0) -> None:
        self.model = model
        self.max_batch = max(1, max_batch)
        self.max_wait_ms = max(0.0, max_wait_ms)
        self.stats = DetectionStats()
        self.timings = StageTimings()
        self._q: queue.Queue[_Request | None] = queue.Queue()
        # Compatibilidad: modelos sin preproceso separado (p. ej. dobles de test) se infieren tal cual
        self._prepare = getattr(model, "prepare", None)
        self._detect_prepared = getattr(model, "detect_prepared", None)
        self._closed = False
        self._lock = threading.Lock()  # se mantiene mientras se infiere un lote (liberar el modelo lo espera)
        self._thread = threading.Thread(target=self._run, name="detection-dispatcher", daemon=True)
        self._thread.start()

    @property
    def model_id(self) -> str:
        return self.model.spec.model_id

    def detect(self, frame: Frame, camera_id: str) -> list[Detection]:
        if self._closed:
            raise RuntimeError("servicio de detección cerrado")
        prepared = None
        if self._prepare is not None and self._detect_prepared is not None:
            with self.timings.measure("preprocess"):
                prepared = self._prepare(frame)  # en el hilo de la cámara: en paralelo con las demás
        req = _Request(frame, camera_id, prepared, time.perf_counter())
        self._q.put(req)
        return req.future.result(timeout=60)  # nunca bloquear una cámara para siempre

    # ------------------------------------------------------------------ despachador
    def _collect(self, first: _Request) -> list[_Request]:
        batch = [first]
        deadline = time.perf_counter() + self.max_wait_ms / 1000
        while len(batch) < self.max_batch:
            try:
                timeout = deadline - time.perf_counter()
                item = self._q.get_nowait() if timeout <= 0 else self._q.get(timeout=timeout)
            except queue.Empty:
                break
            if item is None:
                self._q.put(None)  # que el bucle principal vea la orden de parada
                break
            batch.append(item)
        return batch

    def _run(self) -> None:
        while True:
            first = self._q.get()
            if first is None:
                self._fail_pending()
                return
            batch = self._collect(first)
            start = time.perf_counter()
            for r in batch:
                self.timings.add("detect_wait", (start - r.enqueued) * 1000)  # cola: contención de la GPU
            try:
                with self._lock:
                    frames = [r.frame for r in batch]
                    cams = [r.camera_id for r in batch]
                    if self._detect_prepared is not None and all(r.prepared is not None for r in batch):
                        results = self._detect_prepared([r.prepared for r in batch], frames, cams)
                    else:
                        results = self.model.detect(frames, cams)
                    stage = dict(getattr(self.model, "last_stage_ms", {}) or {})
            except BaseException as exc:
                self.stats.errors += len(batch)
                for r in batch:
                    r.future.set_exception(exc)
                continue
            self.stats.batches += 1
            self.stats.calls += len(batch)
            self.stats.batch_sizes[len(batch)] += 1
            for k, v in stage.items():
                if k != "preprocess":  # el preproceso ya se midió en el hilo de cada cámara
                    self.timings.add(k, v)
            self.timings.add("batch_size", float(len(batch)))
            for r, dets in zip(batch, results, strict=True):
                self.stats.by_class.update(d.class_name for d in dets)
                r.future.set_result(dets)

    def _fail_pending(self) -> None:
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                return
            if item is not None:
                item.future.set_exception(RuntimeError("servicio de detección cerrado (cambio de modelo)"))

    def close(self, timeout: float = 5.0) -> None:
        """Deja de aceptar peticiones, termina las pendientes y para el despachador."""
        self._closed = True
        self._q.put(None)
        self._thread.join(timeout)
