"""Métricas de detección estilo COCO (AP con interpolación de 101 puntos) sin dependencias externas.

Entrada por imagen:
    pred = {"boxes": [N,4] xyxy normalizado, "scores": [N], "labels": [N]}
    gt   = {"boxes": [M,4] xyxy normalizado, "labels": [M]}
Devuelve AP50 y AP50:95 por clase y sus medias (solo sobre clases con ejemplos reales).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)
RECALL_POINTS = np.linspace(0, 1, 101)


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0])
    iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2])
    iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-12)


def _ap(tp: np.ndarray, scores: np.ndarray, n_gt: int) -> float:
    if n_gt == 0:
        return float("nan")
    if len(scores) == 0:
        return 0.0
    order = np.argsort(-scores, kind="stable")
    tp = tp[order]
    ctp = np.cumsum(tp)
    cfp = np.cumsum(1 - tp)
    recall = ctp / n_gt
    precision = ctp / np.maximum(ctp + cfp, 1e-12)
    # envolvente monótona de la precisión
    precision = np.maximum.accumulate(precision[::-1])[::-1]
    idx = np.searchsorted(recall, RECALL_POINTS, side="left")
    return float(np.mean([precision[i] if i < len(precision) else 0.0 for i in idx]))


def evaluate_detections(preds: Sequence[dict], gts: Sequence[dict], class_names: Sequence[str]) -> dict:
    if len(preds) != len(gts):
        raise ValueError("preds y gts deben tener la misma longitud")
    per_class: dict[str, dict] = {}
    for c, name in enumerate(class_names):
        scores_all: list[float] = []
        tps_all = [[] for _ in IOU_THRESHOLDS]
        n_gt = 0
        for p, g in zip(preds, gts, strict=True):
            gb = np.asarray(g["boxes"], dtype=np.float32).reshape(-1, 4)[np.asarray(g["labels"]) == c]
            pm = np.asarray(p["labels"]) == c
            pb = np.asarray(p["boxes"], dtype=np.float32).reshape(-1, 4)[pm]
            ps = np.asarray(p["scores"], dtype=np.float32)[pm]
            n_gt += len(gb)
            order = np.argsort(-ps, kind="stable")
            pb, ps = pb[order], ps[order]
            ious = box_iou(pb, gb)
            for ti, thr in enumerate(IOU_THRESHOLDS):
                matched = np.zeros(len(gb), dtype=bool)
                tp = np.zeros(len(pb), dtype=np.float32)
                for i in range(len(pb)):
                    if len(gb) == 0:
                        break
                    cand = np.where(~matched, ious[i], -1.0)
                    j = int(np.argmax(cand))
                    if cand[j] >= thr:
                        matched[j] = True
                        tp[i] = 1.0
                tps_all[ti].append(tp)
            scores_all.extend(ps.tolist())
        scores = np.array(scores_all, dtype=np.float32)
        aps = [_ap(np.concatenate(t) if t else np.zeros(0), scores, n_gt) for t in tps_all]
        per_class[name] = {"gt": n_gt, "AP50": aps[0], "AP50_95": float(np.mean(aps)) if n_gt else float("nan")}
    valid = [v for v in per_class.values() if v["gt"] > 0]
    return {
        "mAP50": float(np.mean([v["AP50"] for v in valid])) if valid else float("nan"),
        "mAP50_95": float(np.mean([v["AP50_95"] for v in valid])) if valid else float("nan"),
        "per_class": per_class,
    }
