"""Hub de datos en vivo: escucha PostgreSQL (``sv_live`` y ``sv_events``) y reparte a los WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from security_vision.core.domain.identity import Permission, Principal
from security_vision.infrastructure.messaging.postgres_bus import CHANNEL as EVENTS_CHANNEL
from security_vision.infrastructure.messaging.postgres_bus import PostgresMessageBus

log = logging.getLogger(__name__)
LIVE_CHANNEL = "sv_live"
# Eventos de dominio que se reenvían al navegador y permiso necesario para recibirlos
FORWARDED_EVENTS = {
    "incident.confirmed.v1": Permission.INCIDENTS_READ,
    "incident.updated.v1": Permission.INCIDENTS_READ,
    "camera.status_changed.v1": Permission.CAMERAS_READ,
    "person.compliance_changed.v1": Permission.CAMERAS_READ,
}


@dataclass(eq=False)
class LiveClient:
    principal: Principal
    queue: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(maxsize=200))
    cameras: set[str] | None = field(default_factory=set)  # None = todas
    dropped: int = 0

    def offer(self, message: str) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:  # cliente lento: se descarta (nunca bloquea al resto)
            self.dropped += 1


class LiveHub:
    def __init__(self, bus: PostgresMessageBus) -> None:
        self._bus = bus
        self.clients: set[LiveClient] = set()
        self.latest: dict[str, dict[str, Any]] = {}  # cámara -> último fotograma (para el pintado inicial)
        self._task: asyncio.Task | None = None
        self.received = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                async for channel, payload in self._bus.listen_raw([LIVE_CHANNEL, EVENTS_CHANNEL]):
                    self.received += 1
                    self._dispatch(channel, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("hub en vivo desconectado (%s); reintento en 3 s", exc)
                await asyncio.sleep(3)

    def _dispatch(self, channel: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if channel == LIVE_CHANNEL:
            cam = str(data.get("cam"))
            self.latest[cam] = data
            msg = json.dumps({"type": "frame", "data": data}, separators=(",", ":"))
            for c in list(self.clients):
                if c.principal.can(Permission.CAMERAS_READ) and (c.cameras is None or cam in c.cameras):
                    c.offer(msg)
        else:
            perm = FORWARDED_EVENTS.get(data.get("type", ""))
            if perm is None:
                return
            msg = json.dumps({"type": "event", "event": data["type"], "data": data.get("payload", {})},
                             separators=(",", ":"))
            for c in list(self.clients):
                if c.principal.can(perm):
                    c.offer(msg)
