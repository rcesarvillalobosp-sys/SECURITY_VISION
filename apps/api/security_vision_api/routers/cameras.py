"""Gestión de cámaras. Las credenciales nunca se devuelven: solo ``has_credentials``."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from security_vision.core.domain.cameras import Camera, SourceType
from security_vision.core.domain.identity import Permission, Principal
from security_vision.modules.cameras.service import CameraInput

from ..container import Container
from ..deps import client_ip, get_container, require

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])
C = Annotated[Container, Depends(get_container)]
Reader = Annotated[Principal, Depends(require(Permission.CAMERAS_READ))]
Writer = Annotated[Principal, Depends(require(Permission.CAMERAS_WRITE))]


class CameraIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    source_uri: str = Field(min_length=1, max_length=1000)
    username: str | None = Field(default=None, max_length=200)
    password: SecretStr | None = Field(default=None, max_length=500)
    analysis_fps: float = Field(default=2.0, gt=0, le=60)
    enabled: bool = True
    site_id: UUID | None = None
    width: int | None = Field(default=None, ge=16, le=8192)
    height: int | None = Field(default=None, ge=16, le=8192)
    target_fps: float | None = Field(default=None, gt=0, le=120)
    location: dict[str, str] = Field(default_factory=dict, max_length=20)
    default_profile_id: UUID | None = None


class CameraPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: SourceType | None = None
    source_uri: str | None = Field(default=None, min_length=1, max_length=1000)
    username: str | None = Field(default=None, max_length=200)
    password: SecretStr | None = Field(default=None, max_length=500)
    analysis_fps: float | None = Field(default=None, gt=0, le=60)
    enabled: bool | None = None
    site_id: UUID | None = None
    width: int | None = Field(default=None, ge=16, le=8192)
    height: int | None = Field(default=None, ge=16, le=8192)
    target_fps: float | None = Field(default=None, gt=0, le=120)
    location: dict[str, str] | None = None
    default_profile_id: UUID | None = None


class CameraOut(BaseModel):
    id: UUID
    name: str
    source_type: SourceType
    source_uri: str
    has_credentials: bool
    analysis_fps: float
    enabled: bool
    site_id: UUID | None
    width: int | None
    height: int | None
    target_fps: float | None
    location: dict[str, str]
    default_profile_id: UUID | None
    status: str | None
    status_at: datetime | None
    last_error: str | None
    webrtc_url: str | None


class ProbeOut(BaseModel):
    ok: bool
    elapsed_ms: float
    error: str | None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    nominal_fps: float | None = None


class DiscoveredOut(BaseModel):
    kind: str
    name: str
    address: str
    details: dict[str, str]


def _out(c: Camera, container: Container) -> CameraOut:
    webrtc = container.media.webrtc_url(c.mediamtx_path) if container.media and c.mediamtx_path else None
    return CameraOut(id=c.id, name=c.name, source_type=c.source_type, source_uri=c.source_uri,
                     has_credentials=c.has_credentials, analysis_fps=c.analysis_fps, enabled=c.enabled,
                     site_id=c.site_id, width=c.width, height=c.height, target_fps=c.target_fps,
                     location=c.location, default_profile_id=c.default_profile_id, status=c.last_status,
                     status_at=c.last_status_at,
                     last_error=c.last_error, webrtc_url=webrtc)


@router.get("", response_model=list[CameraOut])
async def list_cameras(container: C, _: Reader) -> list[CameraOut]:
    return [_out(c, container) for c in await container.cameras.list()]


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(body: CameraIn, request: Request, container: C, principal: Writer) -> CameraOut:
    cam = await container.cameras.create(CameraInput(**body.model_dump()), actor=principal, ip=client_ip(request))
    return _out(cam, container)


@router.get("/discover", response_model=list[DiscoveredOut])
async def discover(container: C, _: Writer, kind: str = "onvif") -> list[DiscoveredOut]:
    """ONVIF (WS-Discovery en la red local del servidor) o USB (dispositivos del propio servidor)."""
    if kind == "onvif":
        from security_vision.infrastructure.video.onvif_discovery import discover_onvif

        found = await asyncio.to_thread(discover_onvif, 2.0)
        return [DiscoveredOut(kind=d.kind, name=d.name, address=d.address, details=d.details) for d in found]
    if kind == "usb":
        from security_vision.plugins.video_sources.pyav_source import list_usb_cameras

        names = await asyncio.to_thread(list_usb_cameras)
        return [DiscoveredOut(kind="usb", name=n, address=f"usb:{n}", details={}) for n in names]
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "kind debe ser onvif o usb")


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: UUID, container: C, _: Reader) -> CameraOut:
    return _out(await container.cameras.get(camera_id), container)


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: UUID, body: CameraPatch, request: Request, container: C,
                        principal: Writer) -> CameraOut:
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    cam = await container.cameras.update(camera_id, changes, actor=principal, ip=client_ip(request))
    return _out(cam, container)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: UUID, request: Request, container: C, principal: Writer) -> Response:
    await container.cameras.delete(camera_id, actor=principal, ip=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/test", response_model=ProbeOut)
async def test_camera(camera_id: UUID, container: C, _: Writer) -> ProbeOut:
    """Prueba de conectividad directa. En USB puede fallar si el worker ya tiene el dispositivo abierto."""
    r = await container.cameras.test_connection(camera_id)
    m = r.metadata
    return ProbeOut(ok=r.ok, elapsed_ms=round(r.elapsed_ms, 1), error=r.error, codec=m.codec if m else None,
                    width=m.width if m else None, height=m.height if m else None,
                    nominal_fps=m.nominal_fps if m else None)


@router.get("/{camera_id}/snapshot")
async def snapshot(camera_id: UUID, container: C, _: Reader) -> Response:
    await container.cameras.get(camera_id)  # 404 si no existe
    snap = container.cameras.latest_snapshot(camera_id)
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sin snapshot reciente (¿worker detenido o cámara caída?)")
    data, at = snap
    return Response(data, media_type="image/jpeg", headers={"Last-Modified": at.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                                                            "Cache-Control": "no-store"})
