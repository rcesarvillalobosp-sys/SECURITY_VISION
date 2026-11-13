"""Eventos de dominio versionados. Contrato estable entre procesos (worker, API, alertas)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class DomainEvent(BaseModel):
    """Base de todos los eventos. ``event_type`` = "<nombre>.v<versión>"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: ClassVar[str]
    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=utcnow)
    correlation_id: UUID | None = None

    def envelope(self) -> dict[str, Any]:
        return {"type": self.event_type, "payload": self.model_dump(mode="json")}


_REGISTRY: dict[str, type[DomainEvent]] = {}


def register_event(cls: type[DomainEvent]) -> type[DomainEvent]:
    if cls.event_type in _REGISTRY:
        raise ValueError(f"evento duplicado: {cls.event_type}")
    _REGISTRY[cls.event_type] = cls
    return cls


def parse_event(envelope: dict[str, Any]) -> DomainEvent:
    cls = _REGISTRY.get(envelope["type"])
    if cls is None:
        raise ValueError(f"tipo de evento desconocido: {envelope['type']!r}")
    return cls.model_validate(envelope["payload"])
