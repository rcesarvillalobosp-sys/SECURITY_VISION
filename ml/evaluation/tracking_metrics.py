"""Métricas de seguimiento multiobjeto: CLEAR-MOT (MOTA, IDSW) e IDF1. Sin dependencias externas salvo SciPy.

Entrada por fotograma: lista de (id, caja xyxy) de verdad y de predicción.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

Frame = Sequence[tuple[int, Sequence[float]]]


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + ab[None, :] - inter, 1e-12)


def evaluate_tracking(gt: Sequence[Frame], pred: Sequence[Frame], iou_thr: float = 0.5) -> dict:
    if len(gt) != len(pred):
        raise ValueError("gt y pred deben tener el mismo nº de fotogramas")
    n_gt = fp = fn = idsw = matches_total = 0
    last_match: dict[int, int] = {}  # gt_id -> pred_id del último emparejamiento
    pair_counts: dict[tuple[int, int], int] = defaultdict(int)
    gt_counts: dict[int, int] = defaultdict(int)
    pred_counts: dict[int, int] = defaultdict(int)
    for g, p in zip(gt, pred, strict=True):
        gids = [i for i, _ in g]
        pids = [i for i, _ in p]
        for i in gids:
            gt_counts[i] += 1
        for i in pids:
            pred_counts[i] += 1
        n_gt += len(g)
        gb = np.array([b for _, b in g], float).reshape(-1, 4)
        ious = _iou(gb, np.array([b for _, b in p], float).reshape(-1, 4))
        # CLEAR-MOT: se conservan los emparejamientos previos válidos y se resuelve el resto con húngaro
        cost = np.where(ious >= iou_thr, 1 - ious, 1e6)
        for gi, gid in enumerate(gids):
            if gid in last_match and last_match[gid] in pids:
                pj = pids.index(last_match[gid])
                if ious[gi, pj] >= iou_thr:
                    cost[gi, :] = 1e6
                    cost[:, pj] = 1e6
                    cost[gi, pj] = -1  # se fuerza a mantenerlo
        rows, cols = linear_sum_assignment(cost) if cost.size else ([], [])
        matched_g, matched_p = set(), set()
        for r, c in zip(rows, cols, strict=True):
            if cost[r, c] >= 1e6:
                continue
            gid, pid = gids[r], pids[c]
            if gid in last_match and last_match[gid] != pid:
                idsw += 1
            last_match[gid] = pid
            pair_counts[(gid, pid)] += 1
            matched_g.add(r)
            matched_p.add(c)
        matches_total += len(matched_g)
        fn += len(g) - len(matched_g)
        fp += len(p) - len(matched_p)
    # IDF1: correspondencia global uno a uno entre identidades que maximiza los aciertos
    gl, pl = sorted(gt_counts), sorted(pred_counts)
    idtp = 0
    if gl and pl:
        m = np.zeros((len(gl), len(pl)))
        for (g_id, p_id), n in pair_counts.items():
            m[gl.index(g_id), pl.index(p_id)] = n
        r, c = linear_sum_assignment(-m)
        idtp = int(m[r, c].sum())
    total_gt, total_pred = sum(gt_counts.values()), sum(pred_counts.values())
    idf1 = 2 * idtp / (total_gt + total_pred) if (total_gt + total_pred) else 1.0
    return {"MOTA": 1 - (fn + fp + idsw) / n_gt if n_gt else 1.0, "IDF1": idf1, "IDSW": idsw, "FP": fp, "FN": fn,
            "GT": n_gt, "matches": matches_total, "gt_ids": len(gl), "pred_ids": len(pl)}
