"""Asociación espacial EPP -> persona.

Cada clase de EPP pertenece a una **región corporal** (slot) definida relativa a la caja de la
persona, con una **capacidad** (1 casco, 2 guantes...). La asignación global es un problema de
asignación (algoritmo húngaro) en el que cada persona se replica tantas veces como su capacidad;
así dos personas solapadas no se "roban" ni se duplican los EPP.

Se marca ``ambiguous`` cuando otra persona era casi igual de plausible: el motor de reglas
(Fase 5) tratará esas observaciones como no verificables en lugar de usarlas como prueba.
Las regiones son configurables (cámaras cenitales, encuadres a media altura...).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from security_vision.core.domain.geometry import BBox
from security_vision.core.domain.vision import Detection, Track
from security_vision.core.interfaces.analysis import Association, AssociationResult, PPEAssociator


@dataclass(frozen=True)
class SlotSpec:
    classes: frozenset[str]
    # Región relativa a la caja de la persona: (x1, y1, x2, y2) en fracciones de su ancho/alto;
    # se permiten valores fuera de [0,1] (p. ej. el casco sobresale por arriba, las botas por abajo).
    region: tuple[float, float, float, float]
    capacity: int
    min_overlap: float = 0.5  # fracción mínima del EPP dentro de la región
    require_center: bool = True  # el centro del EPP debe caer dentro de la región


DEFAULT_SLOTS: dict[str, SlotSpec] = {
    "head": SlotSpec(frozenset({"helmet", "no_helmet"}), (-0.15, -0.15, 1.15, 0.35), 1),
    "eyes": SlotSpec(frozenset({"goggles", "no_goggles"}), (-0.10, -0.05, 1.10, 0.30), 1),
    "torso": SlotSpec(frozenset({"safety_vest", "no_vest"}), (-0.10, 0.10, 1.10, 0.75), 1, min_overlap=0.6),
    "hands": SlotSpec(frozenset({"gloves", "no_gloves"}), (-0.30, 0.20, 1.30, 0.95), 2),
    "feet": SlotSpec(frozenset({"safety_boot", "no_safety_boot"}), (-0.20, 0.70, 1.20, 1.12), 2),
}
AMBIGUITY_MARGIN = 0.15


def _region(person: BBox, rel: tuple[float, float, float, float]) -> np.ndarray:
    w, h = person.width, person.height
    return np.array([person.x1 + rel[0] * w, person.y1 + rel[1] * h, person.x1 + rel[2] * w, person.y1 + rel[3] * h])


def placement_score(item: BBox, person: BBox, spec: SlotSpec) -> float:
    """0 = imposible; >0 = plausibilidad (solape con la región y cercanía al eje de la persona)."""
    r = _region(person, spec.region)
    cx, cy = item.center
    if spec.require_center and not (r[0] <= cx <= r[2] and r[1] <= cy <= r[3]):
        return 0.0
    ix = max(0.0, min(item.x2, r[2]) - max(item.x1, r[0]))
    iy = max(0.0, min(item.y2, r[3]) - max(item.y1, r[1]))
    overlap = ix * iy / item.area if item.area > 0 else 0.0
    if overlap < spec.min_overlap:
        return 0.0
    # Escala: un EPP mucho más ancho que la persona no le pertenece (otra persona, falso positivo).
    if item.width > 1.6 * person.width:
        return 0.0
    # Cercanía horizontal al eje de la persona (desempata personas solapadas).
    axis = (person.x1 + person.x2) / 2
    centering = 1.0 - min(1.0, abs(cx - axis) / max(person.width, 1e-6))
    return float(0.6 * overlap + 0.4 * centering)


class GeometricPPEAssociator(PPEAssociator):
    def __init__(self, slots: Mapping[str, SlotSpec] | None = None,
                 ambiguity_margin: float = AMBIGUITY_MARGIN) -> None:
        self.slots = dict(slots or DEFAULT_SLOTS)
        self.margin = ambiguity_margin
        self._slot_of = {c: name for name, s in self.slots.items() for c in s.classes}

    def slot_of(self, class_name: str) -> str | None:
        return self._slot_of.get(class_name)

    def associate(self, persons: Sequence[Track], items: Sequence[Detection]) -> AssociationResult:
        by_person: dict[int, list[Association]] = {p.track_id: [] for p in persons}
        unassigned: list[Detection] = []
        for slot_name, spec in self.slots.items():
            slot_items = [d for d in items if d.class_name in spec.classes]
            if not slot_items:
                continue
            if not persons:
                unassigned.extend(slot_items)
                continue
            scores = np.array([[placement_score(it.bbox, p.bbox, spec) for p in persons] for it in slot_items])
            # columnas = personas replicadas por capacidad
            cols = [pi for pi in range(len(persons)) for _ in range(spec.capacity)]
            cost = np.where(scores[:, cols] > 0, 1.0 - scores[:, cols], 1e6)
            rows, cidx = linear_sum_assignment(cost)
            assigned = set()
            for r, c in zip(rows, cidx, strict=True):
                if cost[r, c] >= 1e6:
                    continue
                pi = cols[c]
                s = scores[r]
                others = np.delete(s, pi)
                ambiguous = bool(others.size and others.max() > 0 and s[pi] - others.max() < self.margin)
                by_person[persons[pi].track_id].append(
                    Association(item=slot_items[r], slot=slot_name, score=float(s[pi]), ambiguous=ambiguous))
                assigned.add(r)
            unassigned.extend(it for i, it in enumerate(slot_items) if i not in assigned)
        unassigned.extend(d for d in items if d.class_name not in self._slot_of and d.class_name != "person")
        return AssociationResult(by_person=by_person, unassigned=unassigned)
