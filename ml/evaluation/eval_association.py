"""Evaluación de la asociación EPP -> persona sobre imágenes reales de la partición de test.

El dataset no anota a qué persona pertenece cada EPP, así que no existe una "verdad" de asociación.
Se miden propiedades observables y se generan láminas para revisión visual humana:
- cobertura: % de EPP asignados a alguna persona (con cajas GT y con predicciones del modelo);
- ambigüedad: % de asignaciones marcadas como ambiguas (solapes);
- EPP huérfanos por clase (persona no anotada/detectada, encuadres parciales...).

    uv run python ml/evaluation/eval_association.py --model rtdetr-v2-r18-ppe-pilot@1 --sheets 8
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml/datasets/exports/ppe_v1"
CAM = uuid.UUID("01890000-0000-7000-8000-0000000000ee")
PALETTE = [(66, 135, 245), (245, 130, 48), (60, 180, 75), (240, 50, 230), (255, 225, 25), (70, 240, 240),
           (230, 25, 75), (170, 110, 40), (0, 128, 128), (128, 0, 0)]


def gt_detections(img: Path, size: tuple[int, int]):
    from security_vision.core.domain.geometry import BBox, Size
    from security_vision.core.domain.taxonomy import CANONICAL_ORDER
    from security_vision.core.domain.vision import Detection

    out = []
    lbl = DATA / "labels/test" / (img.stem + ".txt")
    for line in lbl.read_text(encoding="utf-8").splitlines():
        c, cx, cy, w, h = line.split()
        cx, cy, w, h = map(float, (cx, cy, w, h))
        x1, y1, x2, y2 = max(0, cx - w / 2), max(0, cy - h / 2), min(1, cx + w / 2), min(1, cy + h / 2)
        if x2 - x1 < 1e-4 or y2 - y1 < 1e-4:
            continue
        out.append(Detection(camera_id=CAM, frame_id=0, frame_ts=datetime.now(UTC), frame_size=Size(*size),
                             class_name=CANONICAL_ORDER[int(c)].value, bbox=BBox(x1, y1, x2, y2), confidence=1.0,
                             model_id="gt", inference_ms=0))
    return out


def as_tracks(persons):
    from security_vision.core.domain.vision import Track, TrackState

    return [Track(track_id=i + 1, camera_id=CAM, class_name="person", bbox=p.bbox, confidence=p.confidence,
                  state=TrackState.CONFIRMED, first_seen=p.frame_ts, last_seen=p.frame_ts)
            for i, p in enumerate(persons)]


def summarize(results) -> dict:
    total, assigned, ambiguous = Counter(), Counter(), Counter()
    for r, items in results:
        for it in items:
            total[it.class_name] += 1
        for lst in r.by_person.values():
            for a in lst:
                assigned[a.item.class_name] += 1
                ambiguous[a.item.class_name] += a.ambiguous
    per = {c: {"n": total[c], "asignados_%": round(100 * assigned[c] / total[c], 1),
               "ambiguos_%": round(100 * ambiguous[c] / max(1, assigned[c]), 1)} for c in sorted(total)}
    n, a, amb = sum(total.values()), sum(assigned.values()), sum(ambiguous.values())
    return {"items": n, "asignados_%": round(100 * a / max(1, n), 1), "ambiguos_%": round(100 * amb / max(1, a), 1),
            "por_clase": per}


def draw_sheet(img: Path, tracks, result, out: Path) -> None:
    im = Image.open(img).convert("RGB")
    im.thumbnail((1280, 1280))
    d = ImageDraw.Draw(im)
    W, H = im.size
    lw = max(2, W // 500)
    for t in tracks:
        col = PALETTE[(t.track_id - 1) % len(PALETTE)]
        b = t.bbox
        d.rectangle((b.x1 * W, b.y1 * H, b.x2 * W, b.y2 * H), outline=col, width=lw)
        d.text((b.x1 * W + 3, b.y1 * H + 2), f"P{t.track_id}", fill=col)
        pc = ((b.x1 + b.x2) / 2 * W, (b.y1 + b.y2) / 2 * H)
        for a in result.by_person.get(t.track_id, []):
            ib = a.item.bbox
            d.rectangle((ib.x1 * W, ib.y1 * H, ib.x2 * W, ib.y2 * H), outline=col, width=lw)
            ic = ((ib.x1 + ib.x2) / 2 * W, (ib.y1 + ib.y2) / 2 * H)
            d.line((pc, ic), fill=col, width=max(1, lw - 1))
            d.text((ib.x1 * W, ib.y2 * H), a.item.class_name + ("?" if a.ambiguous else ""), fill=col)
    for it in result.unassigned:
        ib = it.bbox
        d.rectangle((ib.x1 * W, ib.y1 * H, ib.x2 * W, ib.y2 * H), outline=(255, 255, 255), width=lw)
        d.text((ib.x1 * W, ib.y2 * H), "SIN PERSONA " + it.class_name, fill=(255, 255, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="si se indica, evalúa también con predicciones del modelo")
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--sheets", type=int, default=8)
    a = ap.parse_args()
    from security_vision.core.domain.vision import Detection  # noqa: F401
    from security_vision.core.interfaces.video import Frame
    from security_vision.modules.tracking.association import GeometricPPEAssociator

    assoc = GeometricPPEAssociator()
    imgs = sorted((DATA / "images/test").glob("*.jpg"))
    model = None
    if a.model:
        from security_vision.composition import build_inference_registry
        from security_vision.core.interfaces.inference import DetectionModel, DeviceRequest, InferenceEngine
        from security_vision.infrastructure.models.store import ModelStore

        reg = build_inference_registry()
        rm = ModelStore(ROOT / "ml/model_registry").get(a.model)
        eng = reg.create(InferenceEngine, "onnxruntime")
        eng.load_model(rm.artifact, DeviceRequest(preference=["cuda", "cpu"]))
        spec = rm.spec.model_copy(update={"score_threshold": a.threshold})
        model = reg.create(DetectionModel, spec.architecture, spec, eng)
    res_gt, res_pred = [], []
    sheets_dir = ROOT / "var/association_review"
    for i, img in enumerate(imgs):
        size = Image.open(img).size
        dets = gt_detections(img, size)
        tracks = as_tracks([d for d in dets if d.class_name == "person"])
        items = [d for d in dets if d.class_name != "person"]
        r = assoc.associate(tracks, items)
        res_gt.append((r, items))
        if i < a.sheets:
            draw_sheet(img, tracks, r, sheets_dir / f"gt_{img.stem}.jpg")
        if model is not None:
            frame = Frame(np.asarray(Image.open(img).convert("RGB")), frame_id=i, captured_at=datetime.now(UTC))
            pdets = model.detect([frame], [str(CAM)])[0]
            pt = as_tracks([d for d in pdets if d.class_name == "person"])
            pitems = [d for d in pdets if d.class_name != "person"]
            pr = assoc.associate(pt, pitems)
            res_pred.append((pr, pitems))
            if i < a.sheets:
                draw_sheet(img, pt, pr, sheets_dir / f"pred_{img.stem}.jpg")
    out = {"imagenes": len(imgs), "con_cajas_gt": summarize(res_gt)}
    if res_pred:
        out["con_predicciones"] = summarize(res_pred) | {"modelo": a.model, "umbral": a.threshold}
    out["laminas"] = str(sheets_dir)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    d = ROOT / "ml/evaluation/results"
    out_file = d / f"association_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    out_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
