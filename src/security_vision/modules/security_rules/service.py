"""Casos de uso de configuración de reglas: perfiles de seguridad y zonas por cámara."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from security_vision.core.domain.compliance import RuleThresholds, SecurityProfile, ZoneRule
from security_vision.core.domain.errors import ConflictError, NotFoundError, ValidationError
from security_vision.core.domain.identity import Principal
from security_vision.core.domain.ids import uuid7
from security_vision.core.events.catalog import RulesChanged
from security_vision.core.interfaces.infrastructure import MessageBus
from security_vision.core.interfaces.repositories import UnitOfWork

log = logging.getLogger(__name__)
DEFAULT_PROFILE_NAME = "EPP básico (casco + chaleco)"


class RulesService:
    def __init__(self, uow: Callable[[], UnitOfWork], bus: MessageBus | None = None) -> None:
        self._uow = uow
        self._bus = bus

    # ---------------------------------------------------------------- perfiles
    async def list_profiles(self) -> list[SecurityProfile]:
        async with self._uow() as uow:
            return await uow.rules.list_profiles()

    async def get_profile(self, profile_id: UUID) -> SecurityProfile:
        async with self._uow() as uow:
            p = await uow.rules.get_profile(profile_id)
        if p is None:
            raise NotFoundError("perfil no encontrado")
        return p

    async def create_profile(self, name: str, required_ppe: list[str], thresholds: dict[str, Any] | None,
                             *, actor: Principal, ip: str | None = None) -> SecurityProfile:
        profile = SecurityProfile(id=str(uuid7()), name=name.strip(), required_ppe=tuple(dict.fromkeys(required_ppe)),
                                  thresholds=RuleThresholds.from_dict(thresholds))
        if not profile.name:
            raise ValidationError("nombre obligatorio")
        async with self._uow() as uow:
            if any(p.name == profile.name for p in await uow.rules.list_profiles()):
                raise ConflictError("ya existe un perfil con ese nombre")
            await uow.rules.save_profile(profile, new=True)
            await uow.audit.record("rules.profile_created", actor_id=actor.user_id, entity_type="security_profile",
                                   entity_id=profile.id, after=_view(profile), ip=ip)
            await uow.commit()
        await self._notify(None)
        return profile

    async def update_profile(self, profile_id: UUID, changes: dict[str, Any], *, actor: Principal,
                             ip: str | None = None) -> SecurityProfile:
        async with self._uow() as uow:
            cur = await uow.rules.get_profile(profile_id)
            if cur is None:
                raise NotFoundError("perfil no encontrado")
            th = cur.thresholds.to_dict() | (changes.get("thresholds") or {})
            new = SecurityProfile(id=cur.id, name=changes.get("name", cur.name).strip(),
                                  required_ppe=tuple(dict.fromkeys(changes.get("required_ppe", cur.required_ppe))),
                                  thresholds=RuleThresholds.from_dict(th), version=cur.version + 1)
            await uow.rules.save_profile(new, new=False)
            await uow.audit.record("rules.profile_updated", actor_id=actor.user_id, entity_type="security_profile",
                                   entity_id=cur.id, before=_view(cur), after=_view(new), ip=ip)
            await uow.commit()
        await self._notify(None)
        return new

    async def delete_profile(self, profile_id: UUID, *, actor: Principal, ip: str | None = None) -> None:
        async with self._uow() as uow:
            cur = await uow.rules.get_profile(profile_id)
            if cur is None:
                raise NotFoundError("perfil no encontrado")
            if await uow.rules.profile_in_use(profile_id):
                raise ConflictError("el perfil está asignado a cámaras o zonas")
            await uow.rules.delete_profile(profile_id)
            await uow.audit.record("rules.profile_deleted", actor_id=actor.user_id, entity_type="security_profile",
                                   entity_id=cur.id, before=_view(cur), ip=ip)
            await uow.commit()

    # ---------------------------------------------------------------- zonas
    async def list_zones(self, camera_id: UUID) -> list[ZoneRule]:
        async with self._uow() as uow:
            if await uow.cameras.get(camera_id) is None:
                raise NotFoundError("cámara no encontrada")
            return await uow.rules.list_zones(camera_id)

    async def create_zone(self, camera_id: UUID, name: str, polygon: list[list[float]], profile_id: UUID | None,
                          kind: str, *, actor: Principal, ip: str | None = None) -> ZoneRule:
        async with self._uow() as uow:
            if await uow.cameras.get(camera_id) is None:
                raise NotFoundError("cámara no encontrada")
            profile = await self._profile_or_none(uow, profile_id)
            zone = ZoneRule(zone_id=str(uuid7()), name=name.strip(), polygon=_poly(polygon), profile=profile,
                            kind=kind)
            if any(z.name == zone.name for z in await uow.rules.list_zones(camera_id)):
                raise ConflictError("ya existe una zona con ese nombre en la cámara")
            await uow.rules.save_zone(camera_id, zone, enabled=True, new=True)
            await uow.audit.record("rules.zone_created", actor_id=actor.user_id, entity_type="zone",
                                   entity_id=zone.zone_id, after={"camera_id": str(camera_id), "name": zone.name,
                                                                  "profile_id": profile_id and str(profile_id)}, ip=ip)
            await uow.commit()
        await self._notify(camera_id)
        return zone

    async def update_zone(self, zone_id: UUID, changes: dict[str, Any], *, actor: Principal,
                          ip: str | None = None) -> ZoneRule:
        async with self._uow() as uow:
            found = await uow.rules.get_zone(zone_id)
            if found is None:
                raise NotFoundError("zona no encontrada")
            camera_id, cur = found
            profile = (await self._profile_or_none(uow, changes["profile_id"]) if "profile_id" in changes
                       else cur.profile)
            new = ZoneRule(zone_id=cur.zone_id, name=changes.get("name", cur.name).strip(),
                           polygon=_poly(changes["polygon"]) if "polygon" in changes else cur.polygon,
                           profile=profile, kind=changes.get("kind", cur.kind))
            await uow.rules.save_zone(camera_id, new, enabled=changes.get("enabled", True), new=False)
            await uow.audit.record("rules.zone_updated", actor_id=actor.user_id, entity_type="zone",
                                   entity_id=cur.zone_id, after={k: str(v) for k, v in changes.items()}, ip=ip)
            await uow.commit()
        await self._notify(camera_id)
        return new

    async def delete_zone(self, zone_id: UUID, *, actor: Principal, ip: str | None = None) -> None:
        async with self._uow() as uow:
            found = await uow.rules.get_zone(zone_id)
            if found is None:
                raise NotFoundError("zona no encontrada")
            await uow.rules.delete_zone(zone_id)
            await uow.audit.record("rules.zone_deleted", actor_id=actor.user_id, entity_type="zone",
                                   entity_id=str(zone_id), ip=ip)
            await uow.commit()
        await self._notify(found[0])

    # ---------------------------------------------------------------- internos
    @staticmethod
    async def _profile_or_none(uow: UnitOfWork, profile_id: UUID | None) -> SecurityProfile | None:
        if profile_id is None:
            return None
        p = await uow.rules.get_profile(profile_id)
        if p is None:
            raise ValidationError("perfil inexistente")
        return p

    async def _notify(self, camera_id: UUID | None) -> None:
        if self._bus:
            try:
                await self._bus.publish(RulesChanged(camera_id=camera_id))
            except Exception as exc:
                log.warning("no se pudo notificar el cambio de reglas: %s", exc)


def _poly(points: list[list[float]]) -> tuple[tuple[float, float], ...]:
    if not isinstance(points, list) or len(points) > 64:
        raise ValidationError("polígono inválido (máx. 64 vértices)")
    try:
        return tuple((float(x), float(y)) for x, y in points)
    except (TypeError, ValueError) as exc:
        raise ValidationError("cada vértice debe ser [x, y]") from exc


def _view(p: SecurityProfile) -> dict[str, Any]:
    return {"name": p.name, "required_ppe": list(p.required_ppe), "thresholds": p.thresholds.to_dict(),
            "version": p.version}


async def ensure_default_profile(uow_factory: Callable[[], UnitOfWork]) -> str | None:
    """Bootstrap: crea el perfil por defecto si no hay ninguno. Devuelve su nombre si lo creó."""
    async with uow_factory() as uow:
        if await uow.rules.list_profiles():
            return None
        await uow.rules.save_profile(SecurityProfile(id=str(uuid7()), name=DEFAULT_PROFILE_NAME,
                                                     required_ppe=("helmet", "safety_vest")), new=True)
        await uow.commit()
        return DEFAULT_PROFILE_NAME
