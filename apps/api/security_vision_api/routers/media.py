"""Autorización de MediaMTX (``authMethod: http``): MediaMTX consulta a la API antes de cada acción.

- ``publish``: solo el usuario de publicación (worker que reemite cámaras USB/archivo).
- ``read``/``playback``:
  - el usuario de publicación (el worker leyendo cámaras);
  - o un **navegador con el token de acceso de la web** (``Authorization: Bearer``), sesión activa, permiso
    ``cameras:read`` y una ruta que corresponda a una cámara existente. Cada concesión se audita: ver vídeo
    de personas es tratamiento de datos personales.
- ``api``/``metrics``/``pprof``: solo el usuario de API de MediaMTX.

El endpoint exige una clave compartida (``SV_MEDIAMTX_AUTH_KEY``) en la URL que MediaMTX tiene configurada;
sin ella responde 404. Respuesta 2xx = permitido; cualquier otra = denegado.
"""

from __future__ import annotations

import hmac
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict

from security_vision.core.domain.errors import AuthenticationError
from security_vision.core.domain.identity import Permission

from ..container import Container
from ..deps import get_container

router = APIRouter(prefix="/api/v1/media", tags=["media"], include_in_schema=False)
C = Annotated[Container, Depends(get_container)]
log = logging.getLogger("security_vision.api.media")
_PATHS_TTL = 10.0


class MediaAuthIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user: str = ""
    password: str = ""
    token: str = ""
    ip: str = ""
    action: str = ""
    path: str = ""
    protocol: str = ""
    id: str | None = None
    query: str = ""


def _eq(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(str(a).encode(), str(b).encode())


async def _camera_paths(container: Container) -> set[str]:
    """Rutas de MediaMTX de las cámaras existentes (caché breve: MediaMTX consulta en cada conexión)."""
    cached = getattr(container, "_media_paths_cache", None)
    now = time.monotonic()
    if cached and now - cached[0] < _PATHS_TTL:
        return cached[1]
    paths = {c.mediamtx_path for c in await container.cameras.list() if c.mediamtx_path}
    container._media_paths_cache = (now, paths)  # type: ignore[attr-defined]
    return paths


@router.post("/auth")
async def media_auth(body: MediaAuthIn, container: C, key: Annotated[str, Query(max_length=200)] = "") -> Response:
    s = container.settings
    expected = s.mediamtx_auth_key.get_secret_value() if s.mediamtx_auth_key else None
    if not expected:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if not _eq(key, expected):
        log.warning("autorización de MediaMTX con clave inválida", extra={"ip": body.ip})
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    deny = Response(status_code=status.HTTP_401_UNAUTHORIZED)
    pub_user = s.mediamtx_publish_user
    pub_pwd = s.mediamtx_publish_password.get_secret_value() if s.mediamtx_publish_password else None
    api_pwd = s.mediamtx_api_password.get_secret_value() if s.mediamtx_api_password else None
    is_publisher = _eq(body.user, pub_user) and _eq(body.password, pub_pwd)

    if body.action == "publish":
        return Response(status_code=200) if is_publisher else deny
    if body.action in ("api", "metrics", "pprof"):
        ok = _eq(body.user, s.mediamtx_api_user) and _eq(body.password, api_pwd)
        return Response(status_code=200) if ok else deny
    if body.action not in ("read", "playback"):
        return deny
    if is_publisher:
        return Response(status_code=200)
    if not body.token:
        return deny  # MediaMTX pide credenciales: el navegador debe enviar su token
    try:
        principal = await container.auth.authenticate(body.token)
    except AuthenticationError:
        return deny
    if not principal.can(Permission.CAMERAS_READ):
        return deny
    if body.path not in await _camera_paths(container):
        return deny
    await container.audit_media(principal.user_id, body.path, body.protocol, body.ip)
    return Response(status_code=200)
