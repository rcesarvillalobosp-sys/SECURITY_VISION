"""Puerto de persistencia de incidentes (incluye el outbox de eventos)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from ..domain.incidents import Comment, Evidence, HistoryEntry, Incident, IncidentFilter, IncidentStatus
from ..domain.vision import Detection
from ..events.base import DomainEvent


class IncidentRepository(ABC):
    @abstractmethod
    async def get_by_source(self, source_event_id: UUID) -> Incident | None: ...

    @abstractmethod
    async def add(self, incident: Incident) -> None: ...

    @abstractmethod
    async def add_evidence(self, incident_id: UUID, evidence: Evidence) -> None: ...

    @abstractmethod
    async def add_detections(self, incident_id: UUID, evidence_id: UUID | None, detections: list[Detection],
                             track_ids: dict[int, int]) -> None: ...

    @abstractmethod
    async def get(self, incident_id: UUID) -> Incident | None: ...

    @abstractmethod
    async def list(self, flt: IncidentFilter, offset: int, limit: int) -> tuple[list[Incident], int]: ...

    @abstractmethod
    async def set_status(self, incident_id: UUID, status: IncidentStatus) -> None: ...

    @abstractmethod
    async def set_ended(self, incident_id: UUID, ended_at: datetime, reason: str) -> None: ...

    @abstractmethod
    async def evidences(self, incident_id: UUID) -> list[Evidence]: ...

    @abstractmethod
    async def evidence_by_key(self, storage_key: str) -> tuple[UUID, Evidence] | None: ...

    @abstractmethod
    async def detections(self, incident_id: UUID) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def add_history(self, incident_id: UUID, action: str, *, actor_id: UUID | None,
                          from_status: str | None = None, to_status: str | None = None,
                          note: str | None = None) -> None: ...

    @abstractmethod
    async def history(self, incident_id: UUID) -> list[HistoryEntry]: ...

    @abstractmethod
    async def add_comment(self, incident_id: UUID, comment: Comment) -> None: ...

    @abstractmethod
    async def comments(self, incident_id: UUID) -> list[Comment]: ...

    @abstractmethod
    async def enqueue_event(self, event: DomainEvent) -> None:
        """Escribe el evento en el outbox dentro de la transacción en curso."""

    @abstractmethod
    async def evidences_older_than(self, cutoff: datetime, camera_id: UUID | None, limit: int) -> list[Evidence]: ...

    @abstractmethod
    async def mark_purged(self, evidence_id: UUID, at: datetime) -> None: ...

    @abstractmethod
    async def all_storage_keys(self) -> set[str]: ...
