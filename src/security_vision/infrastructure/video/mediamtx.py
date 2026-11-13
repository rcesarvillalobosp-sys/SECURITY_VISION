"""Adaptador de MediaMTX mediante su API de control (v3).

Cada cámara tiene una ruta ``cam-<id>``:
- RTSP: MediaMTX hace de proxy de la cámara (una sola conexión a la cámara, N lectores).
- USB: ruta de publicación; el worker publica el vídeo de la cámara local.
La configuración se aplica en memoria por API; el worker la re-sincroniza al arrancar.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from security_vision.core.interfaces.cameras import MediaServer


class MediaMtxError(RuntimeError):
    pass


def path_name(camera_id: str) -> str:
    return f"cam-{camera_id.replace('-', '')[:20]}"


class MediaMtxServer(MediaServer):
    def __init__(self, api_url: str, rtsp_url: str, webrtc_url: str, api_user: str | None = None,
                 api_password: str | None = None, timeout: float = 5.0, read_user: str | None = None,
                 read_password: str | None = None) -> None:
        self._read = (read_user, read_password)
        auth = (api_user, api_password or "") if api_user else None
        self._http = httpx.AsyncClient(base_url=api_url.rstrip("/"), auth=auth, timeout=timeout)
        self._rtsp = rtsp_url.rstrip("/")
        self._webrtc = webrtc_url.rstrip("/")

    async def _call(self, method: str, url: str, json: dict | None = None) -> httpx.Response:
        try:
            return await self._http.request(method, url, json=json)
        except httpx.HTTPError as exc:
            raise MediaMtxError(f"MediaMTX no accesible: {type(exc).__name__}") from exc

    async def ensure_path(self, name: str, source_url: str | None) -> None:
        conf = {"source": source_url or "publisher"}
        if source_url:
            conf |= {"sourceOnDemand": False, "rtspTransport": "tcp"}
        q = quote(name, safe="")
        r = await self._call("POST", f"/v3/config/paths/add/{q}", conf)
        if r.status_code == 400 and "already exists" in r.text:
            r = await self._call("PATCH", f"/v3/config/paths/patch/{q}", conf)
        if r.status_code >= 300:
            # Nunca se incluye la configuración en el error: contiene credenciales.
            raise MediaMtxError(f"MediaMTX rechazó la ruta {name}: HTTP {r.status_code}")

    async def remove_path(self, name: str) -> None:
        r = await self._call("DELETE", f"/v3/config/paths/delete/{quote(name, safe='')}")
        if r.status_code not in (200, 404):
            raise MediaMtxError(f"MediaMTX no pudo borrar {name}: HTTP {r.status_code}")

    async def list_paths(self) -> list[dict]:
        r = await self._call("GET", "/v3/paths/list")
        r.raise_for_status()
        return r.json().get("items", [])

    def read_url(self, name: str) -> str:
        return f"{self._rtsp}/{name}"

    def read_credentials(self) -> tuple[str | None, str | None]:
        return self._read

    def webrtc_url(self, name: str) -> str:
        return f"{self._webrtc}/{name}/whep"

    async def close(self) -> None:
        await self._http.aclose()
