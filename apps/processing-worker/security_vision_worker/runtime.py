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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from security_vision.core.domain.cameras import Camera, SourceType
from security_vision.core.domain.compliance import CameraRules, ComplianceStatus
from security_vision.core.domain.incidents import NewIncident, violation_event_id
from security_vision.core.domain.vision import Detection
from security_vision.core.events.catalog import CameraStatusChanged, PersonComplianceChanged
from security_vision.core.interfaces.analysis import AnalyzedFrame, ObjectTracker, PPEAssociator
from security_vision.core.interfaces.cameras import MediaServer
from security_vision.core.interfaces.infrastructure import MessageBus, ObjectStorage, SecretCipher
from security_vision.core.interfaces.repositories import UnitOfWork
from security_vision.core.interfaces.video import Frame, VideoPublisher, VideoSource
from security_vision.core.registry import ProviderRegistry
from security_vision.infrastructure.video.probe import encode_jpeg
from security_vision.modules.analytics.live import StatsAccumulator, live_frame_payload
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
from security_vision.modules.detection.service import DetectionService
from security_vision.modules.incidents.evidence import FrameSnapshot, build_evidence
from security_vision.modules.incidents.service import IncidentService
from security_vision.modules.security_rules.engine import RuleBasedSecurityEvaluator
from security_vision.modules.tracking.analyzer import CameraAnalyzer

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


COLORS = {"person": (66, 135, 245), "helmet": (40, 200, 90), "safety_vest": (40, 200, 90),
          "safety_boot": (40, 200, 90), "gloves": (40, 200, 90), "goggles": (40, 200, 90)}


