"""Métricas Prometheus del worker, leídas en cada scrape de las estadísticas vivas (sin estado duplicado)."""

from __future__ import annotations

import time
from collections.abc import Iterator

from prometheus_client import CollectorRegistry
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from security_vision.modules.cameras.supervisor import CameraState

from .runtime import WorkerRuntime


class CameraCollector(Collector):
    def __init__(self, runtime: WorkerRuntime) -> None:
        self.rt = runtime

    def collect(self) -> Iterator[Metric]:
        lbl = ["camera_id", "camera"]
        up = GaugeMetricFamily("sv_camera_up", "1 si la cámara está entregando vídeo", labels=lbl)
        fps = GaugeMetricFamily("sv_camera_fps", "FPS de captura (media móvil)", labels=lbl)
        read = GaugeMetricFamily("sv_camera_read_seconds", "Tiempo medio esperando cada fotograma", labels=lbl)
        stale = GaugeMetricFamily("sv_camera_seconds_since_last_frame", "Segundos desde el último fotograma",
                                  labels=lbl)
        frames = CounterMetricFamily("sv_camera_frames", "Fotogramas capturados", labels=lbl)
        dropped = CounterMetricFamily("sv_camera_frames_dropped", "Fotogramas descartados por backpressure",
                                      labels=lbl)
        conn_err = CounterMetricFamily("sv_camera_connection_errors", "Errores de conexión", labels=lbl)
        read_err = CounterMetricFamily("sv_camera_read_errors", "Errores de lectura", labels=lbl)
        reconn = CounterMetricFamily("sv_camera_reconnects", "Reconexiones tras pérdida de stream", labels=lbl)
        analyzed = CounterMetricFamily("sv_analysis_frames", "Fotogramas tomados por el análisis", labels=lbl)
        age = GaugeMetricFamily("sv_analysis_frame_age_seconds",
                                "Antigüedad del fotograma al tomarlo el análisis (media móvil)", labels=lbl)
        published = CounterMetricFamily("sv_publish_frames", "Fotogramas publicados a MediaMTX", labels=lbl)
        now = time.monotonic()
        for cid, w in self.rt.supervisor.workers().items():
            v = [cid, w.spec.name]
            s = w.stats
            up.add_metric(v, 1.0 if s.state is CameraState.STREAMING else 0.0)
            fps.add_metric(v, s.fps)
            read.add_metric(v, s.read_seconds_ewma)
            if s.last_frame_monotonic is not None:
                stale.add_metric(v, now - s.last_frame_monotonic)
            frames.add_metric(v, s.frames)
            dropped.add_metric(v, w.slot.dropped)
            conn_err.add_metric(v, s.connection_errors)
            read_err.add_metric(v, s.read_errors)
            reconn.add_metric(v, s.reconnects)
            if a := self.rt.analysis.get(cid):
                analyzed.add_metric(v, a.stats.analyzed)
                age.add_metric(v, a.stats.frame_age_ewma)
            if p := self.rt.publishers.get(cid):
                published.add_metric(v, p.published)
        persons = GaugeMetricFamily("sv_camera_persons", "Personas en el último fotograma analizado", labels=lbl)
        tracked = GaugeMetricFamily("sv_camera_tracked_persons", "Personas con track confirmado", labels=lbl)
        unassigned = GaugeMetricFamily("sv_camera_ppe_unassigned", "EPP sin persona en el último análisis",
                                       labels=lbl)
        ambiguous = GaugeMetricFamily("sv_camera_ppe_ambiguous", "EPP con asignación ambigua en el último análisis",
                                      labels=lbl)
        for cid, (_fid, dets, af) in list(self.rt.latest.items()):
            w = self.rt.supervisor.worker(cid)
            if w is None:
                continue
            v = [cid, w.spec.name]
            persons.add_metric(v, sum(d.class_name == "person" for d in dets))
            if af is not None:
                tracked.add_metric(v, len(af.tracks))
                unassigned.add_metric(v, len(af.associations.unassigned))
                ambiguous.add_metric(v, sum(a.ambiguous for lst in af.associations.by_person.values() for a in lst))
        by_status = GaugeMetricFamily("sv_camera_persons_by_status", "Personas por estado de cumplimiento",
                                      labels=[*lbl, "status"])
        for cid, (_fid, _dets, af) in list(self.rt.latest.items()):
            w = self.rt.supervisor.worker(cid)
            if w is None or af is None or af.evaluation is None:
                continue
            counts: dict[str, int] = {}
            for p in af.evaluation.persons:
                counts[p.status.value] = counts.get(p.status.value, 0) + 1
            for st, n in counts.items():
                by_status.add_metric([cid, w.spec.name, st], n)
        confirmed = CounterMetricFamily("sv_violations_confirmed", "Incumplimientos confirmados",
                                        labels=["camera_id", "ppe"])
        for (cid, ppe), n in list(self.rt.violations_confirmed.items()):
            confirmed.add_metric([cid, ppe], n)
        closed = CounterMetricFamily("sv_violations_closed", "Incumplimientos cerrados", labels=["camera_id", "reason"])
        for (cid, reason), n in list(self.rt.violations_closed.items()):
            closed.add_metric([cid, reason], n)
        inc = CounterMetricFamily("sv_incidents_recorded", "Incidentes registrados con evidencia")
        inc.add_metric([], self.rt.incidents_recorded)
        inc_err = CounterMetricFamily("sv_incident_errors", "Incidentes que no se pudieron registrar")
        inc_err.add_metric([], self.rt.incident_errors)
        yield from (up, fps, read, stale, frames, dropped, conn_err, read_err, reconn, analyzed, age, published,
                    persons, tracked, unassigned, ambiguous, by_status, confirmed, closed, inc, inc_err)
        det = self.rt.detector
        if det is not None:
            m = det.model.engine.get_metrics()
            dev = m.device.kind if m.device else "?"
            inf = GaugeMetricFamily("sv_inference_ms", "Latencia de inferencia (p50/p95, ms)",
                                    labels=["model", "device", "quantile"])
            if m.p50_ms is not None:
                inf.add_metric([det.model_id, dev, "0.5"], m.p50_ms)
                inf.add_metric([det.model_id, dev, "0.95"], m.p95_ms or 0.0)
            calls = CounterMetricFamily("sv_inference_calls", "Llamadas de inferencia", labels=["model", "device"])
            calls.add_metric([det.model_id, dev], m.calls)
            errs = CounterMetricFamily("sv_inference_errors", "Errores de inferencia", labels=["model"])
            errs.add_metric([det.model_id], det.stats.errors)
            by_cls = CounterMetricFamily("sv_detections", "Detecciones por clase canónica", labels=["model", "class"])
            for cls, n in det.stats.by_class.items():
                by_cls.add_metric([det.model_id, cls], n)
            yield from (inf, calls, errs, by_cls)


class ProcessCollector(Collector):
    """CPU y RAM del proceso (psutil si está instalado; si no, se omite sin fallar).

    Se reutiliza el mismo ``psutil.Process``: ``cpu_percent`` mide desde la llamada anterior,
    así que un objeto nuevo en cada lectura devolvería siempre 0.
    """

    def __init__(self) -> None:
        try:
            import psutil

            self._proc = psutil.Process()
            self._proc.cpu_percent(None)
        except ImportError:
            self._proc = None

    def collect(self) -> Iterator[Metric]:
        if self._proc is None:
            return
        p = self._proc
        cpu = GaugeMetricFamily("sv_worker_cpu_percent", "CPU del proceso worker (%)")
        cpu.add_metric([], p.cpu_percent(None))
        rss = GaugeMetricFamily("sv_worker_memory_rss_bytes", "Memoria residente del worker")
        rss.add_metric([], p.memory_info().rss)
        yield cpu
        yield rss


def build_registry(runtime: WorkerRuntime) -> CollectorRegistry:
    reg = CollectorRegistry()
    reg.register(CameraCollector(runtime))
    reg.register(ProcessCollector())
    return reg
