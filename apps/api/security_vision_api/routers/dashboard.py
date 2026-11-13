"""Panel principal (KPI y series) y WebSocket de datos en vivo."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi import status as http

from security_vision.core.domain.errors import AuthenticationError
from security_vision.core.domain.identity import Permission, Principal
from security_vision.infrastructure.database.repositories import stats as stats_repo

from ..container import Container
from ..deps import get_container, require
from ..live import LiveClient

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
C = Annotated[Container, Depends(get_container)]
Reader = Annotated[Principal, Depends(require(Permission.INCIDENTS_READ))]
RANGES = {"24h": (timedelta(hours=24), "hour"), "7d": (timedelta(days=7), "day"), "30d": (timedelta(days=30), "day")}


def _day_start(tz_offset_minutes: int) -> datetime:
    """Inicio del día en la zona horaria del navegador (el servidor trabaja en UTC)."""
    now = datetime.now(UTC) + timedelta(minutes=tz_offset_minutes)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local - timedelta(minutes=tz_offset_minutes)


@router.get("/dashboard/summary")
async def summary(container: C, _: Reader,
                  tz_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0) -> dict[str, Any]:
    data = await stats_repo.summary(container.engine, _day_start(tz_offset_minutes))
    live = container.live.latest if container.live else {}
    data["persons_now"] = sum(len(f.get("tracks", [])) for f in live.values()
                              if _fresh(f.get("ts")))
    data["generated_at"] = datetime.now(UTC).isoformat()
    return data


@router.get("/dashboard/series")
async def series(container: C, _: Reader,
                 range_: Annotated[str, Query(alias="range", pattern="^(24h|7d|30d)$")] = "24h",
                 camera_id: UUID | None = None) -> dict[str, Any]:
    span, step = RANGES[range_]
    since = datetime.now(UTC) - span
    return {"range": range_, "step": step,
            "compliance": await stats_repo.compliance_series(container.engine, since, step, camera_id),
            "incidents_by_day": await stats_repo.incidents_by_day(container.engine, since)}


def _fresh(ts: str | None, seconds: float = 10.0) -> bool:
    if not ts:
        return False
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(ts)).total_seconds() < seconds
    except ValueError:
        return False


@router.websocket("/ws")
async def live_ws(ws: WebSocket) -> None:
    """Protocolo: el cliente envía primero {"type":"auth","token":...}; después puede enviar
    {"type":"subscribe","cameras":[...] | "all"} y renovar el token con otro "auth"."""
    container: Container = ws.app.state.container
    origin = ws.headers.get("origin")
    if origin and origin not in container.settings.cors_origins and not _same_origin(ws, origin):
        await ws.close(code=http.WS_1008_POLICY_VIOLATION)  # protección contra CSWSH
        return
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        if first.get("type") != "auth":
            raise AuthenticationError("se esperaba auth")
        principal = await container.auth.authenticate(str(first.get("token", "")))
        expires = container.auth_token_expiry(str(first.get("token", "")))
    except (TimeoutError, ValueError, AuthenticationError, WebSocketDisconnect):
        with contextlib.suppress(Exception):
            await ws.close(code=4401)
        return
    hub = container.live
    client = LiveClient(principal=principal)
    hub.clients.add(client)  # type: ignore[union-attr]
    await ws.send_text(json.dumps({"type": "ready", "user": principal.email}))

    async def reader() -> None:
        nonlocal expires
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "subscribe":
                cams = msg.get("cameras")
                client.cameras = None if cams == "all" else {str(c) for c in (cams or [])}
                for cam, frame in list(hub.latest.items()):  # type: ignore[union-attr]
                    if client.cameras is None or cam in client.cameras:
                        client.offer(json.dumps({"type": "frame", "data": frame}, separators=(",", ":")))
            elif msg.get("type") == "auth":
                await container.auth.authenticate(str(msg.get("token", "")))
                expires = container.auth_token_expiry(str(msg.get("token", "")))

    async def writer() -> None:
        while True:
            try:
                message = await asyncio.wait_for(client.queue.get(), timeout=15)
            except TimeoutError:
                message = '{"type":"ping"}'
            if datetime.now(UTC) >= expires:
                await ws.close(code=4401)  # token caducado sin renovar
                return
            await ws.send_text(message)

    tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        hub.clients.discard(client)  # type: ignore[union-attr]


def _same_origin(ws: WebSocket, origin: str) -> bool:
    host = ws.headers.get("host", "")
    return origin.split("://", 1)[-1] == host
