"""Salud y métricas."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from prometheus_client import CONTENT_TYPE_LATEST

from security_vision.infrastructure.database.session import ping

from ..container import Container
from ..deps import get_container

router = APIRouter(tags=["system"])
log = logging.getLogger(__name__)


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(response: Response, container: Annotated[Container, Depends(get_container)]) -> dict[str, str]:
    try:
        await ping(container.engine)
        return {"status": "ok", "database": "ok"}
    except Exception:
        log.warning("readiness: base de datos no disponible", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "error"}


@router.get("/metrics", include_in_schema=False)
async def metrics(container: Annotated[Container, Depends(get_container)]) -> Response:
    return Response(container.metrics.render(), media_type=CONTENT_TYPE_LATEST)
