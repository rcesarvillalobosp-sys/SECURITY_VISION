"""Vocabulario y configuración del motor de evaluación de seguridad (Python puro)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import ValidationError
from .taxonomy import PPE_PAIRS, CanonicalClass

# EPP evaluables: la clase "positiva" de cada par de la taxonomía.
EVALUABLE_PPE: tuple[str, ...] = tuple(c.value for c in PPE_PAIRS)


class Observation(StrEnum):
    """Observación de un EPP para una persona en un fotograma."""

    PRESENT = "present"
    ABSENT = "absent"  # región verificable y EPP ausente (explícita o implícitamente)
    UNVERIFIABLE = "unverifiable"  # región no visible / insuficiente / ambigua: NO es ausencia


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    observation: Observation
    # ``explicit``: el detector vio la ausencia (clase "no_*"). Si es False y la observación es
    # ABSENT, es una ausencia *implícita*: la región era verificable pero no se detectó el EPP.
    explicit: bool = False
    confidence: float = 0.0
    reason: str = ""  # para UNVERIFIABLE: por qué (cortada, pequeña, ocluida, ambigua...)


class PPEState(StrEnum):
    """Estado agregado de un EPP en una ventana temporal."""

    DETECTED = "detected"
    MISSING = "missing"
    NOT_VERIFIABLE = "not_verifiable"
    UNCERTAIN = "uncertain"


class ComplianceStatus(StrEnum):
    """Estado de seguridad de una persona (valores del requisito 5)."""

    CUMPLIMIENTO = "CUMPLIMIENTO"
    POSIBLE_INCUMPLIMIENTO = "POSIBLE_INCUMPLIMIENTO"
    INCUMPLIMIENTO_CONFIRMADO = "INCUMPLIMIENTO_CONFIRMADO"
    NO_VERIFICABLE = "NO_VERIFICABLE"
    EN_REVISION = "EN_REVISION"


@dataclass(frozen=True, slots=True)
class RuleThresholds:
    """Umbrales del motor. Por defecto conservadores: ante la duda, NO_VERIFICABLE/EN_REVISION."""

    window_seconds: float = 6.0  # ventana deslizante de observaciones
    min_observations: int = 4  # observaciones verificables mínimas en la ventana para decidir
    min_verifiable_ratio: float = 0.5  # fracción mínima de observaciones verificables
    present_ratio: float = 0.6  # cuota (ponderada) de presencias para DETECTED
    absent_ratio: float = 0.7  # cuota (ponderada) de ausencias para MISSING
    implicit_absent_weight: float = 0.5  # peso de una ausencia implícita frente a una explícita (1.0)
    require_explicit_negative: bool = False  # True: MISSING exige al menos una detección "no_*"
    confirm_seconds: float = 5.0  # MISSING sostenido antes de confirmar el incumplimiento
    min_absent_observations: int = 4  # ausencias verificables mínimas para confirmar
    # Confirmar exige evidencia POSITIVA de ausencia: al menos este nº de detecciones "no_*" en la
    # ventana. Con 0, una ausencia solo implícita (no ver el casco) podría confirmar: no recomendado.
    min_explicit_absences_to_confirm: int = 2
    clear_seconds: float = 4.0  # DETECTED sostenido para cerrar un incumplimiento (histéresis)
    cooldown_seconds: float = 60.0  # no se re-confirma el mismo (persona, EPP) antes de este tiempo
    forget_seconds: float = 10.0  # se olvida el estado de un track que no aparece
    min_person_height_px: int = 80  # personas más pequeñas: no verificables
    min_region_px: int = 12  # región corporal más pequeña: no verificable
    border_margin: float = 0.01  # caja que toca el borde: región cortada
    occlusion_ioa: float = 0.35  # región tapada por otra persona más cercana a la cámara
    min_person_confidence: float = 0.4  # detección de persona poco segura (oclusión parcial)
    min_item_confidence: float = 0.4  # EPP con menos confianza no cuenta

    def __post_init__(self) -> None:
        for name in ("present_ratio", "absent_ratio", "min_verifiable_ratio", "implicit_absent_weight",
                     "occlusion_ioa", "min_person_confidence", "min_item_confidence"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValidationError(f"{name} debe estar en [0, 1]")
        if self.present_ratio + self.absent_ratio <= 1.0:
            raise ValidationError("present_ratio + absent_ratio debe superar 1 (si no, un mismo estado sería ambos)")
        for name in ("window_seconds", "confirm_seconds", "clear_seconds"):
            if getattr(self, name) <= 0:
                raise ValidationError(f"{name} debe ser positivo")
        if self.confirm_seconds > self.window_seconds * 10:
            raise ValidationError("confirm_seconds desproporcionado respecto a la ventana")
        if self.min_explicit_absences_to_confirm < 0:
            raise ValidationError("min_explicit_absences_to_confirm no puede ser negativo")
        if self.min_observations < 2 or self.min_absent_observations < 2:
            raise ValidationError("se requieren al menos 2 observaciones: nunca se decide con un fotograma")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RuleThresholds:
        data = dict(data or {})
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValidationError(f"umbrales desconocidos: {', '.join(sorted(unknown))}")
        return replace(cls(), **data)

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True, slots=True)
class SecurityProfile:
    id: str
    name: str
    required_ppe: tuple[str, ...]
    thresholds: RuleThresholds = field(default_factory=RuleThresholds)
    version: int = 1

    def __post_init__(self) -> None:
        bad = set(self.required_ppe) - set(EVALUABLE_PPE)
        if bad:
            raise ValidationError(f"EPP no evaluables: {sorted(bad)} (válidos: {list(EVALUABLE_PPE)})")


@dataclass(frozen=True, slots=True)
class ZoneRule:
    zone_id: str
    name: str
    polygon: tuple[tuple[float, float], ...]  # coordenadas normalizadas
    profile: SecurityProfile | None
    kind: str = "ppe"

    def __post_init__(self) -> None:
        if len(self.polygon) < 3:
            raise ValidationError("una zona necesita al menos 3 vértices")
        if any(not (-0.01 <= x <= 1.01 and -0.01 <= y <= 1.01) for x, y in self.polygon):
            raise ValidationError("vértices fuera del rango normalizado [0, 1]")


@dataclass(frozen=True, slots=True)
class CameraRules:
    """Reglas efectivas de una cámara: perfil por defecto + zonas con su perfil."""

    camera_id: str
    default_profile: SecurityProfile | None
    zones: tuple[ZoneRule, ...] = ()


@dataclass(frozen=True, slots=True)
class PersonCompliance:
    camera_id: str
    track_id: int
    status: ComplianceStatus
    ppe: dict[str, PPEState]
    since: datetime
    zone_ids: tuple[str, ...] = ()
    profile_id: str | None = None  # None: ninguna regla aplica a esta persona (fuera de zonas, sin perfil)


@dataclass(frozen=True, slots=True)
class Violation:
    camera_id: str
    track_id: int
    ppe_class: str
    confirmed_at: datetime
    confidence: float
    zone_id: str | None = None
    profile_id: str | None = None
    started_at: datetime | None = None  # inicio del periodo MISSING que llevó a la confirmación
    details: dict[str, float] = field(default_factory=dict)


_ = CanonicalClass  # la taxonomía define los nombres válidos
