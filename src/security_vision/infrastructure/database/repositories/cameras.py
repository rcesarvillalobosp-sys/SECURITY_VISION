"""Adaptador SQL del repositorio de cámaras."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from security_vision.core.domain.cameras import Camera, SourceType
from security_vision.core.interfaces.cameras import CameraRepository

from ..models import CameraRow, CameraStatusEventRow

_FIELDS = ("name", "site_id", "source_uri", "credentials_encrypted", "width", "height", "target_fps",
           "default_profile_id",
           "analysis_fps", "enabled", "location", "mediamtx_path")


def _to_domain(r: CameraRow) -> Camera:
    return Camera(id=r.id, name=r.name, source_type=SourceType(r.source_type), source_uri=r.source_uri,
                  analysis_fps=r.analysis_fps, enabled=r.enabled, site_id=r.site_id, width=r.width,
                  height=r.height, target_fps=r.target_fps, location=dict(r.location or {}),
                  mediamtx_path=r.mediamtx_path, credentials_encrypted=r.credentials_encrypted,
                  default_profile_id=r.default_profile_id,
                  last_status=r.last_status, last_status_at=r.last_status_at, last_error=r.last_error,
                  created_at=r.created_at, updated_at=r.updated_at)


class SqlCameraRepository(CameraRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list(self, *, enabled_only: bool = False) -> list[Camera]:
        q = select(CameraRow).order_by(CameraRow.name)
        if enabled_only:
            q = q.where(CameraRow.enabled.is_(True))
        return [_to_domain(r) for r in await self.s.scalars(q)]

    async def get(self, camera_id: UUID) -> Camera | None:
        row = await self.s.get(CameraRow, camera_id)
        return _to_domain(row) if row else None

    async def add(self, camera: Camera) -> None:
        self.s.add(CameraRow(id=camera.id, source_type=camera.source_type.value,
                             **{f: getattr(camera, f) for f in _FIELDS}))
        await self.s.flush()

    async def update(self, camera: Camera) -> None:
        await self.s.execute(update(CameraRow).where(CameraRow.id == camera.id).values(
            source_type=camera.source_type.value, **{f: getattr(camera, f) for f in _FIELDS}))

    async def delete(self, camera_id: UUID) -> None:
        await self.s.execute(delete(CameraRow).where(CameraRow.id == camera_id))

    async def name_exists(self, name: str, site_id: UUID | None, exclude: UUID | None = None) -> bool:
        q = select(CameraRow.id).where(CameraRow.name == name, CameraRow.site_id.is_not_distinct_from(site_id))
        if exclude:
            q = q.where(CameraRow.id != exclude)
        return (await self.s.scalar(q.limit(1))) is not None

    async def record_status(self, camera_id: UUID, status: str, detail: str | None, at: datetime) -> None:
        detail = detail[:500] if detail else None
        res = await self.s.execute(update(CameraRow).where(CameraRow.id == camera_id).values(
            last_status=status, last_status_at=at, last_error=detail))
        if res.rowcount:
            self.s.add(CameraStatusEventRow(camera_id=camera_id, status=status, detail=detail, at=at))
            await self.s.flush()
