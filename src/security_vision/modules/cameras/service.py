"""Casos de uso de cámaras: alta/edición/baja, credenciales cifradas, prueba de conexión y snapshot."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from security_vision.core.domain.cameras import Camera, SourceType, validate_source
from security_vision.core.domain.errors import ConflictError, NotFoundError, ValidationError
from security_vision.core.domain.identity import Principal
from security_vision.core.domain.ids import uuid7
from security_vision.core.events.catalog import CameraConfigChanged
from security_vision.core.interfaces.cameras import MediaServer, ProbeResult, VideoProbe
from security_vision.core.interfaces.infrastructure import MessageBus, ObjectStorage, SecretCipher
from security_vision.core.interfaces.repositories import UnitOfWork
from security_vision.core.interfaces.video import VideoSourceConfig

log = logging.getLogger(__name__)
SNAPSHOT_KEY = "snapshots/{camera_id}.jpg"


@dataclass(frozen=True)
class CameraPolicy:
    video_provider: str = "pyav"
    allow_test_sources: bool = False
    files_root: str | None = None
    probe_timeout: float = 15.0
    snapshot_max_age: timedelta = timedelta(seconds=30)


@dataclass
class CameraInput:
    name: str
    source_type: SourceType
    source_uri: str
    username: str | None = None
    password: SecretStr | None = None
    analysis_fps: float = 2.0
    enabled: bool = True
    site_id: UUID | None = None
    width: int | None = None
    height: int | None = None
    target_fps: float | None = None
    location: dict[str, str] = field(default_factory=dict)
    default_profile_id: UUID | None = None


def provider_for(camera: Camera, policy: CameraPolicy) -> str:
    return "testpattern" if camera.source_type is SourceType.TEST else policy.video_provider


def _aad(camera_id: UUID) -> bytes:
    return b"camera-credentials:" + camera_id.bytes


def decrypt_credentials(camera: Camera, cipher: SecretCipher) -> tuple[str | None, str | None]:
    if not camera.credentials_encrypted:
        return None, None
    data = json.loads(cipher.decrypt(camera.credentials_encrypted, _aad(camera.id)))
    return data.get("username"), data.get("password")


def source_config(camera: Camera, cipher: SecretCipher, policy: CameraPolicy,
                  media: MediaServer | None = None, *, via_media: bool = False) -> VideoSourceConfig:
    """Configuración de captura. ``via_media``: leer la cámara RTSP a través de MediaMTX."""
    user, pwd = decrypt_credentials(camera, cipher)
    uri = camera.source_uri
    if camera.source_type is SourceType.FILE:
        assert policy.files_root, "SV_VIDEO_FILES_DIR no configurado"
        uri = f"{policy.files_root.rstrip('/')}/{uri}"
    options: dict[str, Any] = {}
    if camera.source_type in (SourceType.FILE,):
        options |= {"loop": True, "realtime": True}  # un archivo se comporta como cámara en vivo
    if via_media and media and camera.mediamtx_path and camera.source_type is SourceType.RTSP:
        ru, rp = media.read_credentials()
        return VideoSourceConfig(uri=media.read_url(camera.mediamtx_path), username=ru,
                                 password=SecretStr(rp) if rp else None, width=camera.width,
                                 height=camera.height, fps=camera.target_fps, options=options)
    return VideoSourceConfig(uri=uri, username=user, password=SecretStr(pwd) if pwd else None,
                             width=camera.width, height=camera.height, fps=camera.target_fps, options=options)


def media_source_url(camera: Camera, cipher: SecretCipher) -> str | None:
    """URL de origen para MediaMTX (con credenciales; solo viaja a MediaMTX, nunca a logs/API)."""
    if camera.source_type is not SourceType.RTSP:
        return None
    from urllib.parse import quote, urlsplit, urlunsplit

    user, pwd = decrypt_credentials(camera, cipher)
    if not user:
        return camera.source_uri
    p = urlsplit(camera.source_uri)
    host = f"{p.hostname}:{p.port}" if p.port else (p.hostname or "")
    cred = quote(user, safe="") + (":" + quote(pwd, safe="") if pwd else "")
    return urlunsplit((p.scheme, f"{cred}@{host}", p.path, p.query, p.fragment))


class CameraService:
    def __init__(self, uow: Callable[[], UnitOfWork], cipher: SecretCipher, probe: VideoProbe,
                 storage: ObjectStorage, policy: CameraPolicy, bus: MessageBus | None = None,
                 media: MediaServer | None = None, media_path_for: Callable[[str], str] | None = None) -> None:
        self._uow = uow
        self._cipher = cipher
        self._probe = probe
        self._storage = storage
        self._policy = policy
        self._bus = bus
        self._media = media
        self._media_path_for = media_path_for

    # ---------------------------------------------------------------- consultas
    async def list(self) -> list[Camera]:
        async with self._uow() as uow:
            return await uow.cameras.list()

    async def get(self, camera_id: UUID) -> Camera:
        async with self._uow() as uow:
            cam = await uow.cameras.get(camera_id)
        if cam is None:
            raise NotFoundError("cámara no encontrada")
        return cam

    # ---------------------------------------------------------------- escritura
    def _validate(self, data: CameraInput) -> str:
        if not data.name.strip():
            raise ValidationError("nombre obligatorio")
        if not 0 < data.analysis_fps <= 60:
            raise ValidationError("analysis_fps debe estar en (0, 60]")
        if data.target_fps is not None and data.analysis_fps > data.target_fps:
            raise ValidationError("analysis_fps no puede superar target_fps")
        if (data.width is None) != (data.height is None):
            raise ValidationError("indica ancho y alto juntos")
        if data.password and not data.username:
            raise ValidationError("contraseña sin usuario")
        return validate_source(data.source_type, data.source_uri, allow_test=self._policy.allow_test_sources,
                               files_root=self._policy.files_root)

    def _encrypt(self, camera_id: UUID, username: str | None, password: SecretStr | None) -> bytes | None:
        if not username:
            return None
        payload = json.dumps({"username": username, "password": password.get_secret_value() if password else None})
        return self._cipher.encrypt(payload, _aad(camera_id))

    @staticmethod
    def _audit_view(c: Camera) -> dict[str, Any]:
        return {"name": c.name, "source_type": c.source_type.value, "source_uri": c.source_uri,
                "has_credentials": c.has_credentials, "enabled": c.enabled, "analysis_fps": c.analysis_fps,
                "default_profile_id": str(c.default_profile_id) if c.default_profile_id else None}

    async def create(self, data: CameraInput, *, actor: Principal, ip: str | None = None) -> Camera:
        uri = self._validate(data)
        cid = uuid7()
        cam = Camera(id=cid, name=data.name.strip(), source_type=data.source_type, source_uri=uri,
                     analysis_fps=data.analysis_fps, enabled=data.enabled, site_id=data.site_id, width=data.width,
                     height=data.height, target_fps=data.target_fps, location=data.location,
                     credentials_encrypted=self._encrypt(cid, data.username, data.password),
                     default_profile_id=data.default_profile_id)
        if self._media and self._media_path_for:
            cam.mediamtx_path = self._media_path_for(str(cid))
        async with self._uow() as uow:
            if cam.default_profile_id and await uow.rules.get_profile(cam.default_profile_id) is None:
                raise ValidationError("perfil de seguridad inexistente")
            if await uow.cameras.name_exists(cam.name, cam.site_id):
                raise ConflictError("ya existe una cámara con ese nombre en el sitio")
            await uow.cameras.add(cam)
            await uow.audit.record("camera.created", actor_id=actor.user_id, entity_type="camera",
                                   entity_id=str(cid), after=self._audit_view(cam), ip=ip)
            await uow.commit()
        await self._sync_media(cam)
        await self._notify(cid, "created")
        return cam

    async def update(self, camera_id: UUID, changes: dict[str, Any], *, actor: Principal,
                     ip: str | None = None) -> Camera:
        async with self._uow() as uow:
            current = await uow.cameras.get(camera_id)
            if current is None:
                raise NotFoundError("cámara no encontrada")
            user, pwd = decrypt_credentials(current, self._cipher)
            merged = CameraInput(
                name=changes.get("name", current.name), source_type=SourceType(changes.get("source_type",
                                                                                         current.source_type)),
                source_uri=changes.get("source_uri", current.source_uri),
                username=changes.get("username", user),
                password=changes["password"] if "password" in changes else (SecretStr(pwd) if pwd else None),
                analysis_fps=changes.get("analysis_fps", current.analysis_fps),
                enabled=changes.get("enabled", current.enabled), site_id=changes.get("site_id", current.site_id),
                width=changes.get("width", current.width), height=changes.get("height", current.height),
                target_fps=changes.get("target_fps", current.target_fps),
                location=changes.get("location", current.location),
                default_profile_id=changes.get("default_profile_id", current.default_profile_id))
            uri = self._validate(merged)
            if merged.default_profile_id and await uow.rules.get_profile(merged.default_profile_id) is None:
                raise ValidationError("perfil de seguridad inexistente")
            if merged.name != current.name and await uow.cameras.name_exists(merged.name, merged.site_id,
                                                                                exclude=camera_id):
                raise ConflictError("ya existe una cámara con ese nombre en el sitio")
            updated = replace(current, name=merged.name.strip(), source_type=merged.source_type, source_uri=uri,
                              analysis_fps=merged.analysis_fps, enabled=merged.enabled, site_id=merged.site_id,
                              width=merged.width, height=merged.height, target_fps=merged.target_fps,
                              location=merged.location, default_profile_id=merged.default_profile_id,
                              credentials_encrypted=self._encrypt(camera_id, merged.username, merged.password))
            await uow.cameras.update(updated)
            await uow.audit.record("camera.updated", actor_id=actor.user_id, entity_type="camera",
                                   entity_id=str(camera_id), before=self._audit_view(current),
                                   after=self._audit_view(updated) | {"credentials_changed": "username" in changes
                                                                      or "password" in changes}, ip=ip)
            await uow.commit()
        await self._sync_media(updated)
        await self._notify(camera_id, "updated")
        return updated

    async def delete(self, camera_id: UUID, *, actor: Principal, ip: str | None = None) -> None:
        async with self._uow() as uow:
            current = await uow.cameras.get(camera_id)
            if current is None:
                raise NotFoundError("cámara no encontrada")
            await uow.cameras.delete(camera_id)
            await uow.audit.record("camera.deleted", actor_id=actor.user_id, entity_type="camera",
                                   entity_id=str(camera_id), before=self._audit_view(current), ip=ip)
            await uow.commit()
        if self._media and current.mediamtx_path:
            try:
                await self._media.remove_path(current.mediamtx_path)
            except Exception:
                log.warning("no se pudo borrar la ruta de MediaMTX %s", current.mediamtx_path)
        self._storage.delete(SNAPSHOT_KEY.format(camera_id=camera_id))
        await self._notify(camera_id, "deleted")

    # ---------------------------------------------------------------- diagnóstico
    async def test_connection(self, camera_id: UUID, *, with_snapshot: bool = False) -> ProbeResult:
        cam = await self.get(camera_id)
        cfg = source_config(cam, self._cipher, self._policy)
        return await self._probe.probe(provider_for(cam, self._policy), cfg, self._policy.probe_timeout,
                                       with_snapshot=with_snapshot)

    def latest_snapshot(self, camera_id: UUID) -> tuple[bytes, datetime] | None:
        """Último snapshot publicado por el worker (no abre otra conexión a la cámara)."""
        key = SNAPSHOT_KEY.format(camera_id=camera_id)
        try:
            data = self._storage.get(key)
            _size, mtime, _ct = self._storage.stat(key)
        except FileNotFoundError:
            return None
        if datetime.now(UTC) - mtime > self._policy.snapshot_max_age:
            return None
        return data, mtime

    async def _sync_media(self, cam: Camera) -> None:
        if not (self._media and cam.mediamtx_path):
            return
        try:
            if not cam.enabled:
                await self._media.remove_path(cam.mediamtx_path)
            else:
                await self._media.ensure_path(cam.mediamtx_path, media_source_url(cam, self._cipher))
        except Exception as exc:
            # MediaMTX es opcional: la cámara queda guardada y el worker re-sincroniza al arrancar.
            log.warning("MediaMTX no sincronizado para %s: %s", cam.id, exc)

    async def _notify(self, camera_id: UUID, action: str) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish(CameraConfigChanged(camera_id=camera_id, action=action))
        except Exception as exc:
            log.warning("no se pudo notificar el cambio de cámara %s: %s", camera_id, exc)
