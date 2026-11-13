"""Puertos de alertas, ajustes del sistema y reportes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..domain.alerts import AlertChannel, AlertDelivery, AlertMessage, SendResult
from ..domain.reports import ReportData


class AlertChannelRepository(ABC):
    """Canales de alerta (dentro de la unidad de trabajo, junto a la auditoría)."""

    @abstractmethod
    async def list(self) -> list[AlertChannel]: ...

    @abstractmethod
    async def get(self, channel_id: UUID) -> AlertChannel | None: ...

    @abstractmethod
    async def get_secret(self, channel_id: UUID) -> bytes | None: ...

    @abstractmethod
    async def save(self, channel: AlertChannel, *, secret: bytes | None, keep_secret: bool, new: bool,
                   actor_id: UUID | None) -> None:
        """``keep_secret``: conservar el secreto guardado (no se recibió uno nuevo)."""

    @abstractmethod
    async def delete(self, channel_id: UUID) -> None: ...

    @abstractmethod
    async def requeue(self, delivery_id: UUID) -> AlertDelivery | None:
        """Vuelve a poner en cola una entrega FALLIDA (envío inmediato). None si no existe o no está fallida."""

    @abstractmethod
    async def deliveries(self, *, channel_id: UUID | None = None, incident_id: UUID | None = None,
                         status: str | None = None, offset: int = 0, limit: int = 50
                         ) -> tuple[list[AlertDelivery], int]: ...


class AlertQueue(ABC):
    """Cola persistente de entregas. Seguro con varios procesos (reparto por concesión temporal)."""

    @abstractmethod
    async def plan(self, channels: Sequence[AlertChannel], since: datetime) -> int:
        """Crea entregas pendientes para los incidentes confirmados desde ``since`` que encajen en los
        filtros de cada canal y aún no tengan entrega. Idempotente. Devuelve cuántas creó."""

    @abstractmethod
    async def claim_due(self, limit: int, lease: timedelta) -> list[AlertDelivery]:
        """Toma las entregas pendientes vencidas y las aplaza ``lease`` (nadie más las toma mientras)."""

    @abstractmethod
    async def finish(self, delivery_id: UUID, result: SendResult, *, retry_in: timedelta | None) -> None:
        """Registra el intento: enviado, reintento en ``retry_in`` o fallido definitivo (``retry_in`` None)."""

    @abstractmethod
    async def message_for(self, delivery: AlertDelivery, *, link_base: str | None) -> AlertMessage | None:
        """Construye el mensaje del incidente, con la clave de su evidencia anotada (sin cargarla).
        None si el incidente ya no existe."""


class AlertSender(ABC):
    """Adaptador de envío de un tipo de canal (webhook, email...)."""

    kind: str

    @abstractmethod
    async def send(self, channel: AlertChannel, secret: str | None, message: AlertMessage) -> SendResult: ...


class SettingsRepository(ABC):
    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def set(self, key: str, value: dict[str, Any], *, actor_id: UUID | None) -> None: ...


class ReportSource(ABC):
    """Consultas de solo lectura para construir reportes."""

    @abstractmethod
    async def build(self, start: datetime, end: datetime, *, tz_offset_minutes: int,
                    camera_ids: Sequence[UUID] | None, max_incidents: int) -> ReportData: ...


class ReportRenderer(ABC):
    format: str  # "pdf" | "xlsx"
    content_type: str

    @abstractmethod
    def render(self, report: ReportData) -> bytes: ...
