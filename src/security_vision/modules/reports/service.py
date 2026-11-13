"""Generación de reportes periódicos en el formato pedido (PDF, Excel o JSON para la web)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from security_vision.core.domain.errors import ValidationError
from security_vision.core.domain.identity import Principal
from security_vision.core.domain.reports import PERIOD_LABEL, ReportData, ReportPeriod, period_range
from security_vision.core.interfaces.alerts import ReportRenderer, ReportSource
from security_vision.core.interfaces.repositories import UnitOfWork

MAX_INCIDENTS = 2000


@dataclass(frozen=True)
class RenderedReport:
    data: bytes
    content_type: str
    filename: str


class ReportService:
    def __init__(self, uow: Callable[[], UnitOfWork], source: ReportSource,
                 renderers: Mapping[str, ReportRenderer]) -> None:
        self._uow = uow
        self._source = source
        self.renderers = renderers

    async def build(self, period: ReportPeriod, day: date, *, tz_offset_minutes: int,
                    camera_ids: Sequence[UUID] | None, actor: Principal) -> ReportData:
        start, end = period_range(period, day, tz_offset_minutes)
        r = await self._source.build(start, end, tz_offset_minutes=tz_offset_minutes, camera_ids=camera_ids,
                                     max_incidents=MAX_INCIDENTS)
        r.period = period.value
        r.title = f"Reporte {PERIOD_LABEL[period].lower()} de seguridad EPP"
        r.generated_by = actor.email
        return r

    async def render(self, period: ReportPeriod, day: date, fmt: str, *, tz_offset_minutes: int,
                     camera_ids: Sequence[UUID] | None, actor: Principal, ip: str | None = None) -> RenderedReport:
        renderer = self.renderers.get(fmt)
        if renderer is None:
            raise ValidationError(f"formato no disponible: {fmt}")
        r = await self.build(period, day, tz_offset_minutes=tz_offset_minutes, camera_ids=camera_ids, actor=actor)
        data = await asyncio.to_thread(renderer.render, r)  # CPU: fuera del bucle de eventos
        async with self._uow() as uow:
            await uow.audit.record("report.generated", actor_id=actor.user_id, entity_type="report",
                                   entity_id=period.value,
                                   after={"format": fmt, "day": day.isoformat(), "start": r.start.isoformat(),
                                          "end": r.end.isoformat(), "cameras": [str(c) for c in camera_ids or []],
                                          "incidents": r.totals.get("incidents", 0), "bytes": len(data)}, ip=ip)
            await uow.commit()
        local_start = r.local(r.start)
        name = f"reporte-{period.value}-{local_start:%Y-%m-%d}.{renderer.format}"
        return RenderedReport(data, renderer.content_type, name)
