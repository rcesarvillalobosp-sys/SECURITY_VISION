"""Adaptador SQL de incidentes, evidencias, detecciones, historial, comentarios y outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from security_vision.core.domain.incidents import (
    Comment,
    Evidence,
    HistoryEntry,
    Incident,
    IncidentFilter,
    IncidentStatus,
)
from security_vision.core.domain.vision import Detection
from security_vision.core.events.base import DomainEvent
from security_vision.core.interfaces.incidents import IncidentRepository

from ..models import (
    DetectionRow,
    EvidenceRow,
    IncidentCommentRow,
    IncidentHistoryRow,
    IncidentRow,
    OutboxRow,
)


def _incident(r: IncidentRow) -> Incident:
    return Incident(id=r.id, source_event_id=r.source_event_id, camera_id=r.camera_id, camera_name=r.camera_name,
                    track_id=r.track_id, violation_type=r.violation_type, status=IncidentStatus(r.status),
                    confidence=r.confidence, confirmed_at=r.confirmed_at, started_at=r.started_at,
                    ended_at=r.ended_at, end_reason=r.end_reason, zone_id=r.zone_id, profile_id=r.profile_id,
                    profile_version=r.profile_version, model_id=r.model_id, details=dict(r.details or {}),
                    created_at=r.created_at, updated_at=r.updated_at)


def _evidence(r: EvidenceRow) -> Evidence:
    return Evidence(id=r.id, kind=r.kind, storage_key=r.storage_key, sha256=r.sha256, content_type=r.content_type,
                    size_bytes=r.size_bytes, width=r.width, height=r.height, captured_at=r.captured_at,
                    frame_id=r.frame_id, meta=dict(r.meta or {}), purged_at=r.purged_at)


class SqlIncidentRepository(IncidentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_by_source(self, source_event_id: UUID) -> Incident | None:
        r = await self.s.scalar(select(IncidentRow).where(IncidentRow.source_event_id == source_event_id))
        return _incident(r) if r else None

    async def add(self, i: Incident) -> None:
        self.s.add(IncidentRow(id=i.id, source_event_id=i.source_event_id, camera_id=i.camera_id,
                               camera_name=i.camera_name, zone_id=i.zone_id, profile_id=i.profile_id,
                               profile_version=i.profile_version, track_id=i.track_id,
                               violation_type=i.violation_type, status=i.status.value, confidence=i.confidence,
                               started_at=i.started_at, confirmed_at=i.confirmed_at, model_id=i.model_id,
                               details=i.details))
        await self.s.flush()

    async def add_evidence(self, incident_id: UUID, e: Evidence) -> None:
        self.s.add(EvidenceRow(id=e.id, incident_id=incident_id, kind=e.kind, storage_key=e.storage_key,
                               sha256=e.sha256, content_type=e.content_type, size_bytes=e.size_bytes, width=e.width,
                               height=e.height, captured_at=e.captured_at, frame_id=e.frame_id, meta=e.meta))
        await self.s.flush()

    async def add_detections(self, incident_id: UUID, evidence_id: UUID | None, detections: list[Detection],
                             track_ids: dict[int, int]) -> None:
        self.s.add_all([DetectionRow(
            incident_id=incident_id, evidence_id=evidence_id, camera_id=d.camera_id, track_id=track_ids.get(i),
            class_name=d.class_name, bbox=[d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2], confidence=d.confidence,
            frame_id=d.frame_id, frame_ts=d.frame_ts, model_id=d.model_id, inference_ms=d.inference_ms)
            for i, d in enumerate(detections)])
        await self.s.flush()

    async def get(self, incident_id: UUID) -> Incident | None:
        r = await self.s.get(IncidentRow, incident_id)
        return _incident(r) if r else None

    async def list(self, flt: IncidentFilter, offset: int, limit: int) -> tuple[list[Incident], int]:
        q = select(IncidentRow)
        if flt.status:
            q = q.where(IncidentRow.status.in_([s.value for s in flt.status]))
        if flt.camera_id:
            q = q.where(IncidentRow.camera_id == flt.camera_id)
        if flt.violation_type:
            q = q.where(IncidentRow.violation_type == flt.violation_type)
        if flt.since:
            q = q.where(IncidentRow.confirmed_at >= flt.since)
        if flt.until:
            q = q.where(IncidentRow.confirmed_at < flt.until)
        total = int(await self.s.scalar(select(func.count()).select_from(q.subquery())) or 0)
        rows = await self.s.scalars(q.order_by(IncidentRow.confirmed_at.desc()).offset(offset).limit(limit))
        return [_incident(r) for r in rows], total

    async def set_status(self, incident_id: UUID, status: IncidentStatus) -> None:
        await self.s.execute(update(IncidentRow).where(IncidentRow.id == incident_id).values(status=status.value))

    async def set_ended(self, incident_id: UUID, ended_at: datetime, reason: str) -> None:
        await self.s.execute(update(IncidentRow).where(IncidentRow.id == incident_id, IncidentRow.ended_at.is_(None))
                             .values(ended_at=ended_at, end_reason=reason))

    async def evidences(self, incident_id: UUID) -> list[Evidence]:
        rows = await self.s.scalars(select(EvidenceRow).where(EvidenceRow.incident_id == incident_id)
                                    .order_by(EvidenceRow.captured_at, EvidenceRow.kind))
        return [_evidence(r) for r in rows]

    async def evidence_by_key(self, storage_key: str) -> tuple[UUID, Evidence] | None:
        r = await self.s.scalar(select(EvidenceRow).where(EvidenceRow.storage_key == storage_key))
        return (r.incident_id, _evidence(r)) if r else None

    async def detections(self, incident_id: UUID) -> list[dict[str, Any]]:
        rows = await self.s.scalars(select(DetectionRow).where(DetectionRow.incident_id == incident_id)
                                    .order_by(DetectionRow.frame_ts, DetectionRow.id))
        return [{"camera_id": str(r.camera_id), "track_id": r.track_id, "class_name": r.class_name, "bbox": r.bbox,
                 "confidence": r.confidence, "frame_id": r.frame_id, "frame_ts": r.frame_ts.isoformat(),
                 "model_id": r.model_id, "inference_ms": r.inference_ms,
                 "evidence_id": str(r.evidence_id) if r.evidence_id else None} for r in rows]

    async def add_history(self, incident_id: UUID, action: str, *, actor_id: UUID | None,
                          from_status: str | None = None, to_status: str | None = None,
                          note: str | None = None) -> None:
        self.s.add(IncidentHistoryRow(incident_id=incident_id, actor_id=actor_id, action=action,
                                      from_status=from_status, to_status=to_status, note=note))
        await self.s.flush()

    async def history(self, incident_id: UUID) -> list[HistoryEntry]:
        rows = await self.s.scalars(select(IncidentHistoryRow).where(IncidentHistoryRow.incident_id == incident_id)
                                    .order_by(IncidentHistoryRow.id))
        return [HistoryEntry(r.action, r.from_status, r.to_status, r.note, r.actor_id, r.at) for r in rows]

    async def add_comment(self, incident_id: UUID, c: Comment) -> None:
        self.s.add(IncidentCommentRow(id=c.id, incident_id=incident_id, author_id=c.author_id, body=c.body))
        await self.s.flush()

    async def comments(self, incident_id: UUID) -> list[Comment]:
        rows = await self.s.scalars(select(IncidentCommentRow).where(IncidentCommentRow.incident_id == incident_id)
                                    .order_by(IncidentCommentRow.at))
        return [Comment(r.id, r.body, r.author_id, r.at) for r in rows]

    async def enqueue_event(self, event: DomainEvent) -> None:
        env = event.envelope()
        self.s.add(OutboxRow(event_type=env["type"], payload=env))
        await self.s.flush()

    async def evidences_older_than(self, cutoff: datetime, camera_id: UUID | None, limit: int) -> list[Evidence]:
        q = (select(EvidenceRow).join(IncidentRow, IncidentRow.id == EvidenceRow.incident_id)
             .where(EvidenceRow.captured_at < cutoff, EvidenceRow.purged_at.is_(None)))
        q = q.where(IncidentRow.camera_id == camera_id) if camera_id else q
        return [_evidence(r) for r in await self.s.scalars(q.order_by(EvidenceRow.captured_at).limit(limit))]

    async def mark_purged(self, evidence_id: UUID, at: datetime) -> None:
        await self.s.execute(update(EvidenceRow).where(EvidenceRow.id == evidence_id).values(purged_at=at))

    async def all_storage_keys(self) -> set[str]:
        return set((await self.s.scalars(select(EvidenceRow.storage_key))).all())
