from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
from evaluation.detection_metrics import box_iou, evaluate_detections

GT = [{"boxes": np.array([[0.1, 0.1, 0.3, 0.3], [0.5, 0.5, 0.9, 0.9]]), "labels": np.array([0, 1])},
      {"boxes": np.array([[0.2, 0.2, 0.4, 0.6]]), "labels": np.array([0])}]


def test_iou():
    a = np.array([[0, 0, 1, 1]], dtype=np.float32)
    b = np.array([[0, 0, 1, 1], [0.5, 0, 1.5, 1], [2, 2, 3, 3]], dtype=np.float32)
    assert box_iou(a, b) == pytest.approx(np.array([[1.0, 1 / 3, 0.0]]), abs=1e-6)


def test_perfect_predictions_give_ap_1():
    preds = [{"boxes": g["boxes"], "scores": np.ones(len(g["labels"])), "labels": g["labels"]} for g in GT]
    r = evaluate_detections(preds, GT, ["helmet", "vest", "boots"])
    assert r["mAP50"] == pytest.approx(1.0) and r["mAP50_95"] == pytest.approx(1.0)
    assert math.isnan(r["per_class"]["boots"]["AP50"])  # sin ejemplos: no cuenta en la media


def test_no_predictions_give_zero():
    preds = [{"boxes": np.zeros((0, 4)), "scores": np.zeros(0), "labels": np.zeros(0)} for _ in GT]
    assert evaluate_detections(preds, GT, ["helmet", "vest"])["mAP50"] == 0.0


def test_false_positive_ranked_first_lowers_ap():
    # Clase 0 tiene 2 GT. Predicciones: FP (0.9), TP (0.8), TP (0.7) -> precisión 0, 1/2, 2/3.
    preds = [{"boxes": np.array([[0.6, 0.6, 0.7, 0.7], [0.1, 0.1, 0.3, 0.3]]), "scores": np.array([0.9, 0.8]),
              "labels": np.array([0, 0])},
             {"boxes": np.array([[0.2, 0.2, 0.4, 0.6]]), "scores": np.array([0.7]), "labels": np.array([0])}]
    r = evaluate_detections(preds, GT, ["helmet"])
    # Envolvente: recall ≤0.5 -> 2/3, (0.5,1] -> 2/3  => AP50 = 2/3
    assert r["per_class"]["helmet"]["AP50"] == pytest.approx(2 / 3, abs=0.01)


def test_duplicate_detection_is_false_positive():
    preds = [{"boxes": np.array([[0.1, 0.1, 0.3, 0.3], [0.1, 0.1, 0.3, 0.3]]), "scores": np.array([0.9, 0.8]),
              "labels": np.array([0, 0])},
             {"boxes": np.zeros((0, 4)), "scores": np.zeros(0), "labels": np.zeros(0)}]
    r = evaluate_detections(preds, GT, ["helmet"])
    assert r["per_class"]["helmet"]["AP50"] == pytest.approx(0.5, abs=0.01)  # recall máx 0.5
