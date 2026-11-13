"""Autorización de MediaMTX por la API (authMethod: http): quién puede publicar, leer o usar su API."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from .conftest import auth, login

pytestmark = pytest.mark.anyio
KEY = "clave-compartida-de-pruebas"


@pytest.fixture
def settings(settings):
    return settings.model_copy(update={
        "allow_test_sources": True, "mediamtx_auth_key": SecretStr(KEY),
        "mediamtx_publish_user": "svpublisher", "mediamtx_publish_password": SecretStr("pub-secreto"),
        "mediamtx_api_user": "svapi", "mediamtx_api_password": SecretStr("api-secreto")})


async def _ask(client, **body):
    return (await client.post(f"/api/v1/media/auth?key={KEY}", json=body)).status_code


async def test_media_auth_rules_and_audit(client):
    token = await login(client)
    cam = (await client.post("/api/v1/cameras", headers=auth(token), json={
        "name": "C1", "source_type": "rtsp", "source_uri": "rtsp://10.0.0.5/stream"})).json()
    # Sin MediaMTX en el test la cámara no tiene ruta: se le asigna la que tendría (cam-<id>)
    from sqlalchemy import text

    from security_vision.infrastructure.video.mediamtx import path_name

    path = path_name(cam["id"])
    async with client.app.state.container.engine.begin() as conn:
        await conn.execute(text("UPDATE cameras SET mediamtx_path = :p WHERE id = :i"), {"p": path, "i": cam["id"]})

    # Clave compartida obligatoria
    assert (await client.post("/api/v1/media/auth?key=otra", json={"action": "read"})).status_code == 403
    assert (await client.post("/api/v1/media/auth", json={"action": "read"})).status_code == 403
    # Publicar: solo el usuario de publicación
    assert await _ask(client, action="publish", path=path, user="svpublisher", password="pub-secreto") == 200
    assert await _ask(client, action="publish", path=path, user="svpublisher", password="mal") == 401
    assert await _ask(client, action="publish", path=path, token=token) == 401  # un navegador no publica
    # API de MediaMTX: solo su usuario
    assert await _ask(client, action="api", user="svapi", password="api-secreto") == 200
    assert await _ask(client, action="api", user="svpublisher", password="pub-secreto") == 401
    # Leer: el worker (usuario de publicación) o un navegador con sesión y una cámara existente
    assert await _ask(client, action="read", path=path, protocol="rtsp", user="svpublisher",
                      password="pub-secreto") == 200
    assert await _ask(client, action="read", path=path, protocol="rtsp") == 401  # anónimo, aunque sea local
    assert await _ask(client, action="read", path=path, protocol="webrtc", token=token, ip="192.168.1.30") == 200
    assert await _ask(client, action="read", path="otra-ruta", protocol="webrtc", token=token) == 401
    assert await _ask(client, action="read", path=path, protocol="webrtc", token="no-es-un-jwt") == 401
    assert await _ask(client, action="unknown", path=path, token=token) == 401
    # El acceso concedido al vídeo queda auditado (dato personal)
    items = (await client.get("/api/v1/audit", headers=auth(token), params={"action": "media."})).json()["items"]
    assert len(items) == 1 and items[0]["entity_id"] == path and items[0]["ip"] == "192.168.1.30"
    # Cerrar la sesión invalida el token también para el vídeo
    await client.post("/api/v1/auth/logout", headers=auth(token))
    assert await _ask(client, action="read", path=path, protocol="webrtc", token=token) == 401


async def test_media_auth_disabled_without_key(client, settings):
    client.app.state.container.settings = settings.model_copy(update={"mediamtx_auth_key": None})
    assert (await client.post("/api/v1/media/auth?key=x", json={"action": "read"})).status_code == 404


async def test_metrics_only_from_allowed_networks(client):
    import httpx

    assert (await client.get("/metrics")).status_code == 200  # 127.0.0.1
    for ip, code in (("192.168.1.40", 200), ("203.0.113.7", 404)):
        transport = httpx.ASGITransport(app=client.app, client=(ip, 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            assert (await c.get("/metrics")).status_code == code, ip
