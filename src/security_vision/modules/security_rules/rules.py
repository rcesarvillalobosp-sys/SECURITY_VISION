"""Observación de cada EPP por persona y fotograma, con verificabilidad explícita.

Principio rector: **la ausencia de una detección no demuestra la ausencia del EPP**. Antes de
contar una ausencia se comprueba que la región corporal es verificable; si no lo es, la
observación es ``UNVERIFIABLE`` y nunca empuja hacia un incumplimiento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from security_vision.core.domain.compliance import Observation, ObservationRecord, RuleThresholds
from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.vision import Track
from security_vision.core.interfaces.analysis import Association


@dataclass(frozen=True)
class PPERule:
    ppe: str  # clase positiva canónica
    negative: str  # clase "no_*"
    slot: str  # región del asociador
    roi: tuple[float, float, float, float]  # región a verificar, relativa a la caja de la persona
    border: str | None  # "top" | "bottom": borde de imagen que corta la región
    # Algunas regiones (manos) pueden estar fuera de la vista aunque la persona sea visible: su
    # ausencia implícita pesa menos (multiplica el peso global de ausencia implícita).
    implicit_weight_factor: float = 1.0

    def region(self, person: BBox) -> BBox:
        w, h = person.width, person.height
        x1, y1 = person.x1 + self.roi[0] * w, person.y1 + self.roi[1] * h
        x2, y2 = person.x1 + self.roi[2] * w, person.y1 + self.roi[3] * h
        return BBox(max(-0.04, x1), max(-0.04, y1), min(1.04, max(x2, x1 + 1e-4)), min(1.04, max(y2, y1 + 1e-4)))

    def unverifiable_reason(self, person: Track, others: Sequence[Track], frame: Size,
                            th: RuleThresholds) -> str | None:
        b = person.bbox
        if b.height * frame.height < th.min_person_height_px:
            return "persona demasiado pequeña"
        if person.confidence < th.min_person_confidence:
            return "detección de persona poco segura (posible oclusión)"
        roi = self.region(b)
        if roi.height * frame.height < th.min_region_px:
            return "región corporal demasiado pequeña"
        if self.border == "top" and b.y1 <= th.border_margin:
            return "región cortada por el borde superior"
        if self.border == "bottom" and b.y2 >= 1.0 - th.border_margin:
            return "región cortada por el borde inferior"
        for o in others:
            # Otra persona más cercana a la cámara (pie más abajo) que tapa la región
            if o.track_id != person.track_id and o.bbox.y2 > b.y2 and roi.ioa(o.bbox) >= th.occlusion_ioa:
                return f"región ocluida por P{o.track_id}"
        return None

    def observe(self, person: Track, associated: Sequence[Association], others: Sequence[Track], frame: Size,
                th: RuleThresholds) -> ObservationRecord:
        # La verificabilidad se comprueba ANTES que cualquier evidencia. Si la persona es demasiado
        # pequeña, poco segura, está cortada u ocluida, ninguna detección (ni "helmet" ni "no_helmet")
        # es fiable: el detector se equivoca precisamente en esos casos (hallazgo de la Fase 6: un
        # "no_vest" de 0.46 sobre una figura de ~35 px generó un incidente falso).
        reason = self.unverifiable_reason(person, others, frame, th)
        if reason:
            return ObservationRecord(Observation.UNVERIFIABLE, reason=reason)
        mine = [a for a in associated if a.slot == self.slot and a.item.confidence >= th.min_item_confidence]
        clear = [a for a in mine if not a.ambiguous]
        negatives = [a for a in clear if a.item.class_name == self.negative]
        positives = [a for a in clear if a.item.class_name == self.ppe]
        # Una evidencia explícita de ausencia ("no_*") prevalece: en regiones dobles (manos, pies)
        # una mano sin guante es incumplimiento aunque la otra lo lleve.
        if negatives:
            conf = max(a.item.confidence for a in negatives)
            return ObservationRecord(Observation.ABSENT, explicit=True, confidence=conf)
        if positives:
            return ObservationRecord(Observation.PRESENT, explicit=True,
                                     confidence=max(a.item.confidence for a in positives))
        if mine:  # solo asignaciones ambiguas: no se puede atribuir a esta persona
            return ObservationRecord(Observation.UNVERIFIABLE, reason="asignación ambigua (solape de personas)")
        return ObservationRecord(Observation.ABSENT, explicit=False)


DEFAULT_RULES: dict[str, PPERule] = {
    "helmet": PPERule("helmet", "no_helmet", "head", (0.15, -0.05, 0.85, 0.22), "top"),
    "goggles": PPERule("goggles", "no_goggles", "eyes", (0.2, 0.02, 0.8, 0.2), "top", implicit_weight_factor=0.5),
    "safety_vest": PPERule("safety_vest", "no_vest", "torso", (0.1, 0.2, 0.9, 0.6), None),
    "gloves": PPERule("gloves", "no_gloves", "hands", (0.0, 0.35, 1.0, 0.8), None, implicit_weight_factor=0.25),
    "safety_boot": PPERule("safety_boot", "no_safety_boot", "feet", (0.05, 0.86, 0.95, 1.0), "bottom"),
}
