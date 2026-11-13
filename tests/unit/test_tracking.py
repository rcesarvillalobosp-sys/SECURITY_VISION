from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
from evaluation.synthetic_tracking import STANDARD_SCENARIOS, H, W, make_scenario
from evaluation.tracking_metrics import evaluate_tracking

from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Detection, Track, TrackState
from security_vision.modules.tracking.association import GeometricPPEAssociator
from security_vision.plugins.trackers.bytetrack import ByteTrackConfig, ByteTracker

CAM = UUID("01890000-0000-7000-8000-000000000001")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def det(x1, y1, x2, y2, cls="person", conf=0.9, k=0, cam=CAM) -> Detection:
    return Detection(camera_id=cam, frame_id=k, frame_ts=T0 + timedelta(seconds=k / 3), frame_size=Size(1280, 720),
                     class_name=cls, bbox=BBox(x1, y1, x2, y2), confidence=conf, model_id="t@1", inference_ms=0)


def ts(k: int) -> datetime:
    return T0 + timedelta(seconds=k / 3)


# --- ByteTrack -------------------------------------------------------------------------

def test_stable_id_for_walking_person_and_confirmation_delay():
    tr = ByteTracker()
    ids = []
    for k in range(10):
        x = 0.1 + 0.02 * k
        out = tr.update([det(x, 0.3, x + 0.08, 0.8, k=k)], ts(k))
        ids.append([t.track_id for t in out])
    assert ids[0] == []  # tentativo hasta min_hits=2 (evita parpadeos de falsos positivos)
    assert all(i == ids[1] for i in ids[1:]) and len(ids[1]) == 1


def test_short_occlusion_keeps_identity_and_long_one_expires():
    tr = ByteTracker(ByteTrackConfig(max_lost_seconds=2.0))
    for k in range(4):
        out = tr.update([det(0.4, 0.3, 0.48, 0.8, k=k)], ts(k))
    tid = out[0].track_id
    for k in range(4, 7):  # 1 s sin detecciones
        assert tr.update([], ts(k)) == []
    assert tr.get_tracks()[0].state is TrackState.LOST
    back = tr.update([det(0.4, 0.3, 0.48, 0.8, k=7)], ts(7))
    assert [t.track_id for t in back] == [tid]
    for k in range(8, 16):  # > 2 s
        tr.update([], ts(k))
    assert tr.get_tracks() == []


def test_low_confidence_detection_keeps_track_alive():
    """La idea de ByteTrack: una detección de baja confianza (oclusión parcial) mantiene el track."""
    tr = ByteTracker()
    for k in range(3):
        tr.update([det(0.4, 0.3, 0.48, 0.8, k=k)], ts(k))
    out = tr.update([det(0.405, 0.3, 0.485, 0.8, conf=0.3, k=3)], ts(3))
    assert len(out) == 1 and out[0].confidence == pytest.approx(0.3)
    # pero una detección baja NUNCA abre un track nuevo
    assert ByteTracker().update([det(0.1, 0.1, 0.2, 0.5, conf=0.3)], ts(0)) == []


def test_ignores_non_person_and_rejects_other_camera():
    tr = ByteTracker()
    tr.update([det(0.1, 0.1, 0.2, 0.5, cls="helmet")], ts(0))
    assert tr.get_tracks() == []
    tr.update([det(0.1, 0.1, 0.2, 0.5)], ts(0))
    with pytest.raises(ValueError):
        tr.update([det(0.1, 0.1, 0.2, 0.5, cam=UUID(int=5))], ts(1))


@pytest.mark.parametrize("name,min_mota,min_idf1,max_idsw", [
    ("tranquilo_3fps", 0.88, 0.90, 1.5),
    ("cruce_3fps", 0.90, 0.90, 0.5),
    ("rapido_2fps", 0.75, 0.70, 4.0),
    ("concurrido_3fps", 0.75, 0.78, 6.0),
])
def test_synthetic_regression(name, min_mota, min_idf1, max_idsw):
    """Umbrales de regresión fijados a partir de la medición del 2026-11-13 (5 semillas)."""
    res = []
    for seed in range(5):
        sc = make_scenario(name, seed=seed, **STANDARD_SCENARIOS[name])
        tr = ByteTracker()
        pred = [[(t.track_id, [t.bbox.x1 * W, t.bbox.y1 * H, t.bbox.x2 * W, t.bbox.y2 * H])
                 for t in tr.update(d, s)] for d, s in zip(sc.dets, sc.timestamps, strict=True)]
        res.append(evaluate_tracking(sc.gt, pred))
    mean = {k: sum(r[k] for r in res) / len(res) for k in ("MOTA", "IDF1", "IDSW")}
    assert mean["MOTA"] >= min_mota and mean["IDF1"] >= min_idf1 and mean["IDSW"] <= max_idsw, mean


