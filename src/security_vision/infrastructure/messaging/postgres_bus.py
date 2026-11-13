"""Bus de eventos sobre PostgreSQL LISTEN/NOTIFY.

Adecuado para notificaciones de control (cambios de configuración, estado de cámaras) en
despliegues de un nodo sin Valkey. Semántica: difusión, *como mucho una vez*, sin
persistencia (un suscriptor desconectado pierde los eventos de ese intervalo). Por eso los
consumidores también reconcilian periódicamente contra la base de datos. Los eventos que
requieren durabilidad (incidentes) usarán outbox + Valkey Streams (Fase 6).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Sequence

import asyncpg

from security_vision.core.events.base import DomainEvent, parse_event
from security_vision.core.interfaces.infrastructure import MessageBus

log = logging.getLogger(__name__)
CHANNEL = "sv_events"
MAX_PAYLOAD = 7900  # límite de NOTIFY: 8000 bytes


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class PostgresMessageBus(MessageBus):
    def __init__(self, sqlalchemy_url: str) -> None:
        self._dsn = asyncpg_dsn(sqlalchemy_url)
        self._pub: asyncpg.Connection | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[asyncpg.Connection] = []

    async def _publisher(self) -> asyncpg.Connection:
        if self._pub is None or self._pub.is_closed():
            self._pub = await asyncpg.connect(self._dsn)
        return self._pub

    async def publish(self, event: DomainEvent) -> None:
        payload = json.dumps(event.envelope(), separators=(",", ":"))
        if len(payload.encode()) > MAX_PAYLOAD:
            raise ValueError(f"evento demasiado grande para NOTIFY ({event.event_type})")
        async with self._lock:
            conn = await self._publisher()
            await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, payload)

    async def subscribe(self, event_types: Sequence[str], group: str = "") -> AsyncIterator[DomainEvent]:
        wanted = set(event_types)
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        conn = await asyncpg.connect(self._dsn)
        self._listeners.append(conn)

        def on_notify(_c: object, _pid: int, _channel: str, payload: str) -> None:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("cola de eventos llena: se descarta una notificación")

        await conn.add_listener(CHANNEL, on_notify)
        try:
            while True:
                raw = await queue.get()
                try:
                    envelope = json.loads(raw)
                    if wanted and envelope.get("type") not in wanted:
                        continue
                    yield parse_event(envelope)
                except (ValueError, KeyError):
                    log.warning("evento inválido descartado")
        finally:
            with contextlib.suppress(Exception):
                await conn.remove_listener(CHANNEL, on_notify)
                await conn.close()
            if conn in self._listeners:
                self._listeners.remove(conn)

    async def publish_raw(self, channel: str, payload: str) -> None:
        """Mensajes efímeros de alta frecuencia (datos en vivo): sin outbox ni garantías."""
        if len(payload.encode()) > MAX_PAYLOAD:
            return
        async with self._lock:
            conn = await self._publisher()
            await conn.execute("SELECT pg_notify($1, $2)", channel, payload)

    async def listen_raw(self, channels: Sequence[str]) -> AsyncIterator[tuple[str, str]]:
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=5000)
        conn = await asyncpg.connect(self._dsn)
        self._listeners.append(conn)

        def on_notify(_c: object, _pid: int, channel: str, payload: str) -> None:
            with contextlib.suppress(asyncio.QueueFull):  # datos en vivo: perder un fotograma no importa
                queue.put_nowait((channel, payload))

        for ch in channels:
            await conn.add_listener(ch, on_notify)
        try:
            while True:
                yield await queue.get()
        finally:
            with contextlib.suppress(Exception):
                await conn.close()
            if conn in self._listeners:
                self._listeners.remove(conn)

    async def close(self) -> None:
        for c in [self._pub, *self._listeners]:
            if c is not None and not c.is_closed():
                with contextlib.suppress(Exception):
                    await c.close()
        self._pub = None
        self._listeners.clear()
