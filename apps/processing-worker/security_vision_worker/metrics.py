"""Métricas Prometheus del worker, leídas en cada scrape de las estadísticas vivas (sin estado duplicado)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import ClassVar

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
        if det is not None:
            bs = CounterMetricFamily("sv_inference_batches", "Lotes inferidos por tamaño", labels=["size"])
            for size, k in sorted(det.stats.batch_sizes.items()):
                bs.add_metric([str(size)], k)
            yield bs
        stage = GaugeMetricFamily("sv_stage_ms", "Tiempo por etapa del análisis (ms, ventana deslizante)",
                                  labels=["stage", "quantile"])
        snaps = {**(det.timings.snapshot() if det is not None else {}), **self.rt.timings.snapshot()}
        for name, q in snaps.items():
            stage.add_metric([name, "0.5"], q["p50"])
            stage.add_metric([name, "0.95"], q["p95"])
            stage.add_metric([name, "mean"], q["mean"])
        yield stage


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
        yield self._threads_cpu(p)

    @staticmethod
    def _threads_cpu(p) -> Metric:
        """CPU acumulada por grupo de hilos (perfilado en producción sin herramientas externas).

        Los hilos de Python se agrupan por el prefijo de su nombre (camera, analysis, publish,
        detection...). Los hilos nativos (decodificador FFmpeg, ONNX Runtime/CUDA) no tienen nombre
        Python y se agrupan como ``native``.
        """
        import threading

        names = {t.native_id: t.name.split("-")[0] for t in threading.enumerate() if t.native_id}
        groups: dict[str, float] = {}
        for th in p.threads():
            g = names.get(th.id, "native")
            groups[g] = groups.get(g, 0.0) + th.user_time + th.system_time
        fam = CounterMetricFamily("sv_worker_thread_cpu_seconds", "CPU acumulada por grupo de hilos",
                                  labels=["group"])
        for g, v in sorted(groups.items()):
            fam.add_metric([g], v)
        return fam


class SystemCollector(Collector):
    """CPU y RAM del equipo, y estado de la(s) GPU NVIDIA por NVML (``nvidia-ml-py``, BSD-3).

    Incluye el estado de energía (P0 = máximo rendimiento ... P8 = reposo), los relojes y los motivos
    de limitación activos: en un portátil explican latencias de inferencia mayores de lo esperado.
    Sin NVML (otra GPU o sin el paquete) solo se publican CPU y RAM.
    """

    THROTTLE: ClassVar[dict[str, int]] = {
        "gpu_idle": 0x1, "sw_power_cap": 0x4, "hw_slowdown": 0x8, "sw_thermal": 0x20, "hw_thermal": 0x40,
        "hw_power_brake": 0x80}

    def __init__(self) -> None:
        import psutil

        self._psutil = psutil
        psutil.cpu_percent(None)
        self._nvml = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
        except Exception:  # sin GPU NVIDIA, sin driver o sin el paquete: se omite
            self._nvml = None

    def collect(self) -> Iterator[Metric]:
        cpu = GaugeMetricFamily("sv_system_cpu_percent", "CPU total del equipo (%)")
        cpu.add_metric([], self._psutil.cpu_percent(None))
        vm = self._psutil.virtual_memory()
        mem = GaugeMetricFamily("sv_system_memory_used_bytes", "RAM usada del equipo")
        mem.add_metric([], vm.total - vm.available)
        yield from (cpu, mem)
        if self._nvml is None:
            return
        n = self._nvml
        util = GaugeMetricFamily("sv_gpu_utilization_percent", "Uso de la GPU (%)", labels=["gpu", "name"])
        vram = GaugeMetricFamily("sv_gpu_memory_used_bytes", "VRAM usada", labels=["gpu", "name"])
        temp = GaugeMetricFamily("sv_gpu_temperature_celsius", "Temperatura de la GPU", labels=["gpu", "name"])
        pst = GaugeMetricFamily("sv_gpu_pstate", "Estado de energía (0 = máximo rendimiento)", labels=["gpu", "name"])
        clk = GaugeMetricFamily("sv_gpu_clock_mhz", "Reloj actual", labels=["gpu", "name", "domain"])
        thr = GaugeMetricFamily("sv_gpu_throttle_active", "Motivo de limitación activo (1/0)",
                                labels=["gpu", "name", "reason"])
        for i, h in enumerate(self._handles):
            try:
                name = n.nvmlDeviceGetName(h)
                name = name.decode() if isinstance(name, bytes) else name
                lab = [str(i), name]
                util.add_metric(lab, n.nvmlDeviceGetUtilizationRates(h).gpu)
                vram.add_metric(lab, n.nvmlDeviceGetMemoryInfo(h).used)
                temp.add_metric(lab, n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU))
                pst.add_metric(lab, n.nvmlDeviceGetPerformanceState(h))
                clk.add_metric([*lab, "graphics"], n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_GRAPHICS))
                clk.add_metric([*lab, "memory"], n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM))
                reasons = n.nvmlDeviceGetCurrentClocksEventReasons(h)
                for r, bit in self.THROTTLE.items():
                    thr.add_metric([*lab, r], 1.0 if reasons & bit else 0.0)
            except Exception:  # una lectura fallida no tumba /metrics
                continue
        yield from (util, vram, temp, pst, clk, thr)


def build_registry(runtime: WorkerRuntime) -> CollectorRegistry:
    reg = CollectorRegistry()
    reg.register(CameraCollector(runtime))
    reg.register(ProcessCollector())
    reg.register(SystemCollector())
    return reg
