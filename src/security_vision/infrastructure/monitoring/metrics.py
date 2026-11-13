"""Métricas Prometheus. Un registro por instancia de aplicación (evita colisiones en tests)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)
_START = time.monotonic()


class _UptimeCollector(Collector):
    """Tiempo de actividad. CPU/RAM/GPU por proceso se añadirán con psutil/pynvml en la Fase 9."""

    def collect(self) -> Iterator[Metric]:
        g = GaugeMetricFamily("sv_process_uptime_seconds", "Segundos desde el arranque del proceso")
        g.add_metric([], time.monotonic() - _START)
        yield g


@dataclass
class ApiMetrics:
    registry: CollectorRegistry
    requests: Counter
    latency: Histogram
    in_flight: Gauge
    logins: Counter

    def render(self) -> bytes:
        return generate_latest(self.registry)


def create_api_metrics() -> ApiMetrics:
    reg = CollectorRegistry()
    reg.register(_UptimeCollector())
    return ApiMetrics(
        registry=reg,
        requests=Counter("sv_http_requests", "Peticiones HTTP", ["method", "route", "status"], registry=reg),
        latency=Histogram("sv_http_request_duration_seconds", "Latencia HTTP", ["method", "route"],
                          buckets=LATENCY_BUCKETS, registry=reg),
        in_flight=Gauge("sv_http_in_flight", "Peticiones en curso", registry=reg),
        logins=Counter("sv_auth_logins", "Intentos de login", ["outcome"], registry=reg),
    )
