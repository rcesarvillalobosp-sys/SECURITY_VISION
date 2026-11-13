from __future__ import annotations

from uuid import UUID

import pytest

from .conftest import auth, login

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(settings, tmp_path):
    return settings.model_copy(update={"allow_test_sources": True, "storage_dir": str(tmp_path / "s")})


async def test_profiles_zones_and_camera_rules(client):
    admin = await login(client)
    h = auth(admin)
    # El bootstrap crea un perfil por defecto
    profiles = (await client.get("/api/v1/security-profiles", headers=h)).json()
    assert [p["name"] for p in profiles] == ["EPP básico (casco + chaleco)"]
    assert profiles[0]["required_ppe"] == ["helmet", "safety_vest"]

    cat = (await client.get("/api/v1/security-profiles/catalog", headers=h)).json()
    assert "safety_boot" in cat["evaluable_ppe"] and cat["default_thresholds"]["min_explicit_absences_to_confirm"] == 2

    bad = await client.post("/api/v1/security-profiles", headers=h, json={
        "name": "x", "required_ppe": ["helmet"], "thresholds": {"min_observations": 1}})
    assert bad.status_code == 422
    bad2 = await client.post("/api/v1/security-profiles", headers=h, json={"name": "x", "required_ppe": ["casco"]})
    assert bad2.status_code == 422
    full = (await client.post("/api/v1/security-profiles", headers=h, json={
        "name": "Obra completa", "required_ppe": ["helmet", "safety_vest", "safety_boot"],
        "thresholds": {"confirm_seconds": 8}})).json()
    assert full["thresholds"]["confirm_seconds"] == 8 and full["version"] == 1
    upd = (await client.patch(f"/api/v1/security-profiles/{full['id']}", headers=h,
                              json={"thresholds": {"window_seconds": 10}})).json()
    assert upd["version"] == 2 and upd["thresholds"]["confirm_seconds"] == 8  # se conserva lo no modificado

    cam = (await client.post("/api/v1/cameras", headers=h, json={
        "name": "C1", "source_type": "test", "source_uri": "testpattern://", "default_profile_id": profiles[0]["id"]
    })).json()
    assert cam["default_profile_id"] == profiles[0]["id"]
    missing = await client.patch(f"/api/v1/cameras/{cam['id']}", headers=h,
                                 json={"default_profile_id": "01890000-0000-7000-8000-000000000999"})
    assert missing.status_code == 422

    zone = (await client.post(f"/api/v1/cameras/{cam['id']}/zones", headers=h, json={
        "name": "Andamio", "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.9]], "profile_id": full["id"]})).json()
    assert zone["profile_id"] == full["id"]
    bad_zone = await client.post(f"/api/v1/cameras/{cam['id']}/zones", headers=h, json={
        "name": "Mal", "polygon": [[0.1, 0.1], [2.0, 0.1], [0.5, 0.9]]})
    assert bad_zone.status_code == 422
    # Perfil en uso: no se puede borrar
    assert (await client.delete(f"/api/v1/security-profiles/{full['id']}", headers=h)).status_code == 409

    # Reglas efectivas tal y como las cargará el worker
    uow = client.app.state.container.rules._uow
    async with uow() as u:
        rules = await u.rules.camera_rules(UUID(cam["id"]))
    assert rules.default_profile.name.startswith("EPP básico")
    assert rules.zones[0].profile.required_ppe == ("helmet", "safety_vest", "safety_boot")
    assert rules.zones[0].profile.thresholds.window_seconds == 10

    await client.patch(f"/api/v1/zones/{zone['id']}", headers=h, json={"enabled": False})
    async with uow() as u:
        assert (await u.rules.camera_rules(UUID(cam["id"]))).zones == ()
    assert (await client.delete(f"/api/v1/zones/{zone['id']}", headers=h)).status_code == 204
    assert (await client.delete(f"/api/v1/security-profiles/{full['id']}", headers=h)).status_code == 204


async def test_viewer_cannot_change_rules(client):
    admin = await login(client)
    await client.post("/api/v1/users", headers=auth(admin), json={
        "email": "v2@test.local", "display_name": "V", "password": "Viewer-Seguro-2", "roles": ["viewer"]})
    viewer = await login(client, "v2@test.local", "Viewer-Seguro-2")
    assert (await client.get("/api/v1/security-profiles", headers=auth(viewer))).status_code == 200
    r = await client.post("/api/v1/security-profiles", headers=auth(viewer),
                          json={"name": "x", "required_ppe": ["helmet"]})
    assert r.status_code == 403
