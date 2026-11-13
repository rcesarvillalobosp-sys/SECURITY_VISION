"""Convierte un modelo registrado a FP16 (pesos y cálculo en media precisión; entradas/salidas en FP32).

En GPUs limitadas por ancho de banda de memoria (como una GTX 1650 de portátil con los relojes recortados)
reducir a la mitad los bytes movidos acelera la inferencia. La precisión se verifica después con
``ml/evaluation/benchmark_inference.py`` sobre el mismo conjunto que el modelo FP32: nunca se asume.

    uv run python ml/export/convert_fp16.py --model rtdetr-v2-r18-ppe-pilot@1 --version 1
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import onnx
import yaml
from onnxruntime.transformers.float16 import convert_float_to_float16

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "ml/model_registry"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def topo_sort(graph: onnx.GraphProto) -> None:
    """Reordena los nodos en orden topológico (el convertidor añade los Cast de E/S al final)."""
    available = {i.name for i in graph.input} | {t.name for t in graph.initializer} | {""}
    pending = list(graph.node)
    ordered = []
    while pending:
        progressed = False
        rest = []
        for n in pending:
            if all(i in available for i in n.input):
                ordered.append(n)
                available.update(n.output)
                progressed = True
            else:
                rest.append(n)
        if not progressed:
            raise RuntimeError(f"grafo con dependencias no resolubles: {rest[0].name}")
        pending = rest
    del graph.node[:]
    graph.node.extend(ordered)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="nombre@versión del modelo FP32 registrado")
    ap.add_argument("--version", default="1")
    ap.add_argument("--block", nargs="*", default=["TopK", "Softmax", "Sigmoid", "ReduceMean", "Pow", "Sqrt"],
                    help="operadores que se mantienen en FP32 (estabilidad numérica)")
    a = ap.parse_args()
    name, ver = a.model.split("@")
    src_dir = REG / name / ver
    spec = yaml.safe_load((src_dir / "model.yaml").read_text(encoding="utf-8"))
    src = src_dir / spec["artifact"]
    if sha256(src) != spec["sha256"]:
        sys.exit("el artefacto FP32 no coincide con su sha256")
    model = onnx.load(str(src))
    fp16 = convert_float_to_float16(model, keep_io_types=True, op_block_list=a.block)
    topo_sort(fp16.graph)
    out_name = f"{name}-fp16"
    out_dir = REG / out_name / a.version
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "model.onnx"
    onnx.save(fp16, str(out))
    onnx.checker.check_model(str(out))
    spec_out = dict(spec)
    spec_out.update(name=out_name, version=a.version, sha256=sha256(out))
    spec_out["weights_source"] = (f"conversión FP16 de {a.model} (onnxruntime.transformers.float16, keep_io_types, "
                                  f"en FP32: {', '.join(a.block)})")
    spec_out["notes"] = (f"Variante FP16 de {a.model} para GPU (Fase 9). Mismas clases y licencias. "
                         "Precisión verificada aparte frente al FP32 (ver metrics).")
    spec_out["metrics"] = {}
    (out_dir / "model.yaml").write_text(yaml.safe_dump(spec_out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{out} · {out.stat().st_size / 1e6:.1f} MB (FP32: {src.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