def test_tracking_metrics_detect_id_switch():
    box = [0, 0, 10, 10]
    gt = [[(1, box)], [(1, box)], [(1, box)]]
    pred = [[(7, box)], [(7, box)], [(8, box)]]
    r = evaluate_tracking(gt, pred)
    assert r["IDSW"] == 1 and r["MOTA"] == pytest.approx(2 / 3) and r["IDF1"] == pytest.approx(2 / 3)


# --- Asociación EPP -> persona ---------------------------------------------------------

def person(tid: int, x1, y1, x2, y2) -> Track:
    return Track(track_id=tid, camera_id=CAM, class_name="person", bbox=BBox(x1, y1, x2, y2), confidence=0.9,
                 state=TrackState.CONFIRMED, first_seen=T0, last_seen=T0)


A = GeometricPPEAssociator()


def test_each_item_goes_to_the_right_person():
    p1, p2 = person(1, 0.10, 0.20, 0.20, 0.80), person(2, 0.30, 0.20, 0.40, 0.80)
    items = [det(0.12, 0.18, 0.18, 0.26, "helmet"), det(0.32, 0.18, 0.38, 0.26, "no_helmet"),
             det(0.10, 0.35, 0.20, 0.55, "safety_vest"), det(0.11, 0.76, 0.14, 0.82, "safety_boot"),
             det(0.16, 0.76, 0.19, 0.82, "safety_boot")]
    r = A.associate([p1, p2], items)
    got = {tid: sorted(a.item.class_name for a in lst) for tid, lst in r.by_person.items()}
    assert got == {1: ["helmet", "safety_boot", "safety_boot", "safety_vest"], 2: ["no_helmet"]}
    assert r.unassigned == [] and not any(a.ambiguous for lst in r.by_person.values() for a in lst)


def test_capacity_one_head_item_per_person():
    p1 = person(1, 0.10, 0.20, 0.20, 0.80)
    r = A.associate([p1], [det(0.12, 0.18, 0.18, 0.26, "helmet", conf=0.9),
                           det(0.13, 0.19, 0.19, 0.27, "no_helmet", conf=0.6)])
    assert len(r.by_person[1]) == 1 and len(r.unassigned) == 1  # contradicción: solo una ocupa la cabeza


def test_far_items_and_no_persons_are_unassigned():
    p1 = person(1, 0.10, 0.20, 0.20, 0.80)
    r = A.associate([p1], [det(0.70, 0.18, 0.76, 0.26, "helmet")])
    assert r.by_person[1] == [] and len(r.unassigned) == 1
    r2 = A.associate([], [det(0.70, 0.18, 0.76, 0.26, "helmet")])
    assert r2.by_person == {} and len(r2.unassigned) == 1


def test_helmet_on_feet_region_is_not_assigned():
    p1 = person(1, 0.10, 0.20, 0.20, 0.80)
    r = A.associate([p1], [det(0.12, 0.74, 0.18, 0.80, "helmet")])
    assert r.by_person[1] == []


def test_overlapping_persons_mark_ambiguity():
    p1, p2 = person(1, 0.30, 0.20, 0.40, 0.80), person(2, 0.32, 0.20, 0.42, 0.80)
    r = A.associate([p1, p2], [det(0.33, 0.18, 0.39, 0.26, "helmet")])
    assigned = [a for lst in r.by_person.values() for a in lst]
    assert len(assigned) == 1 and assigned[0].ambiguous


def test_oversized_vest_is_not_assigned_to_small_person():
    p1 = person(1, 0.30, 0.20, 0.34, 0.80)
    r = A.associate([p1], [det(0.20, 0.30, 0.50, 0.60, "safety_vest")])
    assert r.by_person[1] == []
