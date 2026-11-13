"""Administración: auditoría, modelos de detección y canales de alerta."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from security_vision.core.domain.alerts import AlertChannel, AlertDelivery
from security_vision.core.domain.identity import Permission, Principal

from ..container import Container
from ..deps import client_ip, get_container, require
from ..schemas import Page

router = APIRouter(prefix="/api/v1", tags=["admin"])
C = Annotated[Container, Depends(get_container)]


# ------------------------------------------------------------------ auditoría
class AuditOut(BaseModel):
    id: int
    at: datetime
    actor_id: UUID | None
    actor_email: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None


@router.get("/audit", response_model=Page[AuditOut])
async def audit(container: C, _: Annotated[Principal, Depends(require(Permission.AUDIT_READ))],
                action: Annotated[str | None, Query(max_length=100)] = None,
                entity_type: Annotated[str | None, Query(max_length=64)] = None,
                entity_id: Annotated[str | None, Query(max_length=64)] = None,
                actor_id: UUID | None = None,
                offset: Annotated[int, Query(ge=0)] = 0,
                limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Page[AuditOut]:
    items, total = await container.audit_query(action_prefix=action, entity_type=entity_type, entity_id=entity_id,
                                               actor_id=actor_id, offset=offset, limit=limit)
    return Page[AuditOut](items=[AuditOut(**i) for i in items], total=total, offset=offset, limit=limit)


# ------------------------------------------------------------------ modelos
class ModelOut(BaseModel):
    model_id: str
    architecture: str | None
    labels: list[str]
    canonical_classes: list[str]
    input_size: list[int] | None
    score_threshold: float | None
    license: str | None
    weights_license: str | None
    weights_source: str | None
    dataset_ref: str | None
    notes: str | None
    metrics: dict[str, Any]
    artifact_present: bool
    error: str | None
    active: bool


class ModelsOut(BaseModel):
    active_model: str | None
    loaded: dict[str, Any] | None  # lo que el worker informa tener cargado
    models: list[ModelOut]


class ActivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=3, max_length=120)


@router.get("/models", response_model=ModelsOut)
async def list_models(container: C, _: Annotated[Principal, Depends(require(Permission.CAMERAS_READ))]
                      ) -> ModelsOut:
    assert container.models is not None
    infos, active, loaded = await container.models.state()
    out = []
    for i in infos:
        s = i.spec
        out.append(ModelOut(
            model_id=i.model_id, architecture=s.architecture if s else None, labels=s.labels if s else [],
            canonical_classes=sorted(set(s.class_map.values())) if s else [],
            input_size=list(s.input_size) if s else None, score_threshold=s.score_threshold if s else None,
            license=s.license if s else None, weights_license=s.weights_license if s else None,
            weights_source=s.weights_source if s else None, dataset_ref=s.dataset_ref if s else None,
            notes=s.notes if s else None, metrics=s.metrics if s else {}, artifact_present=i.artifact_present,
            error=i.error, active=i.model_id == active))
    return ModelsOut(active_model=active, loaded=loaded, models=out)


@router.put("/models/active", response_model=ModelsOut)
async def activate_model(body: ActivateIn, request: Request, container: C,
                         principal: Annotated[Principal, Depends(require(Permission.MODELS_WRITE))]) -> ModelsOut:
    assert container.models is not None
    await container.models.activate(body.model_id, actor=principal, ip=client_ip(request))
    return await list_models(container, principal)


# ------------------------------------------------------------------ alertas
AlertsAdmin = Annotated[Principal, Depends(require(Permission.ALERTS_WRITE))]


class ChannelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(webhook|email)$")
    enabled: bool = True
    config: dict[str, Any]
    secret: str | None = Field(default=None, max_length=500)
    violation_types: list[str] = Field(default_factory=list, max_length=10)
    camera_ids: list[str] = Field(default_factory=list, max_length=500)
    attach_evidence: bool = True


class ChannelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, max_length=500)  # "" = quitarlo
    violation_types: list[str] | None = Field(default=None, max_length=10)
    camera_ids: list[str] | None = Field(default=None, max_length=500)
    attach_evidence: bool | None = None


class ChannelOut(BaseModel):
    id: UUID
    name: str
    kind: str
    enabled: bool
    config: dict[str, Any]
    has_secret: bool
    violation_types: list[str]
    camera_ids: list[str]
    attach_evidence: bool
    created_at: datetime | None


class DeliveryOut(BaseModel):
    id: UUID
    channel_id: UUID
    incident_id: UUID
    status: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    response_code: int | None
    created_at: datetime | None
    sent_at: datetime | None


class TestOut(BaseModel):
    ok: bool
    detail: str | None
    response_code: int | None


class AlertsInfo(BaseModel):
    email_available: bool
    webhook_allow_private: bool
    public_web_url: str | None
    dispatcher: dict[str, int] | None


def _ch(c: AlertChannel) -> ChannelOut:
    return ChannelOut(id=c.id, name=c.name, kind=c.kind.value, enabled=c.enabled, config=c.config,
                      has_secret=c.has_secret, violation_types=c.violation_types, camera_ids=c.camera_ids,
                      attach_evidence=c.attach_evidence, created_at=c.created_at)


def _d(d: AlertDelivery) -> DeliveryOut:
    return DeliveryOut(id=d.id, channel_id=d.channel_id, incident_id=d.incident_id, status=d.status.value,
                       attempts=d.attempts, next_attempt_at=d.next_attempt_at, last_error=d.last_error,
                       response_code=d.response_code, created_at=d.created_at, sent_at=d.sent_at)


@router.get("/alert-channels/info", response_model=AlertsInfo)
async def alerts_info(container: C, _: AlertsAdmin) -> AlertsInfo:
    s = container.settings
    d = container.dispatcher
    return AlertsInfo(email_available=bool(s.smtp_host and s.smtp_from),
                      webhook_allow_private=s.alert_webhook_allow_private, public_web_url=s.public_web_url,
                      dispatcher={"sent": d.sent, "retried": d.retried, "failed": d.failed}
                      if d and s.alerts_enabled else None)


@router.get("/alert-channels", response_model=list[ChannelOut])
async def list_channels(container: C, _: AlertsAdmin) -> list[ChannelOut]:
    assert container.alerts is not None
    return [_ch(c) for c in await container.alerts.list()]


@router.post("/alert-channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelIn, request: Request, container: C, principal: AlertsAdmin) -> ChannelOut:
    assert container.alerts is not None
    c = await container.alerts.create(name=body.name, kind=body.kind, config=body.config, secret=body.secret or None,
                                      violation_types=body.violation_types, camera_ids=body.camera_ids,
                                      attach_evidence=body.attach_evidence, enabled=body.enabled, actor=principal,
                                      ip=client_ip(request))
    return _ch(c)


@router.patch("/alert-channels/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: UUID, body: ChannelPatch, request: Request, container: C,
                         principal: AlertsAdmin) -> ChannelOut:
    assert container.alerts is not None
    changes = body.model_dump(exclude_unset=True)
    if changes.get("secret") is None:
        changes.pop("secret", None)  # null = no tocar
    return _ch(await container.alerts.update(channel_id, changes, actor=principal, ip=client_ip(request)))


@router.delete("/alert-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: UUID, request: Request, container: C, principal: AlertsAdmin) -> Response:
    assert container.alerts is not None
    await container.alerts.delete(channel_id, actor=principal, ip=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alert-channels/{channel_id}/test", response_model=TestOut)
async def test_channel(channel_id: UUID, request: Request, container: C, principal: AlertsAdmin) -> TestOut:
    assert container.alerts is not None
    r = await container.alerts.send_test(channel_id, actor=principal, ip=client_ip(request))
    return TestOut(ok=r.ok, detail=r.detail, response_code=r.response_code)


@router.post("/alert-deliveries/{delivery_id}/retry", response_model=DeliveryOut)
async def retry_delivery(delivery_id: UUID, request: Request, container: C, principal: AlertsAdmin) -> DeliveryOut:
    assert container.alerts is not None
    d = await container.alerts.retry_delivery(delivery_id, actor=principal, ip=client_ip(request))
    if container.dispatcher is not None:
        container.dispatcher.wake()
    return _d(d)


@router.get("/alert-deliveries", response_model=Page[DeliveryOut])
async def deliveries(container: C, _: AlertsAdmin, channel_id: UUID | None = None, incident_id: UUID | None = None,
                     status_: Annotated[str | None, Query(alias="status", pattern="^(pending|sent|failed)$")] = None,
                     offset: Annotated[int, Query(ge=0)] = 0,
                     limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Page[DeliveryOut]:
    assert container.alerts is not None
    items, total = await container.alerts.deliveries(channel_id=channel_id, incident_id=incident_id, status=status_,
                                                     offset=offset, limit=limit)
    return Page[DeliveryOut](items=[_d(d) for d in items], total=total, offset=offset, limit=limit)
