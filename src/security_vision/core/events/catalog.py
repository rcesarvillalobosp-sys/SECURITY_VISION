"""Catálogo de eventos v1."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from .base import DomainEvent, register_event


@register_event
class CameraStatusChanged(DomainEvent):
    event_type: ClassVar[str] = "camera.status_changed.v1"
    camera_id: UUID
    status: str
    detail: str | None = None


@register_event
class PersonComplianceChanged(DomainEvent):
    event_type: ClassVar[str] = "person.compliance_changed.v1"
    camera_id: UUID
    track_id: int
    previous: str
    current: str
    ppe: dict[str, str]


@register_event
class IncidentConfirmed(DomainEvent):
    event_type: ClassVar[str] = "incident.confirmed.v1"
    camera_id: UUID
    track_id: int
    violation_type: str
    confidence: float
    started_at: datetime
    confirmed_at: datetime
    zone_id: UUID | None = None
    profile_id: UUID | None = None
    model_id: str
    evidence_keys: list[str]


@register_event
class UserAuthenticated(DomainEvent):
    event_type: ClassVar[str] = "user.authenticated.v1"
    user_id: UUID
    session_id: UUID


@register_event
class RulesChanged(DomainEvent):
    """Perfiles o zonas modificados: los workers recargan las reglas (sin reiniciar la captura)."""

    event_type: ClassVar[str] = "rules.changed.v1"
    camera_id: UUID | None = None  # None: puede afectar a varias cámaras


@register_event
class CameraConfigChanged(DomainEvent):
    """Alta/baja/modificación de una cámara: los workers reconcilian su configuración."""

    event_type: ClassVar[str] = "camera.config_changed.v1"
    camera_id: UUID
    action: str  # created | updated | deleted
