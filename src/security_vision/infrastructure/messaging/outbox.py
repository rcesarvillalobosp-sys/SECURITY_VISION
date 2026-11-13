"""Relé del outbox: publica en el bus los eventos escritos transaccionalmente (al menos una vez).

Varios relés (API y workers) pueden convivir: ``FOR UPDATE SKIP LOCKED`` reparte las filas.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from security_vision.core.events.base import parse_event
from security_vision.core.interfaces.infrastructure import MessageBus

log = logging.getLogger(__name__)

_CLAIM = text("""
    SELECT id, payload FROM event_outbox
    WHERE published_at IS NULL AND attempts < :max_attempts
    ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED
""")


class OutboxRelay:
    def __init__(self, engine: AsyncEngine, bus: MessageBus, batch: int = 100, max_attempts: int = 20) -> None:
        self.engine = engine
        self.bus = bus
        self.batch = batch
        self.max_attempts = max_attempts
        self.published = 0
        self.failures = 0

    async def run_once(self) -> int:
        n = 0
        async with self.engine.begin() as conn:
            rows = (await conn.execute(_CLAIM, {"batch": self.batch, "max_attempts": self.max_attempts})).all()
            for row_id, payload in rows:
                try:
                    await self.bus.publish(parse_event(payload))
                except Exception as exc:
                    self.failures += 1
                    log.warning("outbox: no se pudo publicar el evento %s: %s", row_id, exc)
                    await conn.execute(text("UPDATE event_outbox SET attempts = attempts + 1 WHERE id = :id"),
                                       {"id": row_id})
                    continue
                await conn.execute(text("UPDATE event_outbox SET published_at = now(), attempts = attempts + 1 "
                                        "WHERE id = :id"), {"id": row_id})
                n += 1
        self.published += n
        return n

    async def run_forever(self, interval: float = 1.0) -> None:
        while True:
            try:
                n = await self.run_once()
            except Exception:
                log.exception("relé del outbox falló")
                n = 0
            await asyncio.sleep(0 if n >= self.batch else interval)
