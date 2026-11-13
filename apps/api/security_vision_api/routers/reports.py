"""Reportes diario, semanal y mensual: JSON (vista previa web), PDF y Excel."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from security_vision.core.domain.identity import Permission, Principal
from security_vision.core.domain.reports import ReportPeriod

from ..container import Container
from ..deps import client_ip, get_container, require

router = APIRouter(prefix="/api/v1", tags=["reports"])
C = Annotated[Container, Depends(get_container)]
Reader = Annotated[Principal, Depends(require(Permission.REPORTS_READ))]


@router.get("/reports/{period}", response_model=None)
async def report(period: ReportPeriod, request: Request, container: C, principal: Reader,
                 day: Annotated[date, Query(alias="date")],
                 fmt: Annotated[str, Query(alias="format", pattern="^(json|pdf|xlsx)$")] = "json",
                 tz_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0,
                 camera_id: Annotated[list[UUID] | None, Query(max_length=100)] = None) -> Any:
    assert container.reports is not None
    if fmt == "json":
        r = await container.reports.build(period, day, tz_offset_minutes=tz_offset_minutes, camera_ids=camera_id,
                                          actor=principal)
        data = asdict(r)
        data["compliance_pct"] = r.compliance_pct
        data["unverifiable_share_pct"] = r.unverifiable_share_pct
        for c, src in zip(data["cameras"], r.cameras, strict=True):
            c["compliance_pct"] = src.compliance_pct
        for d, src in zip(data["days"], r.days, strict=True):
            d["compliance_pct"] = src.compliance_pct
        return data
    out = await container.reports.render(period, day, fmt, tz_offset_minutes=tz_offset_minutes,
                                         camera_ids=camera_id, actor=principal, ip=client_ip(request))
    return Response(out.data, media_type=out.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{out.filename}"'})
