"""Casos de uso de incidentes: registro idempotente con evidencia, cierre, revisión humana y comentarios."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from security_vision.core.domain.errors import NotFoundError, ValidationError
from security_vision.core.domain.identity import Principal
from security_vision.core.domain.ids import uuid7
from security_vision.core.domain.incidents import (
    ALLOWED_TRANSITIONS,
    Comment,
    Evidence,
    HistoryEntry,
    Incident,
    IncidentFilter,
    IncidentStatus,
    NewIncident,
    violation_event_id,
)
from security_vision.core.events.catalog import IncidentConfirmed, IncidentUpdated
from security_vision.core.interfaces.infrastructure import ObjectStorage
from security_vision.core.interfaces.repositories import UnitOfWork

log = logging.getLogger(__name__)
MAX_COMMENT = 4000


def evidence_key(incident: Incident, kind: str, index: int) -> str:
    d = incident.confirmed_at
    cam = str(incident.camera_id) if incident.camera_id else "sin-camara"
    return f"evidences/{cam}/{d:%Y/%m/%d}/{incident.id}/{index:02d}_{kind}.jpg"


@dataclass(frozen=True)
class IncidentDetail:
    incident: Incident
    evidences: list[Evidence]
    detections: list[dict[str, Any]]
    history: list[HistoryEntry]
    comments: list[Comment]


class IncidentService:
    def __init__(self, uow: Callable[[], UnitOfWork], storage: ObjectStorage,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._uow = uow
        self._storage = storage
        self._now = clock

    # ---------------------------------------------------------------- desde el worker
    async def record(self, new: NewIncident) -> tuple[Incident, bool]:
        """Registra un incumplimiento confirmado. Idempotente: devuelve (incidente, creado)."""
        v = new.violation
        source = violation_event_id(v)
        async with self._uow() as uow:
            existing = await uow.incidents.get_by_source(source)
            if existing:
                return existing, False
        incident = Incident(
            id=uuid7(), source_event_id=source, camera_id=UUID(v.camera_id), camera_name=new.camera_name,
            track_id=v.track_id, violation_type=v.ppe_class, status=IncidentStatus.PENDIENTE,
            confidence=min(1.0, max(0.0, v.confidence)), confirmed_at=v.confirmed_at, started_at=v.started_at,
            zone_id=_uuid_or_none(v.zone_id), profile_id=_uuid_or_none(v.profile_id),
            profile_version=new.profile_version, model_id=new.model_id, details=dict(v.details))
        # 1) Evidencia en el almacenamiento (fuera de la transacción; si la transacción falla, los
        #    archivos quedan huérfanos y la purga de retención los elimina).
        stored: list[tuple[Evidence, Any]] = []
        for i, img in enumerate(new.evidences):
            key = evidence_key(incident, img.kind, i)
            obj = await asyncio.to_thread(self._storage.put, key, img.data, img.content_type)
            stored.append((Evidence(id=uuid7(), kind=img.kind, storage_key=key, sha256=obj.sha256,
                                    content_type=img.content_type, size_bytes=obj.size, width=img.width,
                                    height=img.height, captured_at=img.captured_at, frame_id=img.frame_id,
                                    meta=img.meta), img))
        # 2) Incidente + evidencias + detecciones + historial + outbox en UNA transacción
        async with self._uow() as uow:
            if await uow.incidents.get_by_source(source):  # carrera entre reintentos
                return await uow.incidents.get_by_source(source), False  # type: ignore[return-value]
            await uow.incidents.add(incident)
            for ev, img in stored:
                await uow.incidents.add_evidence(incident.id, ev)
                if img.detections:
                    await uow.incidents.add_detections(incident.id, ev.id, list(img.detections), img.track_ids)
            await uow.incidents.add_history(incident.id, "created", actor_id=None, to_status=incident.status.value,
                                            note=f"Confirmado automáticamente (confianza {incident.confidence:.2f})")
            await uow.incidents.enqueue_event(IncidentConfirmed(
                camera_id=incident.camera_id, track_id=v.track_id, violation_type=v.ppe_class,
                confidence=incident.confidence, started_at=v.started_at or v.confirmed_at,
                confirmed_at=v.confirmed_at, zone_id=incident.zone_id, profile_id=incident.profile_id,
                model_id=new.model_id or "", evidence_keys=[e.storage_key for e, _ in stored],
                incident_id=incident.id))
            await uow.commit()
        return incident, True

    async def mark_ended(self, source_event_id: UUID, ended_at: datetime, reason: str) -> bool:
        """El motor dejó de ver el incumplimiento (corregido o persona fuera de escena). No cambia la revisión."""
        async with self._uow() as uow:
            inc = await uow.incidents.get_by_source(source_event_id)
            if inc is None or inc.ended_at is not None:
                return False
            await uow.incidents.set_ended(inc.id, ended_at, reason)
            await uow.incidents.add_history(inc.id, "ended", actor_id=None, note=f"Fin de la situación: {reason}")
            await uow.incidents.enqueue_event(IncidentUpdated(incident_id=inc.id, change="ended", status=inc.status))
            await uow.commit()
            return True

    # ---------------------------------------------------------------- consulta y revisión
    async def list(self, flt: IncidentFilter, offset: int, limit: int) -> tuple[list[Incident], int]:
        async with self._uow() as uow:
            return await uow.incidents.list(flt, offset, limit)

    async def detail(self, incident_id: UUID) -> IncidentDetail:
        async with self._uow() as uow:
            inc = await uow.incidents.get(incident_id)
            if inc is None:
                raise NotFoundError("incidente no encontrado")
            return IncidentDetail(inc, await uow.incidents.evidences(incident_id),
                                  await uow.incidents.detections(incident_id), await uow.incidents.history(incident_id),
                                  await uow.incidents.comments(incident_id))

    async def change_status(self, incident_id: UUID, status: IncidentStatus, note: str | None, *,
                            actor: Principal, ip: str | None = None) -> Incident:
        async with self._uow() as uow:
            inc = await uow.incidents.get(incident_id)
            if inc is None:
                raise NotFoundError("incidente no encontrado")
            if status not in ALLOWED_TRANSITIONS[inc.status]:
                raise ValidationError(f"transición no permitida: {inc.status.value} -> {status.value}")
            if status in (IncidentStatus.DESCARTADO, IncidentStatus.RESUELTO) and not (note and note.strip()):
                raise ValidationError("descartar o resolver requiere una nota que lo justifique")
            await uow.incidents.set_status(incident_id, status)
            await uow.incidents.add_history(incident_id, "status_changed", actor_id=actor.user_id,
                                            from_status=inc.status.value, to_status=status.value,
                                            note=(note or "").strip()[:MAX_COMMENT] or None)
            await uow.audit.record("incident.status_changed", actor_id=actor.user_id, entity_type="incident",
                                   entity_id=str(incident_id), before={"status": inc.status.value},
                                   after={"status": status.value}, ip=ip)
            await uow.incidents.enqueue_event(IncidentUpdated(incident_id=incident_id, change="status", status=status))
            await uow.commit()
            inc.status = status
            return inc

    async def add_comment(self, incident_id: UUID, body: str, *, actor: Principal) -> Comment:
        body = body.strip()
        if not body or len(body) > MAX_COMMENT:
            raise ValidationError(f"comentario vacío o de más de {MAX_COMMENT} caracteres")
        async with self._uow() as uow:
            if await uow.incidents.get(incident_id) is None:
                raise NotFoundError("incidente no encontrado")
            c = Comment(uuid7(), body, actor.user_id, self._now())
            await uow.incidents.add_comment(incident_id, c)
            await uow.incidents.add_history(incident_id, "commented", actor_id=actor.user_id)
            await uow.commit()
            return c

    async def evidence_for_key(self, storage_key: str) -> tuple[UUID, Evidence]:
        async with self._uow() as uow:
            found = await uow.incidents.evidence_by_key(storage_key)
        if found is None:
            raise NotFoundError("evidencia no encontrada")
        return found

    def read_verified(self, ev: Evidence) -> bytes:
        """Lee la evidencia y comprueba su sha256: una evidencia alterada no se sirve."""
        if ev.purged_at is not None:
            raise NotFoundError("evidencia purgada por la política de retención")
        data = self._storage.get(ev.storage_key)
        if hashlib.sha256(data).hexdigest() != ev.sha256:
            raise EvidenceIntegrityError(ev.storage_key)
        return data


class EvidenceIntegrityError(Exception):
    pass


def _uuid_or_none(v: str | None) -> UUID | None:
    if not v:
        return None
    try:
        return UUID(v)
    except ValueError:
        return None  # p. ej. perfiles combinados de varias zonas ("a+b")
