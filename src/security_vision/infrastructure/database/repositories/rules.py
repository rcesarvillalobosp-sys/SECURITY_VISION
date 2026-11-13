"""Adaptador SQL de perfiles de seguridad y zonas."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from security_vision.core.domain.compliance import CameraRules, RuleThresholds, SecurityProfile, ZoneRule
from security_vision.core.interfaces.repositories import RulesRepository

from ..models import CameraRow, SecurityProfileRow, ZoneRow


def _profile(r: SecurityProfileRow) -> SecurityProfile:
    return SecurityProfile(id=str(r.id), name=r.name, required_ppe=tuple(r.required_ppe or ()),
                           thresholds=RuleThresholds.from_dict(r.thresholds), version=r.version)


class SqlRulesRepository(RulesRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list_profiles(self) -> list[SecurityProfile]:
        return [_profile(r) for r in await self.s.scalars(select(SecurityProfileRow).order_by(SecurityProfileRow.name))]

    async def get_profile(self, profile_id: UUID) -> SecurityProfile | None:
        r = await self.s.get(SecurityProfileRow, profile_id)
        return _profile(r) if r else None

    async def save_profile(self, profile: SecurityProfile, *, new: bool) -> None:
        values = {"name": profile.name, "required_ppe": list(profile.required_ppe),
                  "thresholds": profile.thresholds.to_dict(), "version": profile.version}
        if new:
            self.s.add(SecurityProfileRow(id=UUID(profile.id), description="", **values))
        else:
            await self.s.execute(update(SecurityProfileRow).where(SecurityProfileRow.id == UUID(profile.id))
                                 .values(**values))
        await self.s.flush()

    async def delete_profile(self, profile_id: UUID) -> None:
        await self.s.execute(delete(SecurityProfileRow).where(SecurityProfileRow.id == profile_id))

    async def profile_in_use(self, profile_id: UUID) -> bool:
        n = await self.s.scalar(select(func.count()).select_from(CameraRow)
                                .where(CameraRow.default_profile_id == profile_id))
        z = await self.s.scalar(select(func.count()).select_from(ZoneRow).where(ZoneRow.profile_id == profile_id))
        return bool((n or 0) + (z or 0))

    async def _zone(self, r: ZoneRow) -> ZoneRule:
        prof = await self.get_profile(r.profile_id) if r.profile_id else None
        return ZoneRule(zone_id=str(r.id), name=r.name, polygon=tuple(tuple(p) for p in r.polygon),  # type: ignore[misc]
                        profile=prof, kind=r.kind)

    async def list_zones(self, camera_id: UUID) -> list[ZoneRule]:
        rows = await self.s.scalars(select(ZoneRow).where(ZoneRow.camera_id == camera_id).order_by(ZoneRow.name))
        return [await self._zone(r) for r in rows]

    async def get_zone(self, zone_id: UUID) -> tuple[UUID, ZoneRule] | None:
        r = await self.s.get(ZoneRow, zone_id)
        return (r.camera_id, await self._zone(r)) if r else None

    async def save_zone(self, camera_id: UUID, zone: ZoneRule, *, enabled: bool, new: bool) -> None:
        values = {"name": zone.name, "kind": zone.kind, "polygon": [list(p) for p in zone.polygon],
                  "profile_id": UUID(zone.profile.id) if zone.profile else None, "enabled": enabled}
        if new:
            self.s.add(ZoneRow(id=UUID(zone.zone_id), camera_id=camera_id, **values))
        else:
            await self.s.execute(update(ZoneRow).where(ZoneRow.id == UUID(zone.zone_id)).values(**values))
        await self.s.flush()

    async def delete_zone(self, zone_id: UUID) -> None:
        await self.s.execute(delete(ZoneRow).where(ZoneRow.id == zone_id))

    async def camera_rules(self, camera_id: UUID) -> CameraRules:
        cam = await self.s.get(CameraRow, camera_id)
        default = await self.get_profile(cam.default_profile_id) if cam and cam.default_profile_id else None
        rows = await self.s.scalars(select(ZoneRow).where(ZoneRow.camera_id == camera_id,
                                                          ZoneRow.enabled.is_(True)).order_by(ZoneRow.name))
        return CameraRules(camera_id=str(camera_id), default_profile=default,
                           zones=tuple([await self._zone(r) for r in rows]))
