"""Incidentes: consulta, evidencias (URL firmadas y auditadas), revisión humana y comentarios."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from security_vision.core.domain.identity import Permission, Principal
from security_vision.core.domain.incidents import Incident, IncidentFilter, IncidentStatus
from security_vision.modules.incidents.service import EvidenceIntegrityError

from ..container import Container
from ..deps import client_ip, get_container, require

router = APIRouter(prefix="/api/v1", tags=["incidents"])
C = Annotated[Container, Depends(get_container)]
Reader = Annotated[Principal, Depends(require(Permission.INCIDENTS_READ))]
Reviewer = Annotated[Principal, Depends(require(Permission.INCIDENTS_REVIEW))]
EVIDENCE_URL_TTL = timedelta(minutes=5)


class IncidentOut(BaseModel):
    id: UUID
    camera_id: UUID | None
    camera_name: str
    track_id: int
    violation_type: str
    status: IncidentStatus
    confidence: float
    started_at: datetime | None
    confirmed_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    zone_id: UUID | None
    profile_id: UUID | None
    profile_version: int | None
    model_id: str | None


class EvidenceOut(BaseModel):
    id: UUID
    kind: str
    url: str | None  # None si fue purgada por retención
    sha256: str
    width: int | None
    height: int | None
    captured_at: datetime
    frame_id: int | None
    purged: bool
    meta: dict[str, Any]


class HistoryOut(BaseModel):
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    actor_id: UUID | None
    at: datetime


class CommentOut(BaseModel):
    id: UUID
    body: str
    author_id: UUID | None
    at: datetime


class IncidentDetailOut(IncidentOut):
    details: dict[str, Any]
    evidences: list[EvidenceOut]
    detections: list[dict[str, Any]]
    history: list[HistoryOut]
    comments: list[CommentOut]


class IncidentPage(BaseModel):
    items: list[IncidentOut]
    total: int
    offset: int
    limit: int


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: IncidentStatus
    note: str | None = Field(default=None, max_length=4000)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


def _out(i: Incident) -> dict[str, Any]:
    return dict(id=i.id, camera_id=i.camera_id, camera_name=i.camera_name, track_id=i.track_id,
                violation_type=i.violation_type, status=i.status, confidence=i.confidence, started_at=i.started_at,
                confirmed_at=i.confirmed_at, ended_at=i.ended_at, end_reason=i.end_reason, zone_id=i.zone_id,
                profile_id=i.profile_id, profile_version=i.profile_version, model_id=i.model_id)


def _signed(container: Container, key: str, user_id: UUID) -> str:
    # La firma liga la URL al usuario que la pidió: el acceso al archivo queda auditado con su identidad.
    exp = int((datetime.now().astimezone() + EVIDENCE_URL_TTL).timestamp())
    sig = container.storage.sign(f"{key}#{user_id}", exp)
    return f"/api/v1/files/{key}?exp={exp}&u={user_id}&sig={sig}"


@router.get("/incidents", response_model=IncidentPage)
async def list_incidents(container: C, _: Reader,
                         status_: Annotated[list[IncidentStatus] | None, Query(alias="status")] = None,
                         camera_id: UUID | None = None, violation_type: str | None = None,
                         since: datetime | None = None, until: datetime | None = None,
                         offset: Annotated[int, Query(ge=0)] = 0,
                         limit: Annotated[int, Query(ge=1, le=200)] = 50) -> IncidentPage:
    flt = IncidentFilter(status=tuple(status_ or ()), camera_id=camera_id, violation_type=violation_type,
                         since=since, until=until)
    items, total = await container.incidents.list(flt, offset, limit)
    return IncidentPage(items=[IncidentOut(**_out(i)) for i in items], total=total, offset=offset, limit=limit)


@router.get("/incidents/{incident_id}", response_model=IncidentDetailOut)
async def get_incident(incident_id: UUID, container: C, principal: Reader) -> IncidentDetailOut:
    d = await container.incidents.detail(incident_id)
    evidences = [EvidenceOut(id=e.id, kind=e.kind, url=None if e.purged_at else _signed(container, e.storage_key,
                                                                                         principal.user_id),
                             sha256=e.sha256, width=e.width, height=e.height, captured_at=e.captured_at,
                             frame_id=e.frame_id, purged=e.purged_at is not None, meta=e.meta) for e in d.evidences]
    return IncidentDetailOut(**_out(d.incident), details=d.incident.details, evidences=evidences,
                             detections=d.detections,
                             history=[HistoryOut(action=h.action, from_status=h.from_status, to_status=h.to_status,
                                                 note=h.note, actor_id=h.actor_id, at=h.at) for h in d.history],
                             comments=[CommentOut(id=c.id, body=c.body, author_id=c.author_id, at=c.at)
                                       for c in d.comments])


@router.patch("/incidents/{incident_id}/status", response_model=IncidentOut)
async def change_status(incident_id: UUID, body: StatusIn, request: Request, container: C,
                        principal: Reviewer) -> IncidentOut:
    inc = await container.incidents.change_status(incident_id, body.status, body.note, actor=principal,
                                                  ip=client_ip(request))
    return IncidentOut(**_out(inc))


@router.post("/incidents/{incident_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(incident_id: UUID, body: CommentIn, container: C, principal: Reviewer) -> CommentOut:
    c = await container.incidents.add_comment(incident_id, body.body, actor=principal)
    return CommentOut(id=c.id, body=c.body, author_id=c.author_id, at=c.at)


@router.get("/files/{key:path}", include_in_schema=False)
async def get_file(key: str, exp: int, u: UUID, sig: str, request: Request, container: C) -> Response:
    if not container.storage.verify(f"{key}#{u}", exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "enlace inválido o caducado")
    incident_id, ev = await container.incidents.evidence_for_key(key)
    try:
        data = container.incidents.read_verified(ev)
    except EvidenceIntegrityError:
        await container.audit_evidence(u, incident_id, key, client_ip(request), tampered=True)
        raise HTTPException(status.HTTP_409_CONFLICT, "la evidencia no supera la verificación de integridad") from None
    await container.audit_evidence(u, incident_id, key, client_ip(request))
    return Response(data, media_type=ev.content_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-SHA256": ev.sha256,
                             "Content-Disposition": "inline"})
