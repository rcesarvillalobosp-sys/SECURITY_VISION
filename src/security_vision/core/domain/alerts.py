"""Alertas externas: canales (webhook, email), filtros y entregas con reintento.

Una alerta se emite por cada incidente confirmado que pase los filtros del canal. La entrega es
"al menos una vez" e idempotente por (canal, incidente): reiniciar el proceso no duplica ni pierde.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID


class ChannelKind(StrEnum):
    WEBHOOK = "webhook"
    EMAIL = "email"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"  # agotados los reintentos


# Reintentos: 30 s, 2 min, 8 min, 30 min, 2 h (6 intentos en total, ~2,7 h)
RETRY_BACKOFF: tuple[timedelta, ...] = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=8),
                                        timedelta(minutes=30), timedelta(hours=2))
MAX_ATTEMPTS = len(RETRY_BACKOFF) + 1


def next_retry(attempts_done: int) -> timedelta | None:
    """Espera antes del siguiente intento tras ``attempts_done`` fallos; None si no quedan intentos."""
    if attempts_done >= MAX_ATTEMPTS:
        return None
    return RETRY_BACKOFF[min(attempts_done, len(RETRY_BACKOFF)) - 1]


@dataclass(slots=True)
class AlertChannel:
    id: UUID
    name: str
    kind: ChannelKind
    enabled: bool
    config: dict[str, Any]  # webhook: {url}; email: {recipients: [...]}
    has_secret: bool = False
    violation_types: list[str] = field(default_factory=list)  # vacío = todos
    camera_ids: list[str] = field(default_factory=list)  # vacío = todas
    attach_evidence: bool = True
    created_at: datetime | None = None

    def matches(self, violation_type: str, camera_id: str | None) -> bool:
        if not self.enabled:
            return False
        if self.violation_types and violation_type not in self.violation_types:
            return False
        return not (self.camera_ids and (camera_id is None or camera_id not in self.camera_ids))


@dataclass(frozen=True, slots=True)
class AlertMessage:
    """Contenido de una alerta, independiente del canal."""

    delivery_id: str
    incident_id: str
    camera_id: str | None
    camera_name: str
    violation_type: str
    violation_label: str
    confidence: float
    confirmed_at: datetime
    zone_id: str | None
    model_id: str | None
    link: str | None  # enlace al incidente en la web (si se configuró la URL pública)
    evidence_key: str | None = None  # clave de la evidencia anotada en el almacenamiento
    evidence: tuple[str, bytes, str] | None = None  # (nombre, datos, content-type)
    test: bool = False


@dataclass(frozen=True, slots=True)
class SendResult:
    ok: bool
    detail: str | None = None
    response_code: int | None = None
    retryable: bool = True  # p. ej. un 4xx del webhook o una dirección rechazada no se reintentan


@dataclass(slots=True)
class AlertDelivery:
    id: UUID
    channel_id: UUID
    incident_id: UUID
    status: DeliveryStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None = None
    response_code: int | None = None
    created_at: datetime | None = None
    sent_at: datetime | None = None
