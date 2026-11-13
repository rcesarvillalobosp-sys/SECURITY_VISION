"""Evaluación de ByteTrack en escenarios sintéticos estándar (varias semillas).

    uv run python ml/evaluation/eval_tracking.py --seeds 5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from evaluation.synthetic_tracking import STANDARD_SCENARIOS, H, W, make_scenario  # noqa: E402
from evaluation.tracking_metrics import evaluate_tracking  # noqa: E402


def run(seeds: int) -> dict:
    from security_vision.plugins.trackers.bytetrack import ByteTracker

    out = {}
    for name, kw in STANDARD_SCENARIOS.items():
        rows = []
        for seed in range(seeds):
            sc = make_scenario(name, seed=seed, **kw)
            tr = ByteTracker()
            pred = []
            for dets, ts in zip(sc.dets, sc.timestamps, strict=True):
                tracks = tr.update(dets, ts)
                pred.append([(t.track_id, [t.bbox.x1 * W, t.bbox.y1 * H, t.bbox.x2 * W, t.bbox.y2 * H])
                             for t in tracks])
            rows.append(evaluate_tracking(sc.gt, pred))
        out[name] = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in ("MOTA", "IDF1", "IDSW", "FP", "FN")}
        out[name]["gt_ids_mean"] = round(float(np.mean([r["gt_ids"] for r in rows])), 1)
        out[name]["pred_ids_mean"] = round(float(np.mean([r["pred_ids"] for r in rows])), 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    a = ap.parse_args()
    res = run(a.seeds)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    d = ROOT / "ml/evaluation/results"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"tracking_synthetic_{datetime.now(UTC):%Y%m%dT%H%M%S}.json").write_text(json.dumps(res, indent=1),
                                                                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
