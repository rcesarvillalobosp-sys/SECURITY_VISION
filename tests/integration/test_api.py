from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, auth, login

pytestmark = pytest.mark.anyio


async def test_health_and_metrics(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok"
    m = (await client.get("/metrics")).text
    assert 'sv_http_requests_total{method="GET",route="/health/ready",status="200"}' in m
    assert "sv_process_uptime_seconds" in m
    assert r.headers["x-content-type-options"] == "nosniff" and "x-request-id" in r.headers


async def test_login_me_and_refresh_cookie_is_httponly(client):
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL.upper(), "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "sv_refresh=" in cookie and "HttpOnly" in cookie and "samesite=strict" in cookie.lower()
    assert "refresh" not in r.json()  # el refresh token NUNCA viaja en el cuerpo
    me = (await client.get("/api/v1/auth/me", headers=auth(r.json()["access_token"]))).json()
    assert me["roles"] == ["admin"] and "users:write" in me["permissions"]


async def test_failed_logins_are_generic_and_lock_account(client):
    bad = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "mala"})
    unknown = await client.post("/api/v1/auth/login", json={"email": "nadie@test.local", "password": "x"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()  # sin enumeración de usuarios
    for _ in range(2):  # max_failed_logins=3 en los tests
        await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "mala"})
    locked = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert locked.status_code == 429


async def test_refresh_rotation_and_reuse_detection(client):
    await login(client)
    old = client.cookies.get("sv_refresh")
    r1 = await client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    new = client.cookies.get("sv_refresh")
    assert new and new != old
    access = r1.json()["access_token"]
    # Reutilizar el token anterior (robado) revoca la sesión completa.
    client.cookies.set("sv_refresh", old, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    client.cookies.set("sv_refresh", new, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=auth(access))).status_code == 401


async def test_logout_revokes_access_token_immediately(client):
    token = await login(client)
    assert (await client.post("/api/v1/auth/logout", headers=auth(token))).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=auth(token))).status_code == 401


async def test_rbac_user_admin_flow(client):
    admin = await login(client)
    assert (await client.get("/api/v1/users")).status_code == 401
    weak = await client.post("/api/v1/users", headers=auth(admin), json={
        "email": "op@test.local", "display_name": "Op", "password": "debilisimaaaa", "roles": ["viewer"]})
    assert weak.status_code == 422
    body = {"email": "Op@Test.local", "display_name": "Operador", "password": "Operador-Seguro-1", "roles": ["viewer"]}
    created = await client.post("/api/v1/users", headers=auth(admin), json=body)
    assert created.status_code == 201 and created.json()["email"] == "op@test.local"
    assert (await client.post("/api/v1/users", headers=auth(admin), json=body)).status_code == 409
    bad_role = {**body, "email": "x@test.local", "roles": ["superuser"]}
    assert (await client.post("/api/v1/users", headers=auth(admin), json=bad_role)).status_code == 422

    viewer = await login(client, "op@test.local", "Operador-Seguro-1")
    assert (await client.get("/api/v1/users", headers=auth(viewer))).status_code == 403
    uid = created.json()["id"]
    r = await client.put(f"/api/v1/users/{uid}/roles", headers=auth(admin), json={"roles": ["supervisor"]})
    assert r.status_code == 200 and r.json()["roles"] == ["supervisor"]
    # Cambiar roles cierra las sesiones del usuario: el token viejo deja de valer.
    assert (await client.get("/api/v1/auth/me", headers=auth(viewer))).status_code == 401
    supervisor = await login(client, "op@test.local", "Operador-Seguro-1")
    listing = await client.get("/api/v1/users", headers=auth(supervisor))
    assert listing.status_code == 200 and listing.json()["total"] == 2
    roles = (await client.get("/api/v1/roles", headers=auth(supervisor))).json()
    assert {r["name"] for r in roles} == {"admin", "supervisor", "operator", "viewer"}


async def test_admin_cannot_remove_own_admin_role(client):
    admin = await login(client)
    me = (await client.get("/api/v1/auth/me", headers=auth(admin))).json()
    r = await client.put(f"/api/v1/users/{me['user_id']}/roles", headers=auth(admin), json={"roles": ["viewer"]})
    assert r.status_code == 422


async def test_audit_log_is_append_only_and_records_logins(client):
    await login(client)
    engine = client.app.state.container.engine
    async with engine.begin() as conn:
        actions = (await conn.execute(text("SELECT action FROM audit_log ORDER BY id"))).scalars().all()
    assert "auth.login" in actions
    for stmt in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError, match="solo inserción"):
            async with engine.begin() as conn:
                await conn.execute(text(stmt))


async def test_camera_uri_cannot_embed_credentials(client):
    engine = client.app.state.container.engine
    with pytest.raises(IntegrityError, match="no_credentials_in_uri"):
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO cameras (id, name, source_type, source_uri, analysis_fps, enabled, "
                                    "location) VALUES (gen_random_uuid(), 'c1', 'rtsp', "
                                    "'rtsp://admin:clave@10.0.0.5/stream', 2, true, '{}')"))
