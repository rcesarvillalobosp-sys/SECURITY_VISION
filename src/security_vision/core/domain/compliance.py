"""Vocabulario del motor de evaluación de seguridad (la lógica se implementa en la Fase 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Observation(StrEnum):
    """Observación de un EPP para una persona en un fotograma."""

    PRESENT = "present"
    ABSENT = "absent"  # región verificable y sin EPP asociado
    UNVERIFIABLE = "unverifiable"  # región no visible / insuficiente: NO es ausencia


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
class PersonCompliance:
    camera_id: str
    track_id: int
    status: ComplianceStatus
    ppe: dict[str, PPEState]
    since: datetime
    zone_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Violation:
    camera_id: str
    track_id: int
    ppe_class: str
    confirmed_at: datetime
    confidence: float
    zone_id: str | None = None
    details: dict[str, float] = field(default_factory=dict)
