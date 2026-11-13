"""Supervisión de cámaras: un ciclo de captura aislado por cámara, con reconexión y métricas.

Garantías:
- Cada cámara corre en su propio hilo; cualquier excepción queda contenida en ese hilo.
- Reconexión con backoff exponencial + jitter; una cámara caída no afecta a las demás.
- La captura deposita en un ``FrameSlot`` (descarta lo antiguo), así el análisis lento nunca
  acumula retraso ni bloquea la captura.
- El módulo no conoce a los adaptadores: recibe una fábrica ``VideoSourceConfig -> VideoSource``.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from security_vision.core.interfaces.video import Frame, VideoSource, VideoSourceConfig, VideoSourceError
from security_vision.modules.video.frame_slot import FrameSlot

log = logging.getLogger(__name__)


class CameraState(StrEnum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    STALLED = "stalled"


@dataclass(frozen=True)
class CameraSpec:
    camera_id: str
    name: str
    provider: str
    source: VideoSourceConfig
    analysis_fps: float = 2.0
    slot_capacity: int = 1


@dataclass(frozen=True)
class ReconnectPolicy:
    initial_delay: float = 1.0
    max_delay: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.2  # ±20 %
    stall_timeout: float = 15.0  # sin fotogramas durante este tiempo => reconectar


@dataclass
class CameraStats:
    state: CameraState = CameraState.STOPPED
    frames: int = 0
    fps: float = 0.0  # media móvil exponencial
    connects: int = 0
    reconnects: int = 0
    connection_errors: int = 0
    read_errors: int = 0
    last_error: str | None = None
    last_frame_monotonic: float | None = None
    read_seconds_ewma: float = 0.0  # tiempo bloqueado esperando cada fotograma
    width: int | None = None
    height: int | None = None
    extra: dict[str, float] = field(default_factory=dict)


StatusCallback = Callable[[str, CameraState, str | None], None]
SourceFactory = Callable[[CameraSpec], VideoSource]


class CameraWorker:
    def __init__(self, spec: CameraSpec, factory: SourceFactory, policy: ReconnectPolicy | None = None,
                 on_status: StatusCallback | None = None) -> None:
        self.spec = spec
        self.slot: FrameSlot[Frame] = FrameSlot(spec.slot_capacity)
        self.stats = CameraStats()
        self._factory = factory
        self._policy = policy or ReconnectPolicy()
        self._on_status = on_status
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"camera-{spec.camera_id}", daemon=True)
        self._source: VideoSource | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.slot.close()
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.warning("la cámara %s no se detuvo en %.1fs (lectura bloqueada)", self.spec.camera_id, timeout)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def _set_state(self, state: CameraState, detail: str | None = None) -> None:
        if state is self.stats.state:
            return
        self.stats.state = state
        if detail:
            self.stats.last_error = detail
        if self._on_status:
            try:
                self._on_status(self.spec.camera_id, state, detail)
            except Exception:  # el callback nunca debe tumbar la captura
                log.exception("callback de estado falló")

    def _backoff(self, attempt: int) -> float:
        p = self._policy
        base = min(p.max_delay, p.initial_delay * p.multiplier ** max(0, attempt - 1))
        return base * random.uniform(1 - p.jitter, 1 + p.jitter)

    def _run(self) -> None:
        attempt = 0
        ever_connected = False
        while not self._stop.is_set():
            self._set_state(CameraState.RECONNECTING if ever_connected else CameraState.CONNECTING)
            try:
                self._source = self._factory(self.spec)
                self._source.connect()
            except VideoSourceError as exc:
                self.stats.connection_errors += 1
                attempt += 1
                self._set_state(CameraState.RECONNECTING, str(exc))
                self._stop.wait(self._backoff(attempt))
                continue
            except Exception as exc:  # aislamiento: un fallo inesperado no sale del hilo
                log.exception("fallo inesperado conectando %s", self.spec.camera_id)
                self.stats.connection_errors += 1
                attempt += 1
                self._set_state(CameraState.RECONNECTING, f"{type(exc).__name__}: {exc}")
                self._stop.wait(self._backoff(attempt))
                continue
            self.stats.connects += 1
            if ever_connected:
                self.stats.reconnects += 1
            ever_connected = True
            attempt = 0
            meta = self._source.get_metadata()
            self.stats.width, self.stats.height = meta.width, meta.height
            self._stream()
            self._safe_disconnect()
        self._safe_disconnect()
        self._set_state(CameraState.STOPPED)

    def _stream(self) -> None:
        assert self._source is not None
        last_frame = time.monotonic()
        first = True
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                frame = self._source.read_frame(timeout=1.0)
            except VideoSourceError as exc:
                self.stats.read_errors += 1
                self._set_state(CameraState.RECONNECTING, str(exc))
                return
            except Exception as exc:
                log.exception("fallo inesperado leyendo %s", self.spec.camera_id)
                self.stats.read_errors += 1
                self._set_state(CameraState.RECONNECTING, f"{type(exc).__name__}: {exc}")
                return
            now = time.monotonic()
            if frame is None:
                if now - last_frame > self._policy.stall_timeout:
                    self._set_state(CameraState.STALLED, "sin fotogramas")
                    return
                continue
            self.slot.put(frame)
            s = self.stats
            dt = now - last_frame
            if not first and dt > 0:
                s.fps = (1 / dt) if s.fps == 0 else 0.9 * s.fps + 0.1 * (1 / dt)
            s.read_seconds_ewma = 0.9 * s.read_seconds_ewma + 0.1 * (now - t0)
            s.frames += 1
            s.last_frame_monotonic = now
            last_frame = now
            if first:
                self._set_state(CameraState.STREAMING)
                first = False

    def _safe_disconnect(self) -> None:
        if self._source is not None:
            try:
                self._source.disconnect()
            except Exception:
                log.exception("error al desconectar %s", self.spec.camera_id)
            self._source = None


class CameraSupervisor:
    def __init__(self, factory: SourceFactory, policy: ReconnectPolicy | None = None,
                 on_status: StatusCallback | None = None) -> None:
        self._factory = factory
        self._policy = policy
        self._on_status = on_status
        self._workers: dict[str, CameraWorker] = {}
        self._lock = threading.Lock()

    def start(self, spec: CameraSpec) -> CameraWorker:
        with self._lock:
            if spec.camera_id in self._workers:
                raise ValueError(f"la cámara {spec.camera_id} ya está en marcha")
            worker = CameraWorker(spec, self._factory, self._policy, self._on_status)
            self._workers[spec.camera_id] = worker
        worker.start()
        return worker

    def stop(self, camera_id: str) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def apply(self, specs: list[CameraSpec]) -> dict[str, list[str]]:
        """Reconcilia las cámaras en marcha con la configuración deseada."""
        desired = {s.camera_id: s for s in specs}
        with self._lock:
            current = dict(self._workers)
        removed = [cid for cid in current if cid not in desired]
        changed = [cid for cid, s in desired.items() if cid in current and current[cid].spec != s]
        added = [cid for cid in desired if cid not in current]
        for cid in removed + changed:
            self.stop(cid)
        for cid in changed + added:
            self.start(desired[cid])
        return {"added": added, "changed": changed, "removed": removed}

    def worker(self, camera_id: str) -> CameraWorker | None:
        return self._workers.get(camera_id)

    def workers(self) -> dict[str, CameraWorker]:
        with self._lock:
            return dict(self._workers)

    def stop_all(self) -> None:
        for cid in list(self._workers):
            self.stop(cid)
