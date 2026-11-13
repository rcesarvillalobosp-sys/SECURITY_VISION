"""Exporta un checkpoint RT-DETR / RT-DETRv2 de Hugging Face Transformers a ONNX y lo registra.

    uv run python ml/export/export_rtdetr_hf.py --repo PekingU/rtdetr_v2_r18vd \
        --name rtdetr-v2-r18-coco --version 1 --class-map person=person

    # Modelo propio afinado (directorio local de save_pretrained):
    uv run python ml/export/export_rtdetr_hf.py --repo ml/training/runs/ppe-v1/best \
        --name rtdetr-v2-r18-ppe --version 1 --class-map-identity --license "propietario" ...

Verifica la exportación comparando ONNX Runtime con PyTorch en imágenes reales y escribe
model.yaml con sha256, etiquetas, licencias y la revisión exacta de los pesos.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while b := fh.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="repo de HF o directorio local")
    ap.add_argument("--revision", default=None, help="commit exacto del repo de HF (recomendado)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--class-map", nargs="*", default=[], help="etiqueta_modelo=clase_canónica")
    ap.add_argument("--class-map-identity", action="store_true", help="las etiquetas ya son canónicas")
    ap.add_argument("--license", default="Apache-2.0")
    ap.add_argument("--weights-license", default="Apache-2.0")
    ap.add_argument("--dataset-ref", default="COCO train2017")
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--verify-images", nargs="*", default=[])
    ap.add_argument("--opset", type=int, default=17)
    a = ap.parse_args()

    import torch
    from transformers import AutoConfig, AutoModelForObjectDetection

    from security_vision.core.domain.taxonomy import CanonicalClass

    revision = a.revision
    if revision is None and not Path(a.repo).exists():
        from huggingface_hub import HfApi

        revision = HfApi().model_info(a.repo).sha  # fija el commit exacto de los pesos
    cfg = AutoConfig.from_pretrained(a.repo, revision=revision)
    model = AutoModelForObjectDetection.from_pretrained(a.repo, revision=revision).eval()
    commit = revision or "local"
    labels = [cfg.id2label[i] for i in range(len(cfg.id2label))]
    if a.class_map_identity:
        class_map = {lbl: lbl for lbl in labels if lbl in {c.value for c in CanonicalClass}}
    else:
        class_map = dict(kv.split("=", 1) for kv in a.class_map)
    bad = {v for v in class_map.values()} - {c.value for c in CanonicalClass}
    if bad or set(class_map) - set(labels):
        sys.exit(f"class_map inválido: canónicas desconocidas {bad} / etiquetas inexistentes "
                 f"{set(class_map) - set(labels)}")

    class Wrapper(torch.nn.Module):
        def __init__(self, m: torch.nn.Module) -> None:
            super().__init__()
            self.m = m

        def forward(self, pixel_values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            out = self.m(pixel_values=pixel_values)
            return out.logits, out.pred_boxes

    from PIL import Image

    imgs = [Path(p) for p in a.verify_images][:4]
    inputs = [np.asarray(Image.open(p).convert("RGB").resize((a.size, a.size)), np.float32).transpose(2, 0, 1)[None]
              / 255.0 for p in imgs] or [np.random.default_rng(0).random((1, 3, a.size, a.size), np.float32)]
    # Referencia calculada ANTES de exportar: el trazado de torch.onnx.export puede alterar estado
    # interno del modelo (cachés), lo que falsearía la comparación posterior.
    references = []
    with torch.no_grad():
        for x in inputs:
            t_logits, t_boxes = Wrapper(model)(torch.from_numpy(x))
            references.append((t_logits[0].numpy().copy(), t_boxes[0].numpy().copy()))

    out_dir = ROOT / "ml/model_registry" / a.name / a.version
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = out_dir / "model.onnx"
    dummy = torch.rand(1, 3, a.size, a.size)
    with torch.no_grad():
        torch.onnx.export(Wrapper(model), (dummy,), str(onnx_path), input_names=["pixel_values"],
                          output_names=["logits", "pred_boxes"], opset_version=a.opset,
                          dynamic_axes={"pixel_values": {0: "batch"}, "logits": {0: "batch"},
                                        "pred_boxes": {0: "batch"}}, dynamo=False)

    # Verificación numérica ONNX Runtime (CPU) vs PyTorch
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    # Se comparan DETECCIONES (no tensores): la selección top-k de consultas de RT-DETR puede
    # ordenarlas distinto ante diferencias numéricas mínimas sin cambiar el resultado.
    def detections(logits: np.ndarray, boxes: np.ndarray, thr: float = 0.3) -> list[tuple]:
        p = 1 / (1 + np.exp(-logits))
        s, c = p.max(-1), p.argmax(-1)
        k = s >= thr
        return sorted(zip(c[k].tolist(), s[k].tolist(), boxes[k].tolist(), strict=True), key=lambda t: -t[1])

    def match(a: list[tuple], b: list[tuple]) -> float:
        """Cada detección de ``a`` con score >= 0.35 debe existir en ``b`` (umbral 0.25): misma clase,
        caja y score a < 1e-2. Tolera detecciones que cruzan el umbral por diferencias mínimas."""
        worst = 0.0
        for c, sc, bx in (d for d in a if d[1] >= 0.35):
            cands = [abs(sc - s2) + float(np.abs(np.array(bx) - np.array(b2)).max()) for c2, s2, b2 in b if c2 == c]
            best = min(cands, default=float("inf"))
            if best > 2e-2:
                sys.exit(f"detección sin equivalente (clase {c}, score {sc:.3f}): la exportación no es fiel")
            worst = max(worst, best)
        return worst

    max_diff, n_dets = 0.0, 0
    for x, (t_logits, t_boxes) in zip(inputs, references, strict=True):
        o_logits, o_boxes = sess.run(None, {"pixel_values": x})
        td = detections(t_logits, t_boxes, 0.25)
        od = detections(o_logits[0], o_boxes[0], 0.25)
        max_diff = max(max_diff, match(td, od), match(od, td))
        n_dets += sum(d[1] >= 0.35 for d in td)
    print(f"detecciones comparadas: {n_dets}; diferencia máxima (score/caja) ONNX vs PyTorch: {max_diff:.2e}")
    if max_diff > 1e-2:
        sys.exit("la exportación no reproduce el modelo original (diferencia > 1e-2)")

    spec = {
        "name": a.name, "version": a.version, "architecture": "rtdetr", "artifact": "model.onnx",
        "sha256": sha256(onnx_path), "input_size": [a.size, a.size], "labels": labels, "class_map": class_map,
        "score_threshold": a.threshold, "params": {"input_name": "pixel_values", "logits_name": "logits",
                                                   "boxes_name": "pred_boxes", "activation": "sigmoid"},
        "license": a.license, "weights_license": a.weights_license,
        "weights_source": f"{a.repo}@{commit}", "dataset_ref": a.dataset_ref,
        "notes": f"Exportado con torch {torch.__version__}, opset {a.opset}; verificación sobre {n_dets} detecciones "
                 f"ONNX vs PyTorch: max |Δ| = {max_diff:.1e}.",
    }
    (out_dir / "model.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"registrado: {a.name}@{a.version} -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
