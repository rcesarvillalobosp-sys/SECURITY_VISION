"""Casos de uso de alertas: configuración de canales y despacho fiable de incidentes confirmados."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from security_vision.core.domain.alerts import (
    MAX_ATTEMPTS,
    AlertChannel,
    AlertDelivery,
    AlertMessage,
    ChannelKind,
    SendResult,
    next_retry,
)
from security_vision.core.domain.compliance import EVALUABLE_PPE, violation_label
from security_vision.core.domain.errors import ConflictError, NotFoundError, ValidationError
from security_vision.core.domain.identity import Principal
from security_vision.core.domain.ids import uuid7
from security_vision.core.interfaces.alerts import AlertQueue, AlertSender
from security_vision.core.interfaces.infrastructure import MessageBus, ObjectStorage, SecretCipher
from security_vision.core.interfaces.repositories import UnitOfWork

log = logging.getLogger(__name__)

# Validadores de configuración por tipo (los aporta la composición: dependen de adaptadores)
ConfigValidator = Callable[[dict[str, Any]], dict[str, Any]]


def _aad(channel_id: UUID) -> bytes:
    return f"alert_channel:{channel_id}".encode()


def _view(c: AlertChannel) -> dict[str, Any]:
    return {"name": c.name, "kind": c.kind.value, "enabled": c.enabled, "config": c.config,
            "violation_types": c.violation_types, "camera_ids": c.camera_ids, "attach_evidence": c.attach_evidence,
            "has_secret": c.has_secret}


class AlertService:
    def __init__(self, uow: Callable[[], UnitOfWork], cipher: SecretCipher,
                 senders: Mapping[str, AlertSender], validators: Mapping[str, ConfigValidator],
                 storage: ObjectStorage | None = None, link_base: str | None = None) -> None:
        self._uow = uow
        self._cipher = cipher
        self.senders = senders
        self._validators = validators
        self._storage = storage
        self._link_base = link_base

    async def list(self) -> list[AlertChannel]:
        async with self._uow() as uow:
            return await uow.alerts.list()

    async def get(self, channel_id: UUID) -> AlertChannel:
        async with self._uow() as uow:
            ch = await uow.alerts.get(channel_id)
        if ch is None:
            raise NotFoundError("canal no encontrado")
        return ch

    def _validate(self, ch: AlertChannel) -> AlertChannel:
        if not ch.name.strip():
            raise ValidationError("nombre obligatorio")
        bad = set(ch.violation_types) - set(EVALUABLE_PPE)
        if bad:
            raise ValidationError(f"tipos de incumplimiento desconocidos: {sorted(bad)}")
        for cid in ch.camera_ids:
            try:
                UUID(cid)
            except ValueError as exc:
                raise ValidationError(f"id de cámara inválido: {cid}") from exc
        validator = self._validators.get(ch.kind.value)
        if validator is None:
            raise ValidationError(f"tipo de canal no disponible: {ch.kind.value}")
        return replace(ch, name=ch.name.strip(), config=validator(dict(ch.config)),
                       violation_types=sorted(set(ch.violation_types)), camera_ids=sorted(set(ch.camera_ids)))

    async def create(self, *, name: str, kind: str, config: dict[str, Any], secret: str | None,
                     violation_types: list[str], camera_ids: list[str], attach_evidence: bool, enabled: bool,
                     actor: Principal, ip: str | None = None) -> AlertChannel:
        try:
            k = ChannelKind(kind)
        except ValueError as exc:
            raise ValidationError(f"tipo de canal inválido: {kind}") from exc
        ch = self._validate(AlertChannel(id=uuid7(), name=name, kind=k, enabled=enabled, config=config,
                                         has_secret=bool(secret), violation_types=violation_types,
                                         camera_ids=camera_ids, attach_evidence=attach_evidence))
        enc = self._cipher.encrypt(secret, _aad(ch.id)) if secret else None
        async with self._uow() as uow:
            if any(c.name == ch.name for c in await uow.alerts.list()):
                raise ConflictError("ya existe un canal con ese nombre")
            await uow.alerts.save(ch, secret=enc, keep_secret=False, new=True, actor_id=actor.user_id)
            await uow.audit.record("alerts.channel_created", actor_id=actor.user_id, entity_type="alert_channel",
                                   entity_id=str(ch.id), after=_view(ch), ip=ip)
            await uow.commit()
        return await self.get(ch.id)

    async def update(self, channel_id: UUID, changes: dict[str, Any], *, actor: Principal,
                     ip: str | None = None) -> AlertChannel:
        """``changes["secret"]``: str = nuevo secreto, "" = quitarlo, ausente = conservarlo."""
        async with self._uow() as uow:
            cur = await uow.alerts.get(channel_id)
            if cur is None:
                raise NotFoundError("canal no encontrado")
            fields = {k: v for k, v in changes.items() if k in {"name", "enabled", "config", "violation_types",
                                                                "camera_ids", "attach_evidence"}}
            new = self._validate(replace(cur, **fields))
            keep = "secret" not in changes
            enc = None
            if not keep and changes["secret"]:
                enc = self._cipher.encrypt(changes["secret"], _aad(channel_id))
            if new.name != cur.name and any(c.name == new.name for c in await uow.alerts.list()):
                raise ConflictError("ya existe un canal con ese nombre")
            await uow.alerts.save(new, secret=enc, keep_secret=keep, new=False, actor_id=actor.user_id)
            after = _view(new) | {"has_secret": cur.has_secret if keep else bool(enc)}
            await uow.audit.record("alerts.channel_updated", actor_id=actor.user_id, entity_type="alert_channel",
                                   entity_id=str(channel_id), before=_view(cur), after=after, ip=ip)
            await uow.commit()
        return await self.get(channel_id)

    async def delete(self, channel_id: UUID, *, actor: Principal, ip: str | None = None) -> None:
        async with self._uow() as uow:
            cur = await uow.alerts.get(channel_id)
            if cur is None:
                raise NotFoundError("canal no encontrado")
            await uow.alerts.delete(channel_id)
            await uow.audit.record("alerts.channel_deleted", actor_id=actor.user_id, entity_type="alert_channel",
                                   entity_id=str(channel_id), before=_view(cur), ip=ip)
            await uow.commit()

    async def secret_for(self, channel_id: UUID) -> str | None:
        async with self._uow() as uow:
            enc = await uow.alerts.get_secret(channel_id)
        return self._cipher.decrypt(enc, _aad(channel_id)) if enc else None

    async def load_evidence(self, message: AlertMessage, channel: AlertChannel) -> AlertMessage:
        if not (channel.attach_evidence and message.evidence_key and self._storage):
            return message
        try:
            data = await asyncio.to_thread(self._storage.get, message.evidence_key)
        except Exception as exc:  # la alerta sale igualmente, sin adjunto
            log.warning("no se pudo leer la evidencia %s: %s", message.evidence_key, exc)
            return message
        return replace(message, evidence=(f"incidente-{message.incident_id}.jpg", data, "image/jpeg"))

    async def send_test(self, channel_id: UUID, *, actor: Principal, ip: str | None = None) -> SendResult:
        """Envía un mensaje de prueba marcado como tal (no crea incidente ni entrega)."""
        ch = await self.get(channel_id)
        sender = self.senders.get(ch.kind.value)
        if sender is None:
            raise ValidationError(f"tipo de canal no disponible: {ch.kind.value}")
        now = datetime.now(UTC)
        msg = AlertMessage(delivery_id=f"test-{uuid7()}", incident_id="00000000-0000-0000-0000-000000000000",
                           camera_id=None, camera_name="(prueba)", violation_type="helmet",
                           violation_label=violation_label("helmet"), confidence=0.0, confirmed_at=now,
                           zone_id=None, model_id=None, link=self._link_base, test=True)
        result = await sender.send(ch, await self.secret_for(channel_id), msg)
        async with self._uow() as uow:
            await uow.audit.record("alerts.channel_tested", actor_id=actor.user_id, entity_type="alert_channel",
                                   entity_id=str(channel_id),
                                   after={"ok": result.ok, "detail": result.detail, "code": result.response_code},
                                   ip=ip)
            await uow.commit()
        return result

    async def retry_delivery(self, delivery_id: UUID, *, actor: Principal, ip: str | None = None) -> AlertDelivery:
        """Reintento manual de una entrega fallida (p. ej. tras corregir el SMTP o el receptor).
        Conserva el número de intentos; el despachador la envía en su siguiente pasada."""
        async with self._uow() as uow:
            d = await uow.alerts.requeue(delivery_id)
            if d is None:
                raise ConflictError("la entrega no existe o no está fallida")
            await uow.audit.record("alerts.delivery_retried", actor_id=actor.user_id, entity_type="alert_delivery",
                                   entity_id=str(delivery_id), after={"incident_id": str(d.incident_id),
                                                                      "attempts": d.attempts}, ip=ip)
            await uow.commit()
        return d

    async def deliveries(self, **filters: Any) -> tuple[list[AlertDelivery], int]:
        async with self._uow() as uow:
            return await uow.alerts.deliveries(**filters)


class AlertDispatcher:
    """Planifica entregas para incidentes confirmados y las envía con reintentos.

    Fuente de verdad: la tabla de incidentes (no el bus). El evento ``incident.confirmed`` solo
    despierta al despachador para bajar la latencia; si se pierde, la pasada periódica lo recoge.
    """

    def __init__(self, service: AlertService, queue: AlertQueue, bus: MessageBus | None = None, *,
                 lookback: timedelta = timedelta(hours=24), interval: float = 15.0, batch: int = 20,
                 lease: timedelta = timedelta(minutes=2), link_base: str | None = None) -> None:
        self.service = service
        self.queue = queue
        self.bus = bus
        self.lookback = lookback
        self.interval = interval
        self.batch = batch
        self.lease = lease
        self.link_base = link_base
        self._wake = asyncio.Event()
        self.sent = 0
        self.failed = 0
        self.retried = 0

    async def run_once(self) -> int:
        channels = {c.id: c for c in await self.service.list()}
        await self.queue.plan(list(channels.values()), datetime.now(UTC) - self.lookback)
        handled = 0
        for d in await self.queue.claim_due(self.batch, self.lease):
            handled += 1
            ch = channels.get(d.channel_id)
            if ch is None:  # canal borrado entre medias: la FK en cascada eliminará la entrega
                continue
            if not ch.enabled:
                await self.queue.finish(d.id, SendResult(False, "canal deshabilitado", retryable=False),
                                        retry_in=None)
                continue
            await self._deliver(ch, d)
        return handled

    async def _deliver(self, ch: AlertChannel, d: AlertDelivery) -> None:
        msg = await self.queue.message_for(d, link_base=self.link_base)
        if msg is None:
            await self.queue.finish(d.id, SendResult(False, "el incidente ya no existe", retryable=False),
                                    retry_in=None)
            return
        sender = self.service.senders.get(ch.kind.value)
        if sender is None:
            result = SendResult(False, f"sin adaptador para {ch.kind.value}", retryable=False)
        else:
            msg = await self.service.load_evidence(msg, ch)
            try:
                result = await sender.send(ch, await self.service.secret_for(ch.id), msg)
            except Exception as exc:  # un fallo inesperado del adaptador no debe tumbar el bucle
                log.exception("fallo enviando la alerta %s", d.id)
                result = SendResult(False, f"{type(exc).__name__}: {exc}"[:500])
        attempts = d.attempts + 1
        retry = next_retry(attempts) if (not result.ok and result.retryable) else None
        await self.queue.finish(d.id, result, retry_in=retry)
        if result.ok:
            self.sent += 1
            log.info("alerta enviada", extra={"channel": ch.name, "incident_id": msg.incident_id})
        elif retry is not None:
            self.retried += 1
            log.warning("alerta fallida, reintento %d/%d en %s: %s", attempts, MAX_ATTEMPTS, retry, result.detail)
        else:
            self.failed += 1
            log.error("alerta descartada tras %d intentos: %s", attempts, result.detail)

    def wake(self) -> None:
        """Adelanta la siguiente pasada (p. ej. tras un reintento manual)."""
        self._wake.set()

    async def _listen(self) -> None:
        if self.bus is None:
            return
        while True:
            try:
                async for _ in self.bus.subscribe(["incident.confirmed.v1"], group="alerts"):
                    await asyncio.sleep(0.5)  # deja que la transacción del incidente sea visible
                    self._wake.set()
            except Exception as exc:
                log.warning("escucha de incidentes para alertas interrumpida (%s); reintento en 5s", exc)
                await asyncio.sleep(5)

    async def run_forever(self) -> None:
        listener = asyncio.create_task(self._listen())
        try:
            while True:
                self._wake.clear()  # antes de la pasada: un aviso durante ella provoca otra inmediata
                try:
                    n = await self.run_once()
                except Exception:
                    log.exception("despachador de alertas falló")
                    n = 0
                if n >= self.batch:
                    continue
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.interval)
        finally:
            listener.cancel()
