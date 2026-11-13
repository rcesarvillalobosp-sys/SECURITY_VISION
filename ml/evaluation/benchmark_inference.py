"""Benchmark reproducible de inferencia y precisión por motor/dispositivo.

    uv run python ml/evaluation/benchmark_inference.py --model rtdetr-v2-r18-coco@1 \
        --configs onnxruntime:cpu onnxruntime:cuda onnxruntime:tensorrt openvino:openvino-cpu openvino:openvino-gpu \
        --eval-split val --classes person

- Latencia: detector completo (preproceso + inferencia + postproceso) y solo motor, sobre imágenes
  reales del dataset auditado (no tensores aleatorios), tras un calentamiento.
- Precisión: AP50 / AP50:95 por clase canónica sobre la partición indicada de la copia de trabajo
  (etiquetas canónicas), SOLO para las clases que el modelo produce (--classes).
- Si un motor/dispositivo no está disponible se registra el motivo; nunca se inventa una cifra.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from evaluation.detection_metrics import evaluate_detections  # noqa: E402

DEFAULT_IMAGES = ROOT / "ml/datasets/raw/ultralytics_construction_ppe/2026-11/extracted/construction-ppe/images"
DEFAULT_LABELS = ROOT / "ml/datasets/work/ultralytics_construction_ppe/2026-11/labels/construction-ppe/images"


def load_frames(paths: list[Path]):
    from security_vision.core.interfaces.video import Frame

    return [Frame(np.asarray(Image.open(p).convert("RGB")), frame_id=i, captured_at=datetime.now(UTC))
            for i, p in enumerate(paths)]


def load_gt(paths: list[Path], labels_root: Path, split: str, classes: list[str]):
    from security_vision.core.domain.taxonomy import CANONICAL_ORDER

    idx = {c.value: i for i, c in enumerate(CANONICAL_ORDER)}
    keep = {idx[c]: k for k, c in enumerate(classes)}
    gts = []
    for p in paths:
        boxes, labels = [], []
        f = labels_root / split / (p.stem + ".txt")
        for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
            c, cx, cy, w, h = line.split()
            if int(c) in keep:
                cx, cy, w, h = map(float, (cx, cy, w, h))
                boxes.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
                labels.append(keep[int(c)])
        gts.append({"boxes": np.array(boxes, np.float32).reshape(-1, 4), "labels": np.array(labels)})
    return gts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--configs", nargs="+", default=["onnxruntime:cpu", "onnxruntime:cuda"])
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--eval-split", default="val")
    ap.add_argument("--classes", nargs="*", default=["person"])
    ap.add_argument("--latency-images", type=int, default=50)
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--eval-threshold", type=float, default=0.05, help="umbral bajo para calcular AP")
    ap.add_argument("--out", type=Path, default=ROOT / "ml/evaluation/results")
    a = ap.parse_args()

    from security_vision.composition import build_inference_registry
    from security_vision.core.interfaces.inference import DetectionModel, DeviceRequest, InferenceEngine
    from security_vision.infrastructure.models.store import ModelStore

    reg = build_inference_registry()
    registered = ModelStore(ROOT / "ml/model_registry").get(a.model)
    split_imgs = sorted((a.images / a.eval_split).glob("*.jpg"))
    lat_frames = load_frames(split_imgs[: a.latency_images])
    eval_paths = split_imgs
    gts = load_gt(eval_paths, a.labels, a.eval_split, a.classes) if a.classes else None
    cam = str(uuid.uuid4())
    results = {"model": a.model, "weights_source": registered.spec.weights_source,
               "machine": {"cpu": platform.processor(), "python": platform.python_version()},
               "date": datetime.now(UTC).isoformat(), "images_dir": str(a.images), "eval_split": a.eval_split,
               "eval_images": len(eval_paths), "configs": []}
    for cfg in a.configs:
        engine_name, device = cfg.split(":", 1)
        row: dict = {"config": cfg}
        try:
            engine = reg.create(InferenceEngine, engine_name)
            t0 = time.perf_counter()
            engine.load_model(registered.artifact, DeviceRequest(preference=[device], allow_fallback=False))
            row["load_s"] = round(time.perf_counter() - t0, 2)
            spec = registered.spec.model_copy(update={"score_threshold": a.eval_threshold})
            model = reg.create(DetectionModel, spec.architecture, spec, engine)
            dev = engine.get_device()
            row["device"] = {"kind": dev.kind, "name": dev.name}
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            results["configs"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            continue
        for i in range(a.warmup):
            model.detect([lat_frames[i % len(lat_frames)]], [cam])
        e2e = []
        engine_before = engine.get_metrics().calls
        for i in range(a.runs):
            t0 = time.perf_counter()
            model.detect([lat_frames[i % len(lat_frames)]], [cam])
            e2e.append((time.perf_counter() - t0) * 1000)
        em = engine.get_metrics()
        row["latency_ms"] = {"e2e_p50": round(float(np.percentile(e2e, 50)), 2),
                             "e2e_p95": round(float(np.percentile(e2e, 95)), 2),
                             "engine_p50": round(em.p50_ms or 0, 2), "engine_p95": round(em.p95_ms or 0, 2),
                             "runs": em.calls - engine_before}
        row["throughput_fps_single_stream"] = round(1000 / row["latency_ms"]["e2e_p50"], 1)
        if gts is not None:
            preds = []
            for p in eval_paths:
                f = load_frames([p])[0]
                dets = [d for d in model.detect([f], [cam])[0] if d.class_name in a.classes]
                preds.append({"boxes": np.array([[d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2] for d in dets],
                                                np.float32).reshape(-1, 4),
                              "scores": np.array([d.confidence for d in dets], np.float32),
                              "labels": np.array([a.classes.index(d.class_name) for d in dets])})
            row["accuracy"] = evaluate_detections(preds, gts, a.classes)
        results["configs"].append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "accuracy"} | (
            {"mAP50": row["accuracy"]["mAP50"], "mAP50_95": row["accuracy"]["mAP50_95"]} if "accuracy" in row
            else {}), ensure_ascii=False), flush=True)
        engine.unload_model()
    a.out.mkdir(parents=True, exist_ok=True)
    out = a.out / f"benchmark_{a.model.replace('@', '_')}_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"resultados: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
