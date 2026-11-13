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
        yield from (up, fps, read, stale, frames, dropped, conn_err, read_err, reconn, analyzed, age, published)


class ProcessCollector(Collector):
    """CPU y RAM del proceso (psutil si está instalado; si no, se omite sin fallar)."""

    def collect(self) -> Iterator[Metric]:
        try:
            import psutil
        except ImportError:
            return
        p = psutil.Process()
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
