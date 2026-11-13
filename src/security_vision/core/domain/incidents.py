"""Incidentes: incumplimientos confirmados, su evidencia y su ciclo de revisión humana."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid5

from .compliance import Violation
from .vision import Detection

_NAMESPACE = UUID("6f1c9a52-3d0b-4c39-9a0e-5e2f2b8c7d11")


class IncidentStatus(StrEnum):
    PENDIENTE = "PENDIENTE"  # creado por el sistema, sin revisar
    EN_REVISION = "EN_REVISION"
    CONFIRMADO = "CONFIRMADO"  # un humano confirma el incumplimiento
    DESCARTADO = "DESCARTADO"  # falso positivo
    RESUELTO = "RESUELTO"  # se tomaron medidas


ALLOWED_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.PENDIENTE: frozenset({IncidentStatus.EN_REVISION, IncidentStatus.CONFIRMADO,
                                         IncidentStatus.DESCARTADO}),
    IncidentStatus.EN_REVISION: frozenset({IncidentStatus.CONFIRMADO, IncidentStatus.DESCARTADO,
                                           IncidentStatus.PENDIENTE}),
    IncidentStatus.CONFIRMADO: frozenset({IncidentStatus.RESUELTO, IncidentStatus.EN_REVISION}),
    IncidentStatus.DESCARTADO: frozenset({IncidentStatus.EN_REVISION}),
    IncidentStatus.RESUELTO: frozenset({IncidentStatus.EN_REVISION}),
}


def violation_event_id(v: Violation) -> UUID:
    """Identificador determinista de una confirmación: reintentos y duplicados no crean dos incidentes."""
    return uuid5(_NAMESPACE, f"{v.camera_id}|{v.track_id}|{v.ppe_class}|{v.confirmed_at.isoformat()}")


@dataclass(frozen=True, slots=True)
class EvidenceImage:
    kind: str  # frame | annotated | crop | context
    data: bytes
    content_type: str
    width: int
    height: int
    captured_at: datetime
    frame_id: int | None
    meta: dict[str, Any] = field(default_factory=dict)
    detections: tuple[Detection, ...] = ()  # detecciones de ese fotograma (con su track si lo tienen)
    track_ids: dict[int, int] = field(default_factory=dict)  # índice de detección -> track_id


@dataclass(frozen=True, slots=True)
class NewIncident:
    violation: Violation
    camera_name: str
    model_id: str | None
    profile_version: int | None
    evidences: tuple[EvidenceImage, ...]


@dataclass(slots=True)
class Evidence:
    id: UUID
    kind: str
    storage_key: str
    sha256: str
    content_type: str
    size_bytes: int
    width: int | None
    height: int | None
    captured_at: datetime
    frame_id: int | None
    meta: dict[str, Any]
    purged_at: datetime | None = None


@dataclass(slots=True)
class Incident:
    id: UUID
    source_event_id: UUID
    camera_id: UUID | None
    camera_name: str
    track_id: int
    violation_type: str
    status: IncidentStatus
    confidence: float
    confirmed_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None
    zone_id: UUID | None = None
    profile_id: UUID | None = None
    profile_version: int | None = None
    model_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    actor_id: UUID | None
    at: datetime


@dataclass(frozen=True, slots=True)
class Comment:
    id: UUID
    body: str
    author_id: UUID | None
    at: datetime


@dataclass(frozen=True, slots=True)
class IncidentFilter:
    status: tuple[IncidentStatus, ...] = ()
    camera_id: UUID | None = None
    violation_type: str | None = None
    since: datetime | None = None
    until: datetime | None = None
