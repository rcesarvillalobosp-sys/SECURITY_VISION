"""Adaptadores SQL de canales de alerta, cola de entregas y ajustes del sistema."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from security_vision.core.domain.alerts import (
    AlertChannel,
    AlertDelivery,
    AlertMessage,
    ChannelKind,
    DeliveryStatus,
    SendResult,
)
from security_vision.core.domain.compliance import violation_label
from security_vision.core.interfaces.alerts import AlertChannelRepository, AlertQueue, SettingsRepository

from ..models import AlertChannelRow, AlertDeliveryRow, EvidenceRow, IncidentRow, SystemSettingRow


def _channel(r: AlertChannelRow) -> AlertChannel:
    return AlertChannel(id=r.id, name=r.name, kind=ChannelKind(r.kind), enabled=r.enabled, config=dict(r.config),
                        has_secret=r.secret_ciphertext is not None, violation_types=list(r.violation_types),
                        camera_ids=list(r.camera_ids), attach_evidence=r.attach_evidence, created_at=r.created_at)


def _delivery(r: AlertDeliveryRow) -> AlertDelivery:
    return AlertDelivery(id=r.id, channel_id=r.channel_id, incident_id=r.incident_id,
                         status=DeliveryStatus(r.status), attempts=r.attempts, next_attempt_at=r.next_attempt_at,
                         last_error=r.last_error, response_code=r.response_code, created_at=r.created_at,
                         sent_at=r.sent_at)


class SqlAlertChannelRepository(AlertChannelRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list(self) -> list[AlertChannel]:
        rows = await self.s.scalars(select(AlertChannelRow).order_by(AlertChannelRow.name))
        return [_channel(r) for r in rows]

    async def get(self, channel_id: UUID) -> AlertChannel | None:
        r = await self.s.get(AlertChannelRow, channel_id)
        return _channel(r) if r else None

    async def get_secret(self, channel_id: UUID) -> bytes | None:
        return await self.s.scalar(select(AlertChannelRow.secret_ciphertext).where(AlertChannelRow.id == channel_id))

    async def save(self, channel: AlertChannel, *, secret: bytes | None, keep_secret: bool, new: bool,
                   actor_id: UUID | None) -> None:
        values: dict[str, Any] = dict(name=channel.name, kind=channel.kind.value, enabled=channel.enabled,
                                      config=channel.config, violation_types=channel.violation_types,
                                      camera_ids=channel.camera_ids, attach_evidence=channel.attach_evidence)
        if not keep_secret:
            values["secret_ciphertext"] = secret
        if new:
            self.s.add(AlertChannelRow(id=channel.id, created_by=actor_id, **values))
        else:
            await self.s.execute(update(AlertChannelRow).where(AlertChannelRow.id == channel.id).values(**values))
        await self.s.flush()

    async def delete(self, channel_id: UUID) -> None:
        await self.s.execute(delete(AlertChannelRow).where(AlertChannelRow.id == channel_id))

    async def requeue(self, delivery_id: UUID) -> AlertDelivery | None:
        row = await self.s.scalar(
            update(AlertDeliveryRow).where(AlertDeliveryRow.id == delivery_id, AlertDeliveryRow.status == "failed")
            .values(status="pending", next_attempt_at=func.now()).returning(AlertDeliveryRow))
        await self.s.flush()
        return _delivery(row) if row else None

    async def deliveries(self, *, channel_id: UUID | None = None, incident_id: UUID | None = None,
                         status: str | None = None, offset: int = 0, limit: int = 50
                         ) -> tuple[list[AlertDelivery], int]:
        conds = []
        if channel_id:
            conds.append(AlertDeliveryRow.channel_id == channel_id)
        if incident_id:
            conds.append(AlertDeliveryRow.incident_id == incident_id)
        if status:
            conds.append(AlertDeliveryRow.status == status)
        total = (await self.s.execute(select(func.count()).select_from(AlertDeliveryRow).where(*conds))).scalar_one()
        rows = await self.s.scalars(select(AlertDeliveryRow).where(*conds)
                                    .order_by(AlertDeliveryRow.created_at.desc()).offset(offset).limit(limit))
        return [_delivery(r) for r in rows], total


class SqlSettingsRepository(SettingsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, key: str) -> dict[str, Any] | None:
        return await self.s.scalar(select(SystemSettingRow.value).where(SystemSettingRow.key == key))

    async def set(self, key: str, value: dict[str, Any], *, actor_id: UUID | None) -> None:
        stmt = insert(SystemSettingRow).values(key=key, value=value, updated_by=actor_id)
        await self.s.execute(stmt.on_conflict_do_update(
            index_elements=[SystemSettingRow.key],
            set_={"value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


class SqlAlertQueue(AlertQueue):
    """Cola sobre ``alert_deliveries``. La concesión (aplazar ``next_attempt_at``) evita que dos procesos
    envíen la misma entrega a la vez sin mantener bloqueos durante el envío por red."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def plan(self, channels: Sequence[AlertChannel], since: datetime) -> int:
        created = 0
        async with self.engine.begin() as conn:
            for ch in channels:
                if not ch.enabled:
                    continue
                conds = [IncidentRow.confirmed_at >= max(since, ch.created_at or since)]
                if ch.violation_types:
                    conds.append(IncidentRow.violation_type.in_(ch.violation_types))
                if ch.camera_ids:
                    conds.append(IncidentRow.camera_id.in_([UUID(c) for c in ch.camera_ids]))
                exists = select(AlertDeliveryRow.id).where(and_(AlertDeliveryRow.channel_id == ch.id,
                                                                AlertDeliveryRow.incident_id == IncidentRow.id))
                ids = (await conn.execute(select(IncidentRow.id).where(*conds, ~exists.exists()))).scalars().all()
                if not ids:
                    continue
                stmt = insert(AlertDeliveryRow).values(
                    [{"channel_id": ch.id, "incident_id": i, "status": "pending"} for i in ids])
                res = await conn.execute(stmt.on_conflict_do_nothing(constraint="uq_alert_deliveries_channel_incident"))
                created += res.rowcount or 0
        return created

    async def claim_due(self, limit: int, lease: timedelta) -> list[AlertDelivery]:
        async with self.engine.begin() as conn:
            rows = (await conn.execute(text("""
                UPDATE alert_deliveries SET next_attempt_at = now() + :lease
                WHERE id IN (SELECT id FROM alert_deliveries
                             WHERE status = 'pending' AND next_attempt_at <= now()
                             ORDER BY next_attempt_at LIMIT :limit FOR UPDATE SKIP LOCKED)
                RETURNING id, channel_id, incident_id, status, attempts, next_attempt_at, last_error,
                          response_code, created_at, sent_at
            """), {"lease": lease, "limit": limit})).all()
        return [AlertDelivery(id=r.id, channel_id=r.channel_id, incident_id=r.incident_id,
                              status=DeliveryStatus(r.status), attempts=r.attempts, next_attempt_at=r.next_attempt_at,
                              last_error=r.last_error, response_code=r.response_code, created_at=r.created_at,
                              sent_at=r.sent_at) for r in rows]

    async def finish(self, delivery_id: UUID, result: SendResult, *, retry_in: timedelta | None) -> None:
        values: dict[str, Any] = {"attempts": AlertDeliveryRow.attempts + 1, "response_code": result.response_code,
                                  "last_error": None if result.ok else (result.detail or "error")[:2000]}
        if result.ok:
            values |= {"status": "sent", "sent_at": func.now()}
        elif retry_in is None:
            values |= {"status": "failed"}
        else:
            values |= {"next_attempt_at": func.now() + retry_in}
        async with self.engine.begin() as conn:
            await conn.execute(update(AlertDeliveryRow).where(AlertDeliveryRow.id == delivery_id).values(**values))

    async def message_for(self, delivery: AlertDelivery, *, link_base: str | None) -> AlertMessage | None:
        async with self.engine.connect() as conn:
            inc = (await conn.execute(select(IncidentRow).where(IncidentRow.id == delivery.incident_id))).first()
            if inc is None:
                return None
            ev = (await conn.execute(select(EvidenceRow.storage_key).where(
                EvidenceRow.incident_id == inc.id, EvidenceRow.kind == "annotated",
                EvidenceRow.purged_at.is_(None)).limit(1))).scalar()
        return AlertMessage(
            delivery_id=str(delivery.id), incident_id=str(inc.id),
            camera_id=str(inc.camera_id) if inc.camera_id else None, camera_name=inc.camera_name,
            violation_type=inc.violation_type, violation_label=violation_label(inc.violation_type),
            confidence=inc.confidence, confirmed_at=inc.confirmed_at,
            zone_id=str(inc.zone_id) if inc.zone_id else None, model_id=inc.model_id,
            link=f"{link_base.rstrip('/')}/incidents/{inc.id}" if link_base else None, evidence_key=ev)
