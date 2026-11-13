"""Exporta RF-DETR (solo variantes Apache-2.0: nano/small/medium/large) a ONNX y lo registra.

Se ejecuta en un entorno AISLADO con el paquete ``rfdetr`` (Apache-2.0), para no añadir sus
dependencias al producto:

    uv venv <dir> --python 3.12 && uv pip install --python <dir> "rfdetr==<versión>" onnxruntime pyyaml pillow
    <dir>/Scripts/python ml/export/export_rfdetr.py --size-variant nano --version 1 --images <img1> <img2>

No importa ``security_vision``; escribe model.yaml con el formato del registro.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import shutil
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
APACHE_VARIANTS = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "large": "RFDETRLarge"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while b := fh.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size-variant", choices=sorted(APACHE_VARIANTS), required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--workdir", type=Path, default=Path("rfdetr_export"))
    a = ap.parse_args()

    import rfdetr
    try:
        from rfdetr.utilities.class_names import COCO_CLASSES  # rfdetr >= 1.9
    except ImportError:
        from rfdetr.util.coco_classes import COCO_CLASSES

    model = getattr(rfdetr, APACHE_VARIANTS[a.size_variant])()
    res = int(model.model.resolution)
    a.workdir.mkdir(parents=True, exist_ok=True)
    model.export(output_dir=str(a.workdir))
    onnx_files = sorted(a.workdir.glob("*.onnx"))
    if not onnx_files:
        sys.exit("rfdetr no generó ningún .onnx")
    name = f"rfdetr-{a.size_variant}-coco"
    out_dir = ROOT / "ml/model_registry" / name / a.version
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "model.onnx"
    shutil.copyfile(onnx_files[0], dst)

    import onnxruntime as ort
    from PIL import Image

    sess = ort.InferenceSession(str(dst), providers=["CPUExecutionProvider"])
    ins = [i.name for i in sess.get_inputs()]
    outs = {o.name: o.shape for o in sess.get_outputs()}
    print("entradas:", ins, "salidas:", outs)
    boxes_name = next(n for n, s in outs.items() if s[-1] == 4)
    logits_name = next(n for n in outs if n != boxes_name)
    n_cls = sess.get_outputs()[[o.name for o in sess.get_outputs()].index(logits_name)].shape[-1]
    labels = [COCO_CLASSES.get(i, f"unused_{i}") for i in range(n_cls)]

    # Comprobación empírica del mapa de clases: en imágenes con personas, la clase más
    # segura debe ser "person". Si no, el registro no se escribe.
    mean = np.array([0.485, 0.456, 0.406], np.float32).reshape(1, 3, 1, 1)
    std = np.array([0.229, 0.224, 0.225], np.float32).reshape(1, 3, 1, 1)
    top_labels = []
    for p in a.images[:5]:
        x = np.asarray(Image.open(p).convert("RGB").resize((res, res)), np.float32).transpose(2, 0, 1)[None] / 255
        o = dict(zip([x.name for x in sess.get_outputs()], sess.run(None, {ins[0]: (x - mean) / std}), strict=True))
        probs = 1 / (1 + np.exp(-o[logits_name][0]))
        top_labels.append(labels[int(np.unravel_index(probs.argmax(), probs.shape)[1])])
    print("clase más segura por imagen:", top_labels)
    if a.images and top_labels.count("person") < max(1, len(top_labels) // 2):
        sys.exit("el mapa de clases no supera la comprobación con personas; revisar antes de registrar")

    spec = {
        "name": name, "version": a.version, "architecture": "rfdetr", "artifact": "model.onnx",
        "sha256": sha256(dst), "input_size": [res, res], "labels": labels, "class_map": {"person": "person"},
        "score_threshold": 0.4,
        "params": {"input_name": ins[0], "logits_name": logits_name, "boxes_name": boxes_name,
                   "activation": "sigmoid"},
        "license": "Apache-2.0", "weights_license": "Apache-2.0",
        "weights_source": f"rfdetr=={md.version('rfdetr')} {APACHE_VARIANTS[a.size_variant]} (pesos COCO)",
        "dataset_ref": "COCO (preentrenamiento Objects365 según el autor)",
        "notes": f"Exportado con rfdetr {md.version('rfdetr')} en entorno aislado; comprobación de clases: "
                 f"{top_labels}",
    }
    (out_dir / "model.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"registrado {name}@{a.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
