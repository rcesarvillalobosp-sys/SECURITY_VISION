"""Evaluador de seguridad basado en reglas, con agregación temporal y máquina de estados por persona.

Flujo por fotograma y persona:
1. Perfil aplicable: zonas que contienen el punto de apoyo (pie) de la persona; si no hay ninguna,
   el perfil por defecto de la cámara; si tampoco, la persona no se evalúa.
2. Por cada EPP requerido: una ``ObservationRecord`` (presente / ausente explícito / ausente
   implícito / no verificable).
3. Ventana deslizante -> ``PPEState`` (DETECTED / MISSING / NOT_VERIFIABLE / UNCERTAIN).
4. Estado de la persona y confirmación de incumplimientos (sostenido + mínimo de ausencias
   verificables + histéresis + enfriamiento).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from security_vision.core.domain.compliance import (
    CameraRules,
    ComplianceStatus,
    Observation,
    ObservationRecord,
    PersonCompliance,
    PPEState,
    RuleThresholds,
    SecurityProfile,
    Violation,
    ZoneRule,
)
from security_vision.core.domain.geometry import point_in_polygon
from security_vision.core.domain.vision import Track
from security_vision.core.interfaces.analysis import (
    AssociationResult,
    ClosedViolation,
    EvaluationContext,
    EvaluationResult,
    SecurityEvaluator,
    Transition,
)

from .rules import DEFAULT_RULES, PPERule


@dataclass
class _PPETrackState:
    window: deque[tuple[datetime, ObservationRecord]] = field(default_factory=deque)
    state: PPEState = PPEState.NOT_VERIFIABLE
    missing_since: datetime | None = None
    detected_since: datetime | None = None
    open_violation: Violation | None = None
    last_confirmed_at: datetime | None = None


@dataclass
class _PersonState:
    status: ComplianceStatus = ComplianceStatus.NO_VERIFICABLE
    since: datetime | None = None
    last_seen: datetime | None = None
    ppe: dict[str, _PPETrackState] = field(default_factory=dict)


@dataclass(frozen=True)
class WindowStats:
    total: int
    present: int
    absent_explicit: int
    absent_implicit: int

    @property
    def verifiable(self) -> int:
        return self.present + self.absent_explicit + self.absent_implicit


def window_stats(window: Sequence[tuple[datetime, ObservationRecord]]) -> WindowStats:
    p = ae = ai = 0
    for _, rec in window:
        if rec.observation is Observation.PRESENT:
            p += 1
        elif rec.observation is Observation.ABSENT:
            if rec.explicit:
                ae += 1
            else:
                ai += 1
    return WindowStats(len(window), p, ae, ai)


def aggregate(stats: WindowStats, th: RuleThresholds, implicit_factor: float = 1.0) -> tuple[PPEState, float]:
    """Estado del EPP en la ventana y la cuota de ausencia ponderada (confianza del incumplimiento)."""
    if stats.total == 0 or stats.verifiable < th.min_observations or \
            stats.verifiable / stats.total < th.min_verifiable_ratio:
        return PPEState.NOT_VERIFIABLE, 0.0
    absent_w = stats.absent_explicit + stats.absent_implicit * th.implicit_absent_weight * implicit_factor
    present_w = float(stats.present)
    if present_w + absent_w <= 0:
        return PPEState.UNCERTAIN, 0.0
    present_share = present_w / (present_w + absent_w)
    absent_share = absent_w / (present_w + absent_w)
    if present_share >= th.present_ratio:
        return PPEState.DETECTED, absent_share
    if absent_share >= th.absent_ratio and (not th.require_explicit_negative or stats.absent_explicit > 0):
        return PPEState.MISSING, absent_share
    return PPEState.UNCERTAIN, absent_share


def resolve_profile(person: Track, rules: CameraRules) -> tuple[SecurityProfile | None, tuple[str, ...]]:
    """Perfil efectivo: unión de los EPP requeridos por las zonas que contienen el pie de la persona
    (se aplica la exigencia más estricta). Umbrales: los del primer perfil de zona."""
    foot = person.bbox.foot_point
    hits: list[ZoneRule] = [z for z in rules.zones if z.kind == "ppe" and point_in_polygon(foot, list(z.polygon))]
    with_profile = [z for z in hits if z.profile is not None]
    if not with_profile:
        return rules.default_profile, tuple(z.zone_id for z in hits)
    base = with_profile[0].profile
    assert base is not None
    required: list[str] = []
    for z in with_profile:
        for p in z.profile.required_ppe:  # type: ignore[union-attr]
            if p not in required:
                required.append(p)
    merged = SecurityProfile(id="+".join(z.profile.id for z in with_profile),  # type: ignore[union-attr]
                             name=" + ".join(z.profile.name for z in with_profile),  # type: ignore[union-attr]
                             required_ppe=tuple(required), thresholds=base.thresholds)
    return merged, tuple(z.zone_id for z in hits)


class RuleBasedSecurityEvaluator(SecurityEvaluator):
    def __init__(self, rules: CameraRules, ppe_rules: Mapping[str, PPERule] | None = None) -> None:
        self.rules = rules
        self.ppe_rules = dict(ppe_rules or DEFAULT_RULES)
        self._persons: dict[int, _PersonState] = {}
        self._latest: list[PersonCompliance] = []

    # ------------------------------------------------------------------ API
    def evaluate(self, tracks: Sequence[Track], associations: AssociationResult,
                 ctx: EvaluationContext) -> EvaluationResult:
        now = ctx.frame_ts
        persons_out: list[PersonCompliance] = []
        transitions: list[Transition] = []
        new_violations: list[Violation] = []
        closed: list[ClosedViolation] = []
        for t in tracks:
            profile, zone_ids = resolve_profile(t, self.rules)
            st = self._persons.setdefault(t.track_id, _PersonState(since=now))
            st.last_seen = now
            if profile is None or not profile.required_ppe:
                new_status = ComplianceStatus.NO_VERIFICABLE
                ppe_states: dict[str, PPEState] = {}
            else:
                th = profile.thresholds
                ppe_states = {}
                for ppe in profile.required_ppe:
                    rule = self.ppe_rules[ppe]
                    rec = rule.observe(t, associations.by_person.get(t.track_id, []), tracks, ctx.frame_size, th)
                    ps = st.ppe.setdefault(ppe, _PPETrackState())
                    ps.window.append((now, rec))
                    while ps.window and (now - ps.window[0][0]).total_seconds() > th.window_seconds:
                        ps.window.popleft()
                    stats = window_stats(ps.window)
                    state, absent_share = aggregate(stats, th, rule.implicit_weight_factor)
                    ps.state = state
                    self._update_ppe_timers(ps, state, now)
                    v = self._maybe_confirm(t, ppe, ps, stats, absent_share, th, now, profile, zone_ids)
                    if v:
                        new_violations.append(v)
                    c = self._maybe_clear(ps, th, now)
                    if c:
                        closed.append(c)
                    ppe_states[ppe] = state
                new_status = self._person_status(st, profile.required_ppe, ppe_states)
            if new_status is not st.status:
                transitions.append(Transition(t.track_id, st.status.value, new_status.value, now))
                st.status = new_status
                st.since = now
            persons_out.append(PersonCompliance(camera_id=self.rules.camera_id, track_id=t.track_id,
                                                status=st.status, ppe=ppe_states, since=st.since or now,
                                                zone_ids=zone_ids, profile_id=profile.id if profile else None))
        closed.extend(self._forget(now))
        self._latest = persons_out
        return EvaluationResult(persons_out, transitions, new_violations, closed)

    def get_violations(self) -> list[Violation]:
        return [ps.open_violation for st in self._persons.values() for ps in st.ppe.values() if ps.open_violation]

    def get_compliance_status(self, track_id: int | None = None) -> list[PersonCompliance]:
        return [p for p in self._latest if track_id is None or p.track_id == track_id]

    # ------------------------------------------------------------------ internos
    @staticmethod
    def _update_ppe_timers(ps: _PPETrackState, state: PPEState, now: datetime) -> None:
        if state is PPEState.MISSING:
            ps.missing_since = ps.missing_since or now
        else:
            ps.missing_since = None
        if state is PPEState.DETECTED:
            ps.detected_since = ps.detected_since or now
        else:
            ps.detected_since = None

    def _maybe_confirm(self, t: Track, ppe: str, ps: _PPETrackState, stats: WindowStats, absent_share: float,
                       th: RuleThresholds, now: datetime, profile: SecurityProfile,
                       zone_ids: tuple[str, ...]) -> Violation | None:
        if ps.open_violation is not None or ps.missing_since is None:
            return None
        if (now - ps.missing_since).total_seconds() < th.confirm_seconds:
            return None
        if stats.absent_explicit + stats.absent_implicit < th.min_absent_observations:
            return None
        if stats.absent_explicit < th.min_explicit_absences_to_confirm:
            return None  # ausencia solo implícita: se queda en POSIBLE_INCUMPLIMIENTO (revisión)
        if ps.last_confirmed_at and (now - ps.last_confirmed_at).total_seconds() < th.cooldown_seconds:
            return None
        v = Violation(camera_id=self.rules.camera_id, track_id=t.track_id, ppe_class=ppe, confirmed_at=now,
                      confidence=round(absent_share, 3), zone_id=zone_ids[0] if zone_ids else None,
                      profile_id=profile.id, started_at=ps.missing_since,
                      details={"observations": stats.total, "verifiable": stats.verifiable,
                               "absent_explicit": stats.absent_explicit, "absent_implicit": stats.absent_implicit,
                               "present": stats.present})
        ps.open_violation = v
        ps.last_confirmed_at = now
        return v

    @staticmethod
    def _maybe_clear(ps: _PPETrackState, th: RuleThresholds, now: datetime) -> ClosedViolation | None:
        if ps.open_violation is None or ps.detected_since is None:
            return None
        if (now - ps.detected_since).total_seconds() < th.clear_seconds:
            return None
        c = ClosedViolation(ps.open_violation, now, "corrected")
        ps.open_violation = None
        return c

    @staticmethod
    def _person_status(st: _PersonState, required: Sequence[str], states: Mapping[str, PPEState]
                       ) -> ComplianceStatus:
        if any(st.ppe[p].open_violation is not None for p in required):
            return ComplianceStatus.INCUMPLIMIENTO_CONFIRMADO
        values = [states[p] for p in required]
        if any(s is PPEState.MISSING for s in values):
            return ComplianceStatus.POSIBLE_INCUMPLIMIENTO
        if all(s is PPEState.DETECTED for s in values):
            return ComplianceStatus.CUMPLIMIENTO
        if all(s is PPEState.NOT_VERIFIABLE for s in values):
            return ComplianceStatus.NO_VERIFICABLE
        return ComplianceStatus.EN_REVISION

    def _forget(self, now: datetime) -> list[ClosedViolation]:
        closed = []
        for tid in list(self._persons):
            st = self._persons[tid]
            th = self.rules.default_profile.thresholds if self.rules.default_profile else RuleThresholds()
            if st.last_seen and (now - st.last_seen).total_seconds() > th.forget_seconds:
                for ps in st.ppe.values():
                    if ps.open_violation:
                        closed.append(ClosedViolation(ps.open_violation, now, "track_lost"))
                del self._persons[tid]
        return closed
