"""Tiempo de ejecución del worker: cámaras, estado, snapshots, publicación y consumidor de análisis.

El consumidor de análisis de esta fase NO ejecuta inferencia (llega en la Fase 3): toma el
fotograma más reciente a la frecuencia de análisis configurada y mide su antigüedad, para
validar el backpressure con cifras reales.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from security_vision.core.domain.cameras import Camera, SourceType
from security_vision.core.events.catalog import CameraStatusChanged
from security_vision.core.interfaces.cameras import MediaServer
from security_vision.core.interfaces.infrastructure import MessageBus, ObjectStorage, SecretCipher
from security_vision.core.interfaces.repositories import UnitOfWork
from security_vision.core.interfaces.video import Frame, VideoPublisher, VideoSource
from security_vision.core.registry import ProviderRegistry
from security_vision.infrastructure.video.probe import encode_jpeg
from security_vision.modules.cameras.service import (
    SNAPSHOT_KEY,
    CameraPolicy,
    media_source_url,
    provider_for,
    source_config,
)
from security_vision.modules.cameras.supervisor import (
    CameraSpec,
    CameraState,
    CameraSupervisor,
    CameraWorker,
    ReconnectPolicy,
)

log = logging.getLogger("security_vision.worker")


@dataclass
class AnalysisStats:
    analyzed: int = 0
    frame_age_ewma: float = 0.0  # s entre la captura y su toma por el análisis
    last_frame_id: int = 0


class AnalysisLoop:
    """Consumidor por cámara a ``analysis_fps``. Fase 3 sustituye ``handle`` por inferencia."""

    def __init__(self, worker: CameraWorker, handle: Callable[[Frame], None] | None = None) -> None:
        self.worker = worker
        self.stats = AnalysisStats()
        self._handle = handle
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"analysis-{worker.spec.camera_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(3)

    def _run(self) -> None:
        period = 1.0 / self.worker.spec.analysis_fps
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame = self.worker.slot.get_latest(timeout=period)
            if frame is not None and frame.frame_id != self.stats.last_frame_id:
                age = (datetime.now(UTC) - frame.captured_at).total_seconds()
                s = self.stats
                s.frame_age_ewma = age if s.analyzed == 0 else 0.9 * s.frame_age_ewma + 0.1 * age
                s.analyzed += 1
                s.last_frame_id = frame.frame_id
                if self._handle:
                    try:
                        self._handle(frame)
                    except Exception:
                        log.exception("error en el análisis de %s", self.worker.spec.camera_id)
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))


class PublishLoop:
    """Reenvía los fotogramas de una cámara local (USB/archivo/prueba) a su ruta de MediaMTX."""

    def __init__(self, worker: CameraWorker, make_publisher: Callable[[], VideoPublisher], fps: float) -> None:
        self.worker = worker
        self._make = make_publisher
        self._fps = fps
        self._stop = threading.Event()
        self.published = 0
        self.errors = 0
        self.encoder: str | None = None
        self._thread = threading.Thread(target=self._run, name=f"publish-{worker.spec.camera_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(3)

    def _run(self) -> None:
        pub: VideoPublisher | None = None
        last_id = -1
        period = 1.0 / self._fps
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame = self.worker.slot.peek_latest()  # no consume: el análisis sigue recibiendo todo
            if frame is not None and frame.frame_id != last_id:
                try:
                    pub = pub or self._make()
                    pub.publish(frame)
                    self.encoder = getattr(pub, "encoder", None)
                    self.published += 1
                    last_id = frame.frame_id
                except Exception as exc:
                    self.errors += 1
                    log.warning("publicación a MediaMTX falló (%s): %s", self.worker.spec.camera_id, exc)
                    if pub:
                        pub.close()
                    pub = None
                    self._stop.wait(2.0)
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
        if pub:
            pub.close()


class WorkerRuntime:
    def __init__(self, *, uow: Callable[[], UnitOfWork], cipher: SecretCipher, registry: ProviderRegistry,
                 storage: ObjectStorage, policy: CameraPolicy, bus: MessageBus | None,
                 media: MediaServer | None, publisher_factory: Callable[[str, float], VideoPublisher] | None,
                 reconnect: ReconnectPolicy | None = None, snapshot_seconds: float = 5.0) -> None:
        self.uow = uow
        self.cipher = cipher
        self.registry = registry
        self.storage = storage
        self.policy = policy
        self.bus = bus
        self.media = media
        self.publisher_factory = publisher_factory
        self.snapshot_seconds = snapshot_seconds
        self.loop: asyncio.AbstractEventLoop | None = None
        self._status_q: asyncio.Queue[tuple[str, CameraState, str | None]] = asyncio.Queue()
        self.supervisor = CameraSupervisor(self._make_source, reconnect, on_status=self._on_status)
        self.analysis: dict[str, AnalysisLoop] = {}
        self.publishers: dict[str, PublishLoop] = {}
        self.cameras: dict[str, Camera] = {}

    # --------------------------------------------------------------- composición
    def _make_source(self, spec: CameraSpec) -> VideoSource:
        return self.registry.create(VideoSource, spec.provider, spec.source)

    def _on_status(self, camera_id: str, state: CameraState, detail: str | None) -> None:
        # Llamado desde hilos de captura: se traslada al bucle asyncio de forma segura.
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._status_q.put_nowait, (camera_id, state, detail))

    def spec_for(self, cam: Camera) -> CameraSpec:
        via_media = bool(self.media and cam.mediamtx_path and cam.source_type is SourceType.RTSP)
        cfg = source_config(cam, self.cipher, self.policy, self.media, via_media=via_media)
        return CameraSpec(camera_id=str(cam.id), name=cam.name, provider=provider_for(cam, self.policy),
                          source=cfg, analysis_fps=cam.analysis_fps)

    # --------------------------------------------------------------- reconciliación
    async def reconcile(self) -> dict[str, list[str]]:
        async with self.uow() as uow:
            cams = await uow.cameras.list(enabled_only=True)
        self.cameras = {str(c.id): c for c in cams}
        if self.media:
            for c in cams:
                if c.mediamtx_path:
                    try:
                        await self.media.ensure_path(c.mediamtx_path, media_source_url(c, self.cipher))
                    except Exception as exc:
                        log.warning("MediaMTX no disponible para %s: %s", c.id, exc)
        specs = [self.spec_for(c) for c in cams]
        before = set(self.supervisor.workers())
        result = await asyncio.to_thread(self.supervisor.apply, specs)
        for cid in result["removed"] + result["changed"]:
            self._stop_aux(cid)
        for cid in result["added"] + result["changed"]:
            self._start_aux(cid)
        if result["added"] or result["removed"] or result["changed"]:
            log.info("cámaras reconciliadas", extra={k: len(v) for k, v in result.items()} | {
                "running_before": len(before)})
        return result

    def _start_aux(self, cid: str) -> None:
        worker = self.supervisor.worker(cid)
        cam = self.cameras.get(cid)
        if worker is None or cam is None:
            return
        loop = AnalysisLoop(worker)
        loop.start()
        self.analysis[cid] = loop
        if (self.media and self.publisher_factory and cam.mediamtx_path
                and cam.source_type is not SourceType.RTSP):
            url = self.media.read_url(cam.mediamtx_path)
            fps = min(cam.target_fps or 15.0, 15.0)
            pub = PublishLoop(worker, lambda u=url, f=fps: self.publisher_factory(u, f), fps)  # type: ignore[misc]
            pub.start()
            self.publishers[cid] = pub

    def _stop_aux(self, cid: str) -> None:
        if loop := self.analysis.pop(cid, None):
            loop.stop()
        if pub := self.publishers.pop(cid, None):
            pub.stop()

    # --------------------------------------------------------------- tareas
    async def status_writer(self) -> None:
        while True:
            cid, state, detail = await self._status_q.get()
            at = datetime.now(UTC)
            try:
                async with self.uow() as uow:
                    await uow.cameras.record_status(UUID(cid), state.value, detail, at)
                    await uow.commit()
                if self.bus:
                    await self.bus.publish(CameraStatusChanged(camera_id=UUID(cid), status=state.value,
                                                               detail=(detail or None) and detail[:300]))
            except Exception:
                log.exception("no se pudo registrar el estado de %s", cid)

    async def snapshot_writer(self) -> None:
        while True:
            await asyncio.sleep(self.snapshot_seconds)
            for cid, worker in self.supervisor.workers().items():
                frame = worker.slot.peek_latest()
                if frame is None or worker.stats.state is not CameraState.STREAMING:
                    continue
                try:
                    jpeg = await asyncio.to_thread(encode_jpeg, frame.data, 75, 960)
                    await asyncio.to_thread(self.storage.put, SNAPSHOT_KEY.format(camera_id=cid), jpeg,
                                            "image/jpeg")
                except Exception:
                    log.exception("snapshot falló para %s", cid)

    async def config_listener(self) -> None:
        if not self.bus:
            return
        while True:
            try:
                async for _ev in self.bus.subscribe(["camera.config_changed.v1"], group="workers"):
                    await self.reconcile()
            except Exception as exc:
                log.warning("escucha de configuración interrumpida (%s); reintento en 5s", exc)
                await asyncio.sleep(5)

    async def periodic_reconcile(self, seconds: float) -> None:
        while True:
            await asyncio.sleep(seconds)
            try:
                await self.reconcile()
            except Exception:
                log.exception("reconciliación periódica falló")

    def shutdown(self) -> None:
        for cid in list(self.analysis) + list(self.publishers):
            self._stop_aux(cid)
        self.supervisor.stop_all()
