"""Máquina de estados del motor de reglas: casos exigidos por el requisito 5 y casos límite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from security_vision.core.domain.compliance import (
    CameraRules,
    Observation,
    PPEState,
    RuleThresholds,
    SecurityProfile,
    ZoneRule,
)
from security_vision.core.domain.compliance import (
    ComplianceStatus as S,
)
from security_vision.core.domain.errors import ValidationError
from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Detection, Track, TrackState
from security_vision.core.interfaces.analysis import Association, AssociationResult, EvaluationContext
from security_vision.modules.security_rules.engine import RuleBasedSecurityEvaluator, aggregate, window_stats
from security_vision.modules.security_rules.rules import DEFAULT_RULES

CAM = UUID("01890000-0000-7000-8000-000000000001")
T0 = datetime(2026, 1, 1, tzinfo=UTC)
FPS = 3
FRAME = Size(1280, 720)
SLOT = {"helmet": "head", "no_helmet": "head", "safety_vest": "torso", "no_vest": "torso",
        "safety_boot": "feet", "no_safety_boot": "feet", "gloves": "hands", "no_gloves": "hands"}

HELMET = SecurityProfile("p-helmet", "Casco", ("helmet",))
FULL = SecurityProfile("p-full", "Casco+chaleco+botas", ("helmet", "safety_vest", "safety_boot"))


def ts(k: int) -> datetime:
    return T0 + timedelta(seconds=k / FPS)


def person(tid: int = 1, box=(0.40, 0.20, 0.48, 0.80), conf: float = 0.9) -> Track:
    return Track(track_id=tid, camera_id=CAM, class_name="person", bbox=BBox(*box), confidence=conf,
                 state=TrackState.CONFIRMED, first_seen=T0, last_seen=T0)


def item(cls: str, conf: float = 0.8) -> Detection:
    return Detection(camera_id=CAM, frame_id=0, frame_ts=T0, frame_size=FRAME, class_name=cls,
                     bbox=BBox(0.41, 0.19, 0.47, 0.25), confidence=conf, model_id="t@1", inference_ms=0)


def assoc(tid: int, *classes: str, ambiguous: bool = False) -> AssociationResult:
    return AssociationResult(by_person={tid: [Association(item(c), SLOT[c], 0.9, ambiguous) for c in classes]},
                             unassigned=[])


def run(ev: RuleBasedSecurityEvaluator, frames: int, start: int = 0, tracks=None, associations=None):
    results = []
    for k in range(start, start + frames):
        tr = tracks if tracks is not None else [person()]
        a = associations if associations is not None else AssociationResult({t.track_id: [] for t in tr}, [])
        results.append(ev.evaluate(tr, a, EvaluationContext(str(CAM), ts(k), FRAME)))
    return results


def evaluator(profile: SecurityProfile = HELMET, zones=()) -> RuleBasedSecurityEvaluator:
    return RuleBasedSecurityEvaluator(CameraRules(str(CAM), profile, tuple(zones)))


# --- Requisito: un fotograma nunca basta ----------------------------------------------

def test_single_frame_without_helmet_never_yields_violation():
    ev = evaluator()
    r = run(ev, 1, associations=assoc(1, "no_helmet"))[0]
    assert r.persons[0].status is S.NO_VERIFICABLE  # menos de min_observations
    assert r.new_violations == []


def test_one_frame_dropout_during_compliance_is_ignored():
    ev = evaluator()
    run(ev, 9, associations=assoc(1, "helmet"))
    r = run(ev, 1, start=9, associations=assoc(1))[0]  # un fotograma sin casco detectado
    assert r.persons[0].status is S.CUMPLIMIENTO and r.new_violations == []


# --- Confirmación ----------------------------------------------------------------------

def test_sustained_explicit_absence_is_confirmed_once():
    ev = evaluator()
    res = run(ev, 30, associations=assoc(1, "no_helmet"))
    statuses = [r.persons[0].status for r in res]
    assert S.POSIBLE_INCUMPLIMIENTO in statuses
    first_conf = statuses.index(S.INCUMPLIMIENTO_CONFIRMADO)
    assert first_conf / FPS >= HELMET.thresholds.confirm_seconds  # nunca antes del tiempo sostenido
    violations = [v for r in res for v in r.new_violations]
    assert len(violations) == 1  # una sola vez, no una por fotograma
    v = violations[0]
    assert v.ppe_class == "helmet" and v.track_id == 1 and v.profile_id == "p-helmet"
    assert v.started_at is not None and v.started_at < v.confirmed_at and v.details["absent_explicit"] >= 2


def test_implicit_absence_only_stays_as_possible_violation():
    """Requisito: diferenciar incumplimiento de ausencia de evidencia. No ver el casco (región
    visible) durante mucho tiempo lleva a POSIBLE_INCUMPLIMIENTO (revisión), nunca a confirmado."""
    ev = evaluator()
    res = run(ev, 60, associations=assoc(1))
    assert res[-1].persons[0].status is S.POSIBLE_INCUMPLIMIENTO
    assert all(r.new_violations == [] for r in res)


def test_require_explicit_zero_allows_implicit_confirmation_when_configured():
    th = RuleThresholds(min_explicit_absences_to_confirm=0)
    ev = evaluator(SecurityProfile("p", "p", ("helmet",), th))
    res = run(ev, 40, associations=assoc(1))
    assert any(r.new_violations for r in res)


# --- No verificable --------------------------------------------------------------------

@pytest.mark.parametrize("box,reason", [
    ((0.40, 0.00, 0.48, 0.60), "cortada por el borde superior"),
    ((0.40, 0.50, 0.42, 0.56), "persona demasiado pequeña"),
])
def test_unverifiable_region_never_becomes_violation(box, reason):
    ev = evaluator()
    res = run(ev, 60, tracks=[person(box=box)])
    assert all(r.persons[0].status is S.NO_VERIFICABLE for r in res)
    assert all(r.new_violations == [] for r in res)
    rec = DEFAULT_RULES["helmet"].observe(person(box=box), [], [person(box=box)], FRAME, RuleThresholds())
    assert rec.observation is Observation.UNVERIFIABLE and reason in rec.reason


def test_occlusion_by_closer_person_is_unverifiable():
    back = person(1, (0.40, 0.20, 0.48, 0.70))
    front = person(2, (0.38, 0.30, 0.50, 0.95))  # pie más abajo = más cerca de la cámara
    rec = DEFAULT_RULES["safety_vest"].observe(back, [], [back, front], FRAME, RuleThresholds())
    assert rec.observation is Observation.UNVERIFIABLE and "ocluida por P2" in rec.reason
    rec2 = DEFAULT_RULES["safety_vest"].observe(front, [], [back, front], FRAME, RuleThresholds())
    assert rec2.observation is Observation.ABSENT and not rec2.explicit


def test_low_confidence_person_is_unverifiable():
    rec = DEFAULT_RULES["helmet"].observe(person(conf=0.2), [], [], FRAME, RuleThresholds())
    assert rec.observation is Observation.UNVERIFIABLE


def test_ambiguous_association_is_unverifiable_not_present():
    ev = evaluator()
    res = run(ev, 30, associations=assoc(1, "helmet", ambiguous=True))
    assert res[-1].persons[0].status is S.NO_VERIFICABLE


# --- Ejemplos literales del requisito 5 ------------------------------------------------

def test_worker_001_helmet_vest_ok_boots_unverifiable_needs_review():
    """Casco detectado, chaleco detectado, botas no verificables -> revisión necesaria."""
    ev = evaluator(FULL)
    cut_feet = person(box=(0.40, 0.30, 0.48, 1.0))  # pies cortados por el borde inferior
    res = run(ev, 15, tracks=[cut_feet], associations=assoc(1, "helmet", "safety_vest"))
    p = res[-1].persons[0]
    assert p.ppe == {"helmet": PPEState.DETECTED, "safety_vest": PPEState.DETECTED,
                     "safety_boot": PPEState.NOT_VERIFIABLE}
    assert p.status is S.EN_REVISION


def test_worker_002_no_helmet_vest_and_boots_ok_possible_violation():
    """Casco no detectado, chaleco y botas detectados -> posible incumplimiento."""
    ev = evaluator(FULL)
    res = run(ev, 6, associations=assoc(1, "no_helmet", "safety_vest", "safety_boot"))
    p = res[-1].persons[0]
    assert p.ppe["helmet"] is PPEState.MISSING and p.ppe["safety_vest"] is PPEState.DETECTED
    assert p.status is S.POSIBLE_INCUMPLIMIENTO


# --- Estabilidad, histéresis, enfriamiento, olvido ---------------------------------------

def test_flicker_between_present_and_absent_is_never_confirmed():
    ev = evaluator()
    res = []
    for k in range(60):
        res += run(ev, 1, start=k, associations=assoc(1, "helmet" if k % 2 else "no_helmet"))
    assert all(r.new_violations == [] for r in res)
    assert res[-1].persons[0].status is S.EN_REVISION


def test_hysteresis_and_cooldown():
    ev = evaluator()
    th = HELMET.thresholds
    res = run(ev, 30, associations=assoc(1, "no_helmet"))
    assert sum(len(r.new_violations) for r in res) == 1
    # Se pone el casco: no se cierra al instante, sino tras clear_seconds de DETECTED sostenido
    res2 = run(ev, 40, start=30, associations=assoc(1, "helmet"))
    closed = [(i, c) for i, r in enumerate(res2) for c in r.closed_violations]
    assert len(closed) == 1 and closed[0][1].reason == "corrected"
    assert closed[0][0] / FPS >= th.clear_seconds
    assert res2[-1].persons[0].status is S.CUMPLIMIENTO
    # Se lo vuelve a quitar enseguida: dentro del enfriamiento no se re-confirma
    res3 = run(ev, 40, start=70, associations=assoc(1, "no_helmet"))
    assert all(r.new_violations == [] for r in res3)
    assert res3[-1].persons[0].status is S.POSIBLE_INCUMPLIMIENTO


def test_lost_track_closes_open_violation():
    ev = evaluator()
    run(ev, 30, associations=assoc(1, "no_helmet"))
    assert len(ev.get_violations()) == 1
    res = run(ev, 40, start=30, tracks=[], associations=AssociationResult({}, []))
    closed = [c for r in res for c in r.closed_violations]
    assert len(closed) == 1 and closed[0].reason == "track_lost" and ev.get_violations() == []


# --- Zonas y perfiles --------------------------------------------------------------------

def test_zone_profile_applies_by_foot_point_and_requirements_are_merged():
    vest = SecurityProfile("p-vest", "Chaleco", ("safety_vest",))
    zone = ZoneRule("z1", "Zona de carga", ((0.3, 0.5), (0.6, 0.5), (0.6, 1.0), (0.3, 1.0)), vest)
    ev = evaluator(HELMET, zones=[zone])
    inside = person(1, (0.40, 0.20, 0.48, 0.80))  # pie en (0.44, 0.80) -> dentro
    outside = person(2, (0.70, 0.20, 0.78, 0.80))
    a = AssociationResult({1: [], 2: []}, [])
    r = ev.evaluate([inside, outside], a, EvaluationContext(str(CAM), ts(0), FRAME))
    by = {p.track_id: p for p in r.persons}
    assert set(by[1].ppe) == {"safety_vest"} and by[1].zone_ids == ("z1",)
    assert set(by[2].ppe) == {"helmet"} and by[2].profile_id == "p-helmet"


def test_no_profile_means_not_evaluated():
    ev = evaluator(profile=None)  # type: ignore[arg-type]
    r = run(ev, 20, associations=assoc(1, "no_helmet"))
    assert r[-1].persons[0].status is S.NO_VERIFICABLE and r[-1].persons[0].profile_id is None
    assert all(x.new_violations == [] for x in r)


# --- Agregación y validación de umbrales -------------------------------------------------

def test_aggregate_weights_implicit_absence_less():
    from security_vision.core.domain.compliance import ObservationRecord as R

    th = RuleThresholds()
    w = [(T0, R(Observation.PRESENT))] * 3 + [(T0, R(Observation.ABSENT, explicit=False))] * 3
    state, share = aggregate(window_stats(w), th)
    assert state is PPEState.DETECTED  # 3 presencias vs 3 ausencias implícitas (peso 0.5)
    assert share == pytest.approx(1.5 / 4.5)


@pytest.mark.parametrize("bad", [
    {"min_observations": 1}, {"present_ratio": 0.4, "absent_ratio": 0.5}, {"absent_ratio": 1.5},
    {"confirm_seconds": 0}, {"umbral_inventado": 3},
])
def test_threshold_validation(bad):
    with pytest.raises(ValidationError):
        RuleThresholds.from_dict(bad)


def test_profile_rejects_unknown_ppe():
    with pytest.raises(ValidationError):
        SecurityProfile("p", "p", ("casco",))


def test_regression_tiny_person_with_explicit_negative_is_never_confirmed():
    """Hallazgo de la Fase 6: una figura lejana de ~35 px con un "no_vest" de 0.46 generó un incidente.
    Con resolución insuficiente, ni la evidencia explícita cuenta: NO_VERIFICABLE."""
    vest = SecurityProfile("p-vest", "Chaleco", ("safety_vest",))
    ev = evaluator(vest)
    tiny = person(box=(0.20, 0.20, 0.215, 0.249))  # ~35 px de alto en 720p
    res = run(ev, 60, tracks=[tiny], associations=assoc(1, "no_vest"))
    assert all(r.new_violations == [] for r in res)
    assert res[-1].persons[0].status is S.NO_VERIFICABLE


def test_occluded_region_ignores_explicit_negative():
    back = person(1, (0.40, 0.20, 0.48, 0.70))
    front = person(2, (0.38, 0.30, 0.50, 0.95))
    a = Association(item("no_vest"), "torso", 0.9, False)
    rec = DEFAULT_RULES["safety_vest"].observe(back, [a], [back, front], FRAME, RuleThresholds())
    assert rec.observation is Observation.UNVERIFIABLE
