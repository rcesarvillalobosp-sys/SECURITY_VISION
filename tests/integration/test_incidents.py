"""Incidentes: registro idempotente con evidencia, outbox, API de revisión, evidencias firmadas,
integridad, retención y flujo completo cámara -> reglas -> incidente en el worker real."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import text

from security_vision.core.domain.compliance import Violation
from security_vision.core.domain.geometry import BBox, Size
from security_vision.core.domain.incidents import EvidenceImage, NewIncident
from security_vision.core.domain.vision import Detection

from .conftest import auth, login

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def settings(settings, tmp_path):
    return settings.model_copy(update={"allow_test_sources": True, "storage_dir": str(tmp_path / "storage"),
                                       "worker_snapshot_seconds": 0.5})


async def _camera(client, h, **extra):
    r = await client.post("/api/v1/cameras", headers=h, json={"name": "C1", "source_type": "test",
                                                              "source_uri": "testpattern://?fps=15", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _new_incident(camera_id: str, confirmed_at: datetime = NOW, kinds=("frame", "annotated")) -> NewIncident:
    v = Violation(camera_id=camera_id, track_id=7, ppe_class="helmet", confirmed_at=confirmed_at, confidence=0.91,
                  started_at=confirmed_at - timedelta(seconds=6), details={"absent_explicit": 4.0})
    det = Detection(camera_id=UUID(camera_id), frame_id=42, frame_ts=confirmed_at, frame_size=Size(640, 480),
                    class_name="no_helmet", bbox=BBox(0.1, 0.1, 0.2, 0.2), confidence=0.8, model_id="m@1",
                    inference_ms=50.0)
    imgs = tuple(EvidenceImage(kind=k, data=f"jpeg-{k}".encode(), content_type="image/jpeg", width=640, height=480,
                               captured_at=confirmed_at, frame_id=42, detections=(det,), track_ids={0: 7})
                 for k in kinds)
    return NewIncident(violation=v, camera_name="C1", model_id="m@1", profile_version=1, evidences=imgs)


async def test_record_is_idempotent_and_transactional(client):
    admin = await login(client)
    cam = await _camera(client, auth(admin))
    svc = client.app.state.container.incidents
    inc, created = await svc.record(_new_incident(cam["id"]))
    again, created2 = await svc.record(_new_incident(cam["id"]))
    assert created and not created2 and again.id == inc.id
    engine = client.app.state.container.engine
    async with engine.begin() as conn:
        n_inc = (await conn.execute(text("SELECT count(*) FROM incidents"))).scalar_one()
        n_ev = (await conn.execute(text("SELECT count(*) FROM evidences"))).scalar_one()
        det = (await conn.execute(text("SELECT class_name, track_id, frame_id, model_id, inference_ms, bbox "
                                       "FROM detections LIMIT 1"))).one()
        outbox = (await conn.execute(text("SELECT event_type FROM event_outbox"))).scalars().all()
    assert (n_inc, n_ev) == (1, 2)
    assert det.class_name == "no_helmet" and det.track_id == 7 and det.frame_id == 42 and det.model_id == "m@1"
    assert outbox == ["incident.confirmed.v1"]  # una sola vez pese al reintento


async def test_outbox_relay_publishes(client):
    from security_vision.infrastructure.messaging.outbox import OutboxRelay

    admin = await login(client)
    cam = await _camera(client, auth(admin))
    c = client.app.state.container
    await c.incidents.record(_new_incident(cam["id"]))
    published = []

    class FakeBus:
        async def publish(self, event):
            published.append(event)

    relay = OutboxRelay(c.engine, FakeBus())  # type: ignore[arg-type]
    await relay.run_once()  # (el relé de la API también puede haberlo publicado ya: SKIP LOCKED)
    async with c.engine.begin() as conn:
        q = text("SELECT count(*) FROM event_outbox WHERE published_at IS NULL")
        pending = (await conn.execute(q)).scalar_one()
    assert pending == 0


async def test_review_flow_evidence_access_and_rbac(client, settings):
    admin = await login(client)
    h = auth(admin)
    cam = await _camera(client, h)
    c = client.app.state.container
    inc, _ = await c.incidents.record(_new_incident(cam["id"]))

    page = (await client.get("/api/v1/incidents", headers=h, params={"status": "PENDIENTE"})).json()
    assert page["total"] == 1 and page["items"][0]["violation_type"] == "helmet"
    d = (await client.get(f"/api/v1/incidents/{inc.id}", headers=h)).json()
    assert sorted(e["kind"] for e in d["evidences"]) == ["annotated", "frame"]
    assert d["history"][0]["action"] == "created" and d["detections"][0]["track_id"] == 7

    # Evidencia por URL firmada (sin cabecera Authorization) y auditada
    url = d["evidences"][0]["url"]
    r = await client.get(url)
    assert r.status_code == 200 and r.content.startswith(b"jpeg-") and r.headers["cache-control"].startswith("private")
    tampered = url.replace("sig=", "sig=0")
    assert (await client.get(tampered)).status_code == 403
    other_user = url.replace(parse_qs(urlsplit(url).query)["u"][0], "01890000-0000-7000-8000-000000000000")
    assert (await client.get(other_user)).status_code == 403  # la firma está ligada al usuario
    # Integridad: si el archivo se altera en disco, no se sirve
    key = urlsplit(url).path.removeprefix("/api/v1/files/")
    Path(settings.storage_dir, key).write_bytes(b"alterado")
    assert (await client.get(url)).status_code == 409
    async with c.engine.begin() as conn:
        q = text("SELECT action FROM audit_log WHERE action LIKE 'evidence.%'")
        actions = (await conn.execute(q)).scalars().all()
    assert "evidence.viewed" in actions and "evidence.integrity_failed" in actions

    # Revisión humana
    bad = await client.patch(f"/api/v1/incidents/{inc.id}/status", headers=h, json={"status": "RESUELTO"})
    assert bad.status_code == 422  # PENDIENTE -> RESUELTO no permitido
    need_note = await client.patch(f"/api/v1/incidents/{inc.id}/status", headers=h, json={"status": "DESCARTADO"})
    assert need_note.status_code == 422  # descartar exige nota
    ok = await client.patch(f"/api/v1/incidents/{inc.id}/status", headers=h, json={"status": "CONFIRMADO",
                                                                                     "note": "Sin casco"})
    assert ok.status_code == 200 and ok.json()["status"] == "CONFIRMADO"
    assert (await client.post(f"/api/v1/incidents/{inc.id}/comments", headers=h,
                              json={"body": "Avisado el encargado"})).status_code == 201
    await client.patch(f"/api/v1/incidents/{inc.id}/status", headers=h, json={"status": "RESUELTO",
                                                                                "note": "Formación impartida"})
    d2 = (await client.get(f"/api/v1/incidents/{inc.id}", headers=h)).json()
    assert [x["to_status"] for x in d2["history"] if x["action"] == "status_changed"] == ["CONFIRMADO", "RESUELTO"]
    assert d2["comments"][0]["body"] == "Avisado el encargado"

    # RBAC: el lector ve pero no revisa; el operador revisa
    await client.post("/api/v1/users", headers=h, json={"email": "lector@test.local", "display_name": "L",
                                                        "password": "Lector-Seguro-1", "roles": ["viewer"]})
    viewer = await login(client, "lector@test.local", "Lector-Seguro-1")
    assert (await client.get(f"/api/v1/incidents/{inc.id}", headers=auth(viewer))).status_code == 200
    r = await client.patch(f"/api/v1/incidents/{inc.id}/status", headers=auth(viewer),
                           json={"status": "EN_REVISION"})
    assert r.status_code == 403


async def test_retention_purges_old_evidence_and_orphans(client, settings):
    from security_vision.composition import build_retention

    admin = await login(client)
    cam = await _camera(client, auth(admin))
    c = client.app.state.container
    old, _ = await c.incidents.record(_new_incident(cam["id"], confirmed_at=datetime.now(UTC) - timedelta(days=120)))
    recent, _ = await c.incidents.record(_new_incident(cam["id"], confirmed_at=datetime.now(UTC)))
    orphan = Path(settings.storage_dir, "evidences/huerfano.jpg")
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x")
    import os
    import time

    past = time.time() - 3 * 86400
    os.utime(orphan, (past, past))
    report = await build_retention(settings, c.engine).purge()
    assert report.evidences_purged == 2 and report.orphans_deleted == 1 and not orphan.exists()
    d_old = (await client.get(f"/api/v1/incidents/{old.id}", headers=auth(admin))).json()
    assert all(e["purged"] and e["url"] is None for e in d_old["evidences"])  # metadatos conservados
    d_new = (await client.get(f"/api/v1/incidents/{recent.id}", headers=auth(admin))).json()
    assert not any(e["purged"] for e in d_new["evidences"])


async def test_end_to_end_camera_to_incident_with_evidence(client, settings):
    """Cámara real del worker (patrón de prueba) + detector simulado que siempre ve a una persona sin
    casco -> reglas -> incidente con evidencia en BD y en disco. El detector es simulado a propósito:
    lo que se prueba aquí es la cadena del sistema, no la precisión del modelo."""
    import security_vision_worker.main as wmain

    from security_vision.modules.detection.service import DetectionService

    admin = await login(client)
    h = auth(admin)
    prof = (await client.post("/api/v1/security-profiles", headers=h, json={
        "name": "Rápido (test)", "required_ppe": ["helmet"],
        "thresholds": {"window_seconds": 2, "confirm_seconds": 1, "min_observations": 2,
                       "min_absent_observations": 2, "min_person_height_px": 20}})).json()
    await _camera(client, h, analysis_fps=5, default_profile_id=prof["id"])

    class FakeModel:
        class spec:
            model_id = "simulado@1"

        @staticmethod
        def _det(f, cid, cls, b, cf):
            return Detection(camera_id=UUID(cid), frame_id=f.frame_id, frame_ts=f.captured_at,
                             frame_size=Size(f.width, f.height), class_name=cls, bbox=BBox(*b), confidence=cf,
                             model_id="simulado@1", inference_ms=1.0)

        def detect(self, frames, camera_ids):
            out = []
            for f, cid in zip(frames, camera_ids, strict=True):
                out.append([self._det(f, cid, "person", (0.40, 0.20, 0.55, 0.90), 0.95),
                            self._det(f, cid, "no_helmet", (0.43, 0.19, 0.52, 0.30), 0.85)])
            return out

    runtime, engine, bus = wmain.build_runtime(settings.model_copy(update={"detection_model": None}))
    runtime.detector = DetectionService(FakeModel())  # type: ignore[arg-type]
    runtime.loop = asyncio.get_running_loop()
    tasks = [asyncio.create_task(t) for t in (runtime.status_writer(), runtime.incident_writer(),
                                                runtime.event_publisher())]
    try:
        await runtime.reconcile()
        incident = None
        for _ in range(60):
            await asyncio.sleep(0.25)
            page = (await client.get("/api/v1/incidents", headers=h)).json()
            if page["total"]:
                incident = page["items"][0]
                break
        assert incident is not None, "no se generó el incidente"
        assert incident["violation_type"] == "helmet" and incident["camera_name"] == "C1"
        assert incident["model_id"] == "simulado@1" and incident["profile_version"] == 1
        d = (await client.get(f"/api/v1/incidents/{incident['id']}", headers=h)).json()
        kinds = [e["kind"] for e in d["evidences"]]
        assert {"frame", "annotated", "crop"} <= set(kinds)
        img = await client.get(d["evidences"][-1]["url"])
        assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"  # JPEG real en disco
        assert {x["class_name"] for x in d["detections"]} >= {"person", "no_helmet"}
        assert page["total"] == 1  # una persona, un incidente (no uno por fotograma)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.to_thread(runtime.shutdown)
        await bus.close()
        await engine.dispose()  # type: ignore[attr-defined]


_ = np