def encode_annotated_jpeg(rgb, detections: list[Detection], analyzed: AnalyzedFrame | None = None) -> bytes:
    """Snapshot de diagnóstico: personas con su ID temporal y EPP coloreado (rojo = "no_*",
    blanco = sin persona asociada, "?" = asignación ambigua)."""
    if analyzed is not None:
        return _encode_analyzed(rgb, analyzed)
    if not detections:
        return encode_jpeg(rgb, 75, 960)
    import io

    from PIL import Image, ImageDraw

    img = Image.fromarray(rgb)
    d = ImageDraw.Draw(img)
    lw = max(2, img.width // 400)
    for det in detections:
        color = (230, 40, 40) if det.class_name.startswith("no_") else COLORS.get(det.class_name, (240, 200, 0))
        box = (det.bbox.x1 * img.width, det.bbox.y1 * img.height, det.bbox.x2 * img.width, det.bbox.y2 * img.height)
        d.rectangle(box, outline=color, width=lw)
        d.text((box[0] + 3, max(0, box[1] - 12)), f"{det.class_name} {det.confidence:.2f}", fill=color)
    img.thumbnail((960, 960))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


STATUS_COLORS = {
    ComplianceStatus.CUMPLIMIENTO: (40, 200, 90),
    ComplianceStatus.EN_REVISION: (240, 200, 0),
    ComplianceStatus.POSIBLE_INCUMPLIMIENTO: (255, 140, 0),
    ComplianceStatus.INCUMPLIMIENTO_CONFIRMADO: (230, 40, 40),
    ComplianceStatus.NO_VERIFICABLE: (160, 160, 160),
}


def _encode_analyzed(rgb, af: AnalyzedFrame) -> bytes:
    import io

    from PIL import Image, ImageDraw

    img = Image.fromarray(rgb)
    d = ImageDraw.Draw(img)
    width, height = img.size
    lw = max(2, width // 400)

    def box(b):
        return (b.x1 * width, b.y1 * height, b.x2 * width, b.y2 * height)

    status = {p.track_id: p.status for p in af.evaluation.persons} if af.evaluation else {}
    for t in af.tracks:
        st = status.get(t.track_id)
        pcol = STATUS_COLORS.get(st, COLORS["person"]) if st else COLORS["person"]
        d.rectangle(box(t.bbox), outline=pcol, width=lw + 1)
        label = f"P{t.track_id}" + (f" {st.value}" if st else "")
        d.text((t.bbox.x1 * width + 3, t.bbox.y1 * height + 2), label, fill=pcol)
        for a in af.associations.by_person.get(t.track_id, []):
            col = (230, 40, 40) if a.item.class_name.startswith("no_") else (40, 200, 90)
            mark = "?" if a.ambiguous else ""
            d.rectangle(box(a.item.bbox), outline=col, width=lw)
            d.text((a.item.bbox.x1 * width, max(0, a.item.bbox.y1 * height - 12)),
                   f"P{t.track_id}:{a.item.class_name}{mark}", fill=col)
    for it in af.associations.unassigned:
        d.rectangle(box(it.bbox), outline=(255, 255, 255), width=lw)
    img.thumbnail((960, 960))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


class WorkerRuntime:
    def __init__(self, *, uow: Callable[[], UnitOfWork], cipher: SecretCipher, registry: ProviderRegistry,
                 storage: ObjectStorage, policy: CameraPolicy, bus: MessageBus | None,
                 media: MediaServer | None, publisher_factory: Callable[[str, float], VideoPublisher] | None,
                 reconnect: ReconnectPolicy | None = None, snapshot_seconds: float = 5.0,
                 detector: DetectionService | None = None,
                 tracker_factory: Callable[[], ObjectTracker] | None = None,
                 associator: PPEAssociator | None = None,
                 incidents: IncidentService | None = None) -> None:
        self.uow = uow
        self.cipher = cipher
        self.registry = registry
        self.storage = storage
        self.policy = policy
        self.bus = bus
        self.media = media
        self.publisher_factory = publisher_factory
        self.snapshot_seconds = snapshot_seconds
        self.detector = detector
        self.tracker_factory = tracker_factory
        self.associator = associator
        self.rules: dict[str, CameraRules] = {}
        self.analyzers: dict[str, CameraAnalyzer] = {}
        self.violations_confirmed: dict[tuple[str, str], int] = {}  # (cámara, epp) -> nº
        self.violations_closed: dict[tuple[str, str], int] = {}  # (cámara, motivo) -> nº
        self._events_q: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self.incidents = incidents
        self._incidents_q: asyncio.Queue = asyncio.Queue(maxsize=1_000)
        # Búfer de contexto por cámara: ~1 fotograma analizado por segundo de los últimos ~12 s
        self.history: dict[str, deque[FrameSnapshot]] = {}
        self.incidents_recorded = 0
        self.incident_errors = 0
        self.stats = StatsAccumulator()
        self._live_q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.live_dropped = 0
        # cámara -> (frame_id, detecciones, análisis) del último fotograma analizado
        self.latest: dict[str, tuple[int, list[Detection], AnalyzedFrame | None]] = {}
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
            new_rules = {str(c.id): await uow.rules.camera_rules(c.id) for c in cams}
        self.cameras = {str(c.id): c for c in cams}
        for cid, rules in new_rules.items():
            if self.rules.get(cid) != rules and cid in self.analyzers:
                # Reglas nuevas: se sustituye el evaluador (estado temporal reiniciado), sin tocar la captura
                self.analyzers[cid].evaluator = RuleBasedSecurityEvaluator(rules)
                log.info("reglas recargadas", extra={"camera_id": cid})
        self.rules = new_rules
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
        handle = None
        if self.detector is not None:
            det = self.detector
            analyzer = None
            if self.tracker_factory and self.associator:
                rules = self.rules.get(cid)
                evaluator = RuleBasedSecurityEvaluator(rules) if rules else None
                analyzer = CameraAnalyzer(cid, self.tracker_factory(), self.associator, evaluator)
                self.analyzers[cid] = analyzer

            def handle(frame: Frame, cid: str = cid) -> None:
                dets = det.detect(frame, cid)
                analyzed = analyzer.process(frame, dets) if analyzer else None
                self.latest[cid] = (frame.frame_id, dets, analyzed)
                if analyzed is not None and analyzed.evaluation is not None:
                    snap = FrameSnapshot(frame.data, analyzed, tuple(dets))
                    hist = self.history.setdefault(cid, deque(maxlen=12))
                    if not hist or (frame.captured_at - hist[-1].analyzed.frame_ts).total_seconds() >= 0.9:
                        hist.append(snap)
                    self._on_evaluation(cid, analyzed, snap)
                if analyzed is not None:
                    self.stats.add(analyzed)
                    if self.loop is not None:
                        self.loop.call_soon_threadsafe(self._put_live, live_frame_payload(analyzed))

        loop = AnalysisLoop(worker, handle)
        loop.start()
        self.analysis[cid] = loop
        if (self.media and self.publisher_factory and cam.mediamtx_path
                and cam.source_type is not SourceType.RTSP):
            url = self.media.read_url(cam.mediamtx_path)
            fps = min(cam.target_fps or 15.0, 15.0)
            pub = PublishLoop(worker, lambda u=url, f=fps: self.publisher_factory(u, f), fps)  # type: ignore[misc]
            pub.start()
            self.publishers[cid] = pub

    def _on_evaluation(self, cid: str, af: AnalyzedFrame, snap: FrameSnapshot | None = None) -> None:
        """Hilo de análisis: contabiliza y encola eventos para el bucle asyncio."""
        ev = af.evaluation
        assert ev is not None
        for v in ev.new_violations:
            key = (cid, v.ppe_class)
            self.violations_confirmed[key] = self.violations_confirmed.get(key, 0) + 1
            log.warning("incumplimiento confirmado", extra={"camera_id": cid, "track": v.track_id,
                                                            "ppe": v.ppe_class, "confidence": v.confidence})
        for c in ev.closed_violations:
            key = (cid, c.reason)
            self.violations_closed[key] = self.violations_closed.get(key, 0) + 1
        if self.loop is not None and self.incidents is not None:
            for v in ev.new_violations:
                if snap is not None:
                    job = ("confirmed", cid, v, snap, list(self.history.get(cid, ())))
                    self.loop.call_soon_threadsafe(self._put_incident, job)
            for c in ev.closed_violations:
                self.loop.call_soon_threadsafe(self._put_incident, ("closed", cid, c, None, []))
        if self.loop is None or not ev.transitions:
            return
        by_track = {p.track_id: p for p in ev.persons}
        for tr in ev.transitions:
            p = by_track.get(tr.track_id)
            event = PersonComplianceChanged(camera_id=UUID(cid), track_id=tr.track_id, previous=tr.previous,
                                            current=tr.current,
                                            ppe={k: v.value for k, v in (p.ppe if p else {}).items()})
            self.loop.call_soon_threadsafe(self._put_event, event)

    def _put_incident(self, job: tuple) -> None:
        try:
            self._incidents_q.put_nowait(job)
        except asyncio.QueueFull:
            self.incident_errors += 1
            log.error("cola de incidentes llena: se pierde un incidente (revisar la base de datos)")

    def _profile_version(self, cid: str, profile_id: str | None) -> int | None:
        rules = self.rules.get(cid)
        if not rules or not profile_id:
            return None
        profiles = [rules.default_profile] + [z.profile for z in rules.zones]
        return next((p.version for p in profiles if p is not None and p.id == profile_id), None)

    async def incident_writer(self) -> None:
        """Construye la evidencia y registra el incidente (idempotente; reintenta ante fallos de BD)."""
        while True:
            kind, cid, payload, snap, history = await self._incidents_q.get()
            for attempt in range(5):
                try:
                    if kind == "confirmed":
                        images = await asyncio.to_thread(build_evidence, payload, snap, history)
                        cam = self.cameras.get(cid)
                        model_id = self.detector.model_id if self.detector else None
                        new = NewIncident(violation=payload, camera_name=cam.name if cam else cid,
                                          model_id=model_id, profile_version=self._profile_version(
                                              cid, payload.profile_id), evidences=images)
                        incident, created = await self.incidents.record(new)  # type: ignore[union-attr]
                        if created:
                            self.incidents_recorded += 1
                            log.warning("incidente registrado", extra={"incident_id": str(incident.id),
                                                                       "camera_id": cid, "ppe": payload.ppe_class,
                                                                       "evidences": len(images)})
                    else:
                        await self.incidents.mark_ended(  # type: ignore[union-attr]
                            violation_event_id(payload.violation), payload.closed_at, payload.reason)
                    break
                except Exception:
                    log.exception("no se pudo registrar el incidente (intento %d)", attempt + 1)
                    await asyncio.sleep(2 ** attempt)
            else:
                self.incident_errors += 1

    def _put_live(self, payload: dict) -> None:
        try:
            self._live_q.put_nowait(payload)
        except asyncio.QueueFull:
            self.live_dropped += 1  # datos efímeros: se prefiere perder un fotograma a acumular retraso

    async def live_publisher(self) -> None:
        import json

        while True:
            payload = await self._live_q.get()
            if self.bus is None or not hasattr(self.bus, "publish_raw"):
                continue
            try:
                await self.bus.publish_raw("sv_live", json.dumps(payload, separators=(",", ":")))
            except Exception as exc:
                log.debug("no se pudo publicar el fotograma en vivo: %s", exc)

    async def stats_flusher(self, engine, interval: float = 30.0) -> None:
        from security_vision.infrastructure.database.repositories.stats import upsert_minutes

        while True:
            await asyncio.sleep(interval)
            rows = self.stats.drain()
            try:
                await upsert_minutes(engine, rows)
            except Exception:
                log.exception("no se pudieron guardar las estadísticas (%d filas)", len(rows))

    def _put_event(self, event: object) -> None:
        try:
            self._events_q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("cola de eventos llena: evento descartado")

    async def event_publisher(self) -> None:
        while True:
            event = await self._events_q.get()
            if self.bus is None:
                continue
            try:
                await self.bus.publish(event)  # type: ignore[arg-type]
            except Exception as exc:
                log.warning("no se pudo publicar %s: %s", type(event).__name__, exc)

    def _stop_aux(self, cid: str) -> None:
        if loop := self.analysis.pop(cid, None):
            loop.stop()
        self.latest.pop(cid, None)  # el tracker de la cámara se descarta con ella
        self.history.pop(cid, None)
        self.analyzers.pop(cid, None)
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
                last = self.latest.get(cid)
                fresh = bool(last and frame.frame_id - last[0] <= 30)
                overlay = last[1] if fresh and last else []
                analyzed = last[2] if fresh and last else None
                try:
                    jpeg = await asyncio.to_thread(encode_annotated_jpeg, frame.data, overlay, analyzed)
                    await asyncio.to_thread(self.storage.put, SNAPSHOT_KEY.format(camera_id=cid), jpeg,
                                            "image/jpeg")
                except Exception:
                    log.exception("snapshot falló para %s", cid)

    async def config_listener(self) -> None:
        if not self.bus:
            return
        while True:
            try:
                async for _ev in self.bus.subscribe(["camera.config_changed.v1", "rules.changed.v1"],
                                                    group="workers"):
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
