"""Latencia del motor de inferencia aislado: llamadas seguidas frente a espaciadas, y por tamaño de lote.

Sirve para separar el coste del modelo del de la gestión de energía de la GPU (en un portátil, con
llamadas espaciadas la GPU baja de estado de energía) y para decidir el tamaño de lote del worker.

    uv run python ml/evaluation/engine_latency.py --model rtdetr-v2-r18-ppe-pilot@1 --device cuda
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def gpu_state() -> str:
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=pstate,clocks.gr,clocks.mem,clocks_event_reasons.active",
                               "--format=csv,noheader"], capture_output=True, text=True, timeout=5).stdout.strip()
    except OSError:
        return "?"


def main() -> None:
    from security_vision.core.interfaces.inference import DeviceRequest
    from security_vision.infrastructure.models.store import ModelStore
    from security_vision.plugins.inference_engines.onnxruntime_engine import OnnxRuntimeEngine
    from security_vision.plugins.inference_engines.openvino_engine import OpenVinoEngine

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="rtdetr-v2-r18-ppe-pilot@1")
    ap.add_argument("--engine", default="onnxruntime", choices=["onnxruntime", "openvino"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batches", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--spaced-ms", type=float, default=500.0)
    ap.add_argument("--options", default="{}", help="opciones del motor en JSON (p. ej. proveedor/fp16)")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    m = ModelStore(ROOT / "ml/model_registry").get(a.model)
    engine = (OnnxRuntimeEngine if a.engine == "onnxruntime" else OpenVinoEngine)(**json.loads(a.options))
    t0 = time.perf_counter()
    engine.load_model(m.artifact, DeviceRequest(preference=[a.device]))
    load_s = time.perf_counter() - t0
    h, w = m.spec.input_size
    name = m.spec.params.get("input_name", "pixel_values")
    rng = np.random.default_rng(0)
    res: dict = {"model": a.model, "engine": a.engine, "device": engine.get_device().name, "label": a.label,
                 "options": json.loads(a.options), "load_s": round(load_s, 2), "at": datetime.now(UTC).isoformat()}
    for b in a.batches:
        x = rng.random((b, 3, h, w), dtype=np.float32)
        for _ in range(5):
            engine.predict({name: x})
        times = []
        for _ in range(a.runs):
            t = time.perf_counter()
            engine.predict({name: x})
            times.append((time.perf_counter() - t) * 1000)
        state = gpu_state()
        p50 = statistics.median(times)
        r = res[f"batch_{b}"] = {"p50_ms": round(p50, 1), "per_image_ms": round(p50 / b, 1),
                                 "p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 1), "gpu_state": state}
        print(f"lote {b}: p50 {r['p50_ms']} ms ({r['per_image_ms']} ms/imagen) · {state}", flush=True)
    x = rng.random((1, 3, h, w), dtype=np.float32)
    spaced = []
    for _ in range(max(10, a.runs // 2)):
        time.sleep(a.spaced_ms / 1000)
        t = time.perf_counter()
        engine.predict({name: x})
        spaced.append((time.perf_counter() - t) * 1000)
    res["spaced_batch_1"] = {"every_ms": a.spaced_ms, "p50_ms": round(statistics.median(spaced), 1),
                             "gpu_state": gpu_state()}
    sp = res["spaced_batch_1"]
    print(f"lote 1 cada {a.spaced_ms:.0f} ms: p50 {sp['p50_ms']} ms · {sp['gpu_state']}")
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%S}"
    out = ROOT / "ml/evaluation/results" / f"engine_latency_{a.label or a.device}_{stamp}.json"
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
