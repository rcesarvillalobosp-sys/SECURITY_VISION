"""Políticas de retención: purga de evidencias antiguas, historial de conectividad y archivos huérfanos.

Los metadatos del incidente se conservan (auditoría y estadísticas); solo se borran los archivos
de imagen, marcando la evidencia como ``purged_at``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from security_vision.core.interfaces.infrastructure import ObjectStorage
from security_vision.core.interfaces.repositories import UnitOfWork

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionDefaults:
    evidences_days: int = 90
    status_events_days: int = 30
    orphan_grace_hours: int = 24  # archivos sin fila en BD (transacción fallida) tras este margen


@dataclass
class PurgeReport:
    evidences_purged: int = 0
    orphans_deleted: int = 0
    status_events_deleted: int = 0
    errors: list[str] = field(default_factory=list)


class RetentionService:
    def __init__(self, uow: Callable[[], UnitOfWork], storage: ObjectStorage, defaults: RetentionDefaults,
                 status_events_purger: Callable[[datetime], object] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._uow = uow
        self._storage = storage
        self._defaults = defaults
        self._purge_status = status_events_purger
        self._now = clock

    async def purge(self, batch: int = 500) -> PurgeReport:
        now = self._now()
        report = PurgeReport()
        cutoff = now - timedelta(days=self._defaults.evidences_days)
        while True:
            async with self._uow() as uow:
                old = await uow.incidents.evidences_older_than(cutoff, None, batch)
                for ev in old:
                    try:
                        await asyncio.to_thread(self._storage.delete, ev.storage_key)
                    except Exception as exc:  # se reintenta en la próxima purga
                        report.errors.append(f"{ev.storage_key}: {exc}")
                        continue
                    await uow.incidents.mark_purged(ev.id, now)
                    report.evidences_purged += 1
                await uow.commit()
            if len(old) < batch:
                break
        # Huérfanos: archivos de evidencia sin fila (p. ej. transacción fallida tras escribirlos)
        async with self._uow() as uow:
            known = await uow.incidents.all_storage_keys()
        grace = now - timedelta(hours=self._defaults.orphan_grace_hours)
        for obj in await asyncio.to_thread(lambda: list(self._storage.list("evidences", older_than=grace))):
            if obj.key not in known:
                await asyncio.to_thread(self._storage.delete, obj.key)
                report.orphans_deleted += 1
        if self._purge_status:
            res = self._purge_status(now - timedelta(days=self._defaults.status_events_days))
            if asyncio.iscoroutine(res):
                res = await res
            report.status_events_deleted = int(res or 0)  # type: ignore[arg-type]
        log.info("purga de retención", extra={"evidences": report.evidences_purged,
                                              "orphans": report.orphans_deleted,
                                              "status_events": report.status_events_deleted})
        return report
