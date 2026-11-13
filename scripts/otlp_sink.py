"""Receptor OTLP/HTTP mínimo para verificar las trazas sin desplegar Jaeger/Tempo (desarrollo y pruebas).

Decodifica cada ``ExportTraceServiceRequest`` (protobuf) y escribe un resumen por span en JSONL:
servicio, nombre, trace/span/padre, duración y atributos.

    uv run python scripts/otlp_sink.py --port 4318 --out var/otlp_spans.jsonl
    SV_OTEL_ENDPOINT=http://127.0.0.1:4318 uv run sv-worker
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)


def _value(v) -> object:
    kind = v.WhichOneof("value")
    return getattr(v, kind) if kind else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4318)
    ap.add_argument("--out", type=Path, default=Path("var/otlp_spans.jsonl"))
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path != "/v1/traces":
                self.send_response(404)
                self.end_headers()
                return
            req = ExportTraceServiceRequest()
            req.ParseFromString(body)
            with a.out.open("a", encoding="utf-8") as f:
                for rs in req.resource_spans:
                    res = {kv.key: _value(kv.value) for kv in rs.resource.attributes}
                    for ss in rs.scope_spans:
                        for sp in ss.spans:
                            f.write(json.dumps({
                                "service": res.get("service.name"), "name": sp.name,
                                "trace_id": sp.trace_id.hex(), "span_id": sp.span_id.hex(),
                                "parent_id": sp.parent_span_id.hex() or None,
                                "duration_ms": round((sp.end_time_unix_nano - sp.start_time_unix_nano) / 1e6, 3),
                                "attributes": {kv.key: _value(kv.value) for kv in sp.attributes},
                            }, ensure_ascii=False) + "\n")
            out = ExportTraceServiceResponse().SerializeToString()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args: object) -> None:
            pass

    print(f"OTLP/HTTP en http://127.0.0.1:{a.port}/v1/traces -> {a.out}", flush=True)
    HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
