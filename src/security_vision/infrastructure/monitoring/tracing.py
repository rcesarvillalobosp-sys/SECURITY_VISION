"""Trazas distribuidas con OpenTelemetry (opcional).

Se activa con ``SV_OTEL_ENDPOINT`` (OTLP/HTTP, p. ej. ``http://127.0.0.1:4318``): Jaeger, Grafana Tempo o
un OpenTelemetry Collector. Sin él no se instala ningún proveedor y ``span()`` es un ``nullcontext``:
coste nulo en el ciclo de análisis.

En el worker se muestrea una fracción de los fotogramas (``SV_OTEL_SAMPLE_RATIO``): trazar cada
fotograma de cada cámara saturaría el colector sin aportar más información.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, nullcontext
from typing import Any

log = logging.getLogger(__name__)
_tracer: Any = None


def setup_tracing(service_name: str, endpoint: str | None, sample_ratio: float = 1.0,
                  exporter: Any = None) -> bool:
    """Configura el proveedor global. ``exporter`` permite inyectar uno (tests). Devuelve si quedó activo."""
    global _tracer
    if not endpoint and exporter is None:
        _tracer = None
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError:
        log.warning("SV_OTEL_ENDPOINT definido pero falta opentelemetry-sdk: trazas desactivadas")
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}),
                              sampler=ParentBased(TraceIdRatioBased(sample_ratio)))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    _tracer = provider.get_tracer("security_vision")
    log.info("trazas OpenTelemetry activas", extra={"endpoint": endpoint, "sample_ratio": sample_ratio})
    return True


def enabled() -> bool:
    return _tracer is not None


def span(name: str, **attributes: Any) -> AbstractContextManager[Any]:
    """Span hijo del actual (o raíz). Sin trazas configuradas: no hace nada."""
    if _tracer is None:
        return nullcontext()
    return _tracer.start_as_current_span(name, attributes={k: v for k, v in attributes.items() if v is not None})


def instrument_fastapi(app: Any) -> None:
    if _tracer is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        log.warning("falta opentelemetry-instrumentation-fastapi: sin trazas HTTP de la API")
        return
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
