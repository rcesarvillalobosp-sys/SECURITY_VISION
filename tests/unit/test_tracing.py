"""Trazas OpenTelemetry: desactivadas no hacen nada; activadas generan la jerarquía de spans del análisis."""

from __future__ import annotations

import pytest

from security_vision.infrastructure.monitoring import tracing

otel = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")


def test_disabled_tracing_is_a_noop():
    tracing.setup_tracing("x", endpoint=None)
    assert not tracing.enabled()
    with tracing.span("analysis.frame", camera_id="c") as s:
        assert s is None  # nullcontext: coste nulo en el ciclo de análisis


def test_spans_nest_per_frame_with_attributes():
    exporter = otel.InMemorySpanExporter()
    try:
        assert tracing.setup_tracing("worker-test", endpoint=None, sample_ratio=1.0, exporter=exporter)
        with tracing.span("analysis.frame", camera_id="cam-1", frame_id=7, zone=None):
            with tracing.span("detect"):
                pass
            with tracing.span("analyze"):
                pass
        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert set(spans) == {"analysis.frame", "detect", "analyze"}
        root = spans["analysis.frame"]
        assert dict(root.attributes) == {"camera_id": "cam-1", "frame_id": 7}  # los None se omiten
        assert spans["detect"].parent.span_id == root.context.span_id
        assert spans["analyze"].context.trace_id == root.context.trace_id
        assert root.resource.attributes["service.name"] == "worker-test"
    finally:
        tracing._tracer = None  # no dejar trazas activas para otros tests


def test_sampling_ratio_zero_records_nothing():
    exporter = otel.InMemorySpanExporter()
    try:
        # El proveedor global de OTel solo se fija una vez por proceso: se usa uno local para el muestreo
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        provider = TracerProvider(sampler=TraceIdRatioBased(0.0))
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracing._tracer = provider.get_tracer("t")
        for _ in range(20):
            with tracing.span("analysis.frame"):
                pass
        assert exporter.get_finished_spans() == ()
    finally:
        tracing._tracer = None


