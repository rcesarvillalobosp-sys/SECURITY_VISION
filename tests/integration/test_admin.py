"""Fase 8: administración de usuarios, auditoría, modelos, canales de alerta (webhook y email reales) y reportes."""

from __future__ import annotations

import email
import hashlib
import hmac
import io
import json
import socket
import threading
from datetime import UTC, datetime, timedelta
from email import policy
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import text

from security_vision.infrastructure.database.repositories.stats import upsert_minutes

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, auth, login
from .test_incidents import _new_incident

pytestmark = pytest.mark.anyio
VIEWER = ("viewer@test.local", "Viewer-Pruebas-2026!")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Receiver:
    """Servidor HTTP real que recibe webhooks y responde con el código configurado."""

    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, str], bytes]] = []
        self.status = 200
        rec = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                rec.requests.append(({k.lower(): v for k, v in self.headers.items()}, body))
                self.send_response(rec.status)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a: object) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class SmtpSink:
    """Servidor SMTP real (aiosmtpd) que guarda los mensajes recibidos."""

    def __init__(self) -> None:
        from aiosmtpd.controller import Controller

        self.messages: list[tuple[list[str], bytes]] = []
        sink = self

        class Handler:
            async def handle_DATA(self, server, session, envelope):
                sink.messages.append((list(envelope.rcpt_tos), envelope.original_content or envelope.content))
                return "250 OK"

        self.port = _free_port()
        self.controller = Controller(Handler(), hostname="127.0.0.1", port=self.port)
        self.controller.start()

    def close(self) -> None:
        self.controller.stop()


@pytest.fixture(scope="module")
def smtp():
    s = SmtpSink()
    yield s
    s.close()


@pytest.fixture
def settings(settings, tmp_path, smtp):
    return settings.model_copy(update={
        "allow_test_sources": True, "storage_dir": str(tmp_path / "storage"),
        "alerts_enabled": False,  # el test controla el despachador (run_once) para ser determinista
        "alert_webhook_allow_private": True, "smtp_host": "127.0.0.1", "smtp_port": smtp.port,
        "smtp_security": "none", "smtp_from": "alertas@test.local", "public_web_url": "https://sv.example"})


async def _camera(client, h, name="C1"):
    r = await client.post("/api/v1/cameras", headers=h, json={"name": name, "source_type": "test",
                                                              "source_uri": "testpattern://"})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ usuarios y auditoría
async def test_user_admin_lifecycle_and_audit(client):
    h = auth(await login(client))
    r = await client.post("/api/v1/users", headers=h, json={"email": VIEWER[0], "display_name": "Vista",
                                                            "password": VIEWER[1], "roles": ["viewer"]})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    vtok = await login(client, *VIEWER)
    assert (await client.get("/api/v1/auth/me", headers=auth(vtok))).status_code == 200
    # Un viewer no administra usuarios
    assert (await client.patch(f"/api/v1/users/{uid}", headers=auth(vtok), json={"is_active": False})
            ).status_code == 403

    # Desactivar: sesiones cerradas al instante y login rechazado
    r = await client.patch(f"/api/v1/users/{uid}", headers=h, json={"is_active": False, "display_name": "V2"})
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["display_name"] == "V2"
    assert (await client.get("/api/v1/auth/me", headers=auth(vtok))).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": VIEWER[0], "password": VIEWER[1]})
            ).status_code == 401
    # No puedes desactivarte a ti mismo
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert (await client.patch(f"/api/v1/users/{me['user_id']}", headers=h, json={"is_active": False})
            ).status_code == 422

    # Reactivar y restablecer contraseña (política de complejidad aplicada)
    await client.patch(f"/api/v1/users/{uid}", headers=h, json={"is_active": True})
    assert (await client.post(f"/api/v1/users/{uid}/password", headers=h, json={"password": "corta"})
            ).status_code == 422
    assert (await client.post(f"/api/v1/users/{uid}/password", headers=h,
                              json={"password": "aaaaaaaaaaaaaaaa"})).status_code == 422
    new_pwd = "Nueva-Clave-2026!"
    assert (await client.post(f"/api/v1/users/{uid}/password", headers=h, json={"password": new_pwd})
            ).status_code == 204
    assert (await client.post("/api/v1/auth/login", json={"email": VIEWER[0], "password": VIEWER[1]})
            ).status_code == 401
    vtok = await login(client, VIEWER[0], new_pwd)

    # Cambio de contraseña propia: exige la actual y cierra las sesiones
    assert (await client.post("/api/v1/me/password", headers=auth(vtok),
                              json={"current_password": "mal", "new_password": "Otra-Clave-2026!"})
            ).status_code == 401
    assert (await client.post("/api/v1/me/password", headers=auth(vtok),
                              json={"current_password": new_pwd, "new_password": "Otra-Clave-2026!"})
            ).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=auth(vtok))).status_code == 401
    await login(client, VIEWER[0], "Otra-Clave-2026!")

    # Auditoría: filtrable, más reciente primero, sin contraseñas
    r = await client.get("/api/v1/audit", headers=h, params={"action": "user.", "entity_id": uid})
    assert r.status_code == 200
    actions = [i["action"] for i in r.json()["items"]]
    assert actions[0] == "user.password_changed"
    assert {"user.created", "user.updated", "user.password_reset"} <= set(actions)
    assert new_pwd not in r.text and VIEWER[1] not in r.text
    assert r.json()["items"][-1]["actor_email"] == ADMIN_EMAIL
    # El filtro por prefijo no interpreta comodines de LIKE
    assert (await client.get("/api/v1/audit", headers=h, params={"action": "user%"})).json()["total"] == 0
    assert (await client.get("/api/v1/audit", headers=auth(await login(client, VIEWER[0], "Otra-Clave-2026!")))
            ).status_code == 403


# ------------------------------------------------------------------ modelos
async def test_models_catalog_and_activation(client):
    h = auth(await login(client))
    r = await client.get("/api/v1/models", headers=h)
    assert r.status_code == 200
    data = r.json()
    ids = {m["model_id"]: m for m in data["models"]}
    assert "rtdetr-v2-r18-ppe-pilot@1" in ids
    pilot = ids["rtdetr-v2-r18-ppe-pilot@1"]
    if not pilot["artifact_present"]:
        pytest.skip("el artefacto ONNX del piloto no está exportado en este equipo")
    assert pilot["metrics"]["mAP50"] == 0.787 and "no_safety_boot" not in pilot["canonical_classes"]
    assert data["loaded"] is None  # sin worker: nadie ha informado de un modelo cargado
    assert (await client.put("/api/v1/models/active", headers=h, json={"model_id": "no-existe@1"})).status_code == 404
    assert (await client.put("/api/v1/models/active", headers=h, json={"model_id": "../../etc@1"})).status_code == 404
    r = await client.put("/api/v1/models/active", headers=h, json={"model_id": "rtdetr-v2-r18-coco@1"})
    assert r.status_code == 200 and r.json()["active_model"] == "rtdetr-v2-r18-coco@1"
    engine = client.app.state.container.engine
    async with engine.connect() as conn:
        ev = (await conn.execute(text("SELECT payload FROM event_outbox WHERE event_type = "
                                      "'detection.model_changed.v1' ORDER BY id DESC LIMIT 1"))).scalar()
    assert ev["payload"]["model_id"] == "rtdetr-v2-r18-coco@1"  # el worker recibirá el cambio por el outbox
    audit = (await client.get("/api/v1/audit", headers=h, params={"action": "models."})).json()["items"]
    assert audit[0]["after"] == {"model_id": "rtdetr-v2-r18-coco@1"}


# ------------------------------------------------------------------ alertas
async def test_webhook_channel_dispatch_signature_retries_and_idempotency(client):
    h = auth(await login(client))
    rx = Receiver()
    try:
        cam = await _camera(client, h)
        other = await _camera(client, h, "C2")
        secret = "s3creto-de-firma"
        r = await client.post("/api/v1/alert-channels", headers=h, json={
            "name": "SOC", "kind": "webhook", "config": {"url": rx.url}, "secret": secret,
            "violation_types": ["helmet"], "camera_ids": [cam["id"]]})
        assert r.status_code == 201, r.text
        ch = r.json()
        assert ch["has_secret"] and "secret" not in ch and secret not in r.text
        # Validaciones
        bad = await client.post("/api/v1/alert-channels", headers=h, json={
            "name": "X", "kind": "webhook", "config": {"url": "ftp://x"}})
        assert bad.status_code == 422
        bad = await client.post("/api/v1/alert-channels", headers=h, json={
            "name": "X", "kind": "webhook", "config": {"url": rx.url}, "violation_types": ["casco"]})
        assert bad.status_code == 422

        # Prueba manual del canal
        t = (await client.post(f"/api/v1/alert-channels/{ch['id']}/test", headers=h)).json()
        assert t["ok"] and t["response_code"] == 200
        hdrs, body = rx.requests[-1]
        assert json.loads(body)["test"] is True

        c = client.app.state.container
        disp = c.dispatcher
        # Tres incidentes: uno encaja; otro es de otra cámara; otro de otro tipo (filtrados)
        inc, _ = await c.incidents.record(_new_incident(cam["id"], confirmed_at=datetime.now(UTC)))
        await c.incidents.record(_new_incident(other["id"], confirmed_at=datetime.now(UTC)))
        n0 = len(rx.requests)
        assert await disp.run_once() == 1
        assert len(rx.requests) == n0 + 1
        hdrs, body = rx.requests[-1]
        payload = json.loads(body)
        assert payload["incident"]["id"] == str(inc.id) and payload["incident"]["violation_label"] == "Sin casco"
        assert payload["incident"]["link"] == f"https://sv.example/incidents/{inc.id}"
        expected = hmac.new(secret.encode(), hdrs["x-sv-timestamp"].encode() + b"." + body, hashlib.sha256).hexdigest()
        assert hdrs["x-sv-signature"] == f"sha256={expected}"
        # Idempotente: otra pasada no reenvía
        assert await disp.run_once() == 0 and len(rx.requests) == n0 + 1
        d = (await client.get("/api/v1/alert-deliveries", headers=h, params={"channel_id": ch["id"]})).json()
        assert d["total"] == 1 and d["items"][0]["status"] == "sent" and d["items"][0]["attempts"] == 1

        # 500 -> reintento programado; 400 -> fallo definitivo (no se reintenta)
        rx.status = 500
        await c.incidents.record(_new_incident(cam["id"], confirmed_at=datetime.now(UTC) + timedelta(seconds=1)))
        await disp.run_once()
        pend = (await client.get("/api/v1/alert-deliveries", headers=h, params={"status": "pending"})).json()
        assert pend["total"] == 1 and pend["items"][0]["attempts"] == 1
        assert "HTTP 500" in pend["items"][0]["last_error"]
        retry_at = datetime.fromisoformat(pend["items"][0]["next_attempt_at"])
        assert retry_at > datetime.now(UTC) + timedelta(seconds=20)  # backoff de 30 s
        engine = c.engine
        async with engine.begin() as conn:  # adelantar el reloj del reintento
            await conn.execute(text("UPDATE alert_deliveries SET next_attempt_at = now() WHERE status='pending'"))
        rx.status = 400
        await disp.run_once()
        failed = (await client.get("/api/v1/alert-deliveries", headers=h, params={"status": "failed"})).json()
        f0 = failed["items"][0]
        assert failed["total"] == 1 and f0["attempts"] == 2 and f0["response_code"] == 400
        # Reintento manual tras corregir el receptor: se envía y conserva el historial de intentos
        rx.status = 200
        r = await client.post(f"/api/v1/alert-deliveries/{f0['id']}/retry", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "pending"
        await disp.run_once()
        again = (await client.get("/api/v1/alert-deliveries", headers=h, params={"status": "sent"})).json()
        assert {i["id"]: i["attempts"] for i in again["items"]}[f0["id"]] == 3
        # Solo se reintentan entregas fallidas
        assert (await client.post(f"/api/v1/alert-deliveries/{f0['id']}/retry", headers=h)).status_code == 409

        # Canal deshabilitado: no se planifican entregas nuevas
        await client.patch(f"/api/v1/alert-channels/{ch['id']}", headers=h, json={"enabled": False})
        await c.incidents.record(_new_incident(cam["id"], confirmed_at=datetime.now(UTC) + timedelta(seconds=2)))
        before = len(rx.requests)
        await disp.run_once()
        assert len(rx.requests) == before
        # Quitar el secreto deja de firmar
        r = await client.patch(f"/api/v1/alert-channels/{ch['id']}", headers=h, json={"secret": "", "enabled": True})
        assert r.json()["has_secret"] is False
        await client.post(f"/api/v1/alert-channels/{ch['id']}/test", headers=h)
        assert "x-sv-signature" not in rx.requests[-1][0]
        audit = (await client.get("/api/v1/audit", headers=h, params={"action": "alerts."})).json()
        assert {"alerts.channel_created", "alerts.channel_updated", "alerts.channel_tested",
                "alerts.delivery_retried"} <= {
            i["action"] for i in audit["items"]}
        assert secret not in json.dumps(audit)
    finally:
        rx.close()


async def test_webhook_ssrf_guard():
    from security_vision.core.domain.alerts import AlertChannel, AlertMessage, ChannelKind
    from security_vision.infrastructure.alerts.webhook import WebhookSender

    rx = Receiver()
    try:
        ch = AlertChannel(id=None, name="x", kind=ChannelKind.WEBHOOK, enabled=True, config={"url": rx.url})  # type: ignore[arg-type]
        msg = AlertMessage(delivery_id="d", incident_id="i", camera_id=None, camera_name="c", violation_type="helmet",
                           violation_label="Sin casco", confidence=0.9, confirmed_at=datetime.now(UTC), zone_id=None,
                           model_id=None, link=None)
        r = await WebhookSender(allow_private=False).send(ch, None, msg)
        assert not r.ok and not r.retryable and "no permitido" in r.detail and rx.requests == []
        r = await WebhookSender(allow_private=True).send(ch, None, msg)
        assert r.ok and len(rx.requests) == 1
    finally:
        rx.close()


async def test_email_channel_with_evidence_through_real_smtp(client, smtp):
    h = auth(await login(client))
    info = (await client.get("/api/v1/alert-channels/info", headers=h)).json()
    assert info["email_available"] is True
    cam = await _camera(client, h)
    r = await client.post("/api/v1/alert-channels", headers=h, json={
        "name": "Correo", "kind": "email", "config": {"recipients": ["Jefe@Obra.example", "jefe@obra.example"]}})
    assert r.status_code == 201, r.text
    assert r.json()["config"]["recipients"] == ["jefe@obra.example"]  # normalizado y sin duplicados
    assert (await client.post("/api/v1/alert-channels", headers=h, json={
        "name": "Mal", "kind": "email", "config": {"recipients": ["no-es-correo"]}})).status_code == 422
    c = client.app.state.container
    smtp.messages.clear()
    inc, _ = await c.incidents.record(_new_incident(cam["id"], confirmed_at=datetime.now(UTC)))
    assert await c.dispatcher.run_once() == 1
    assert len(smtp.messages) == 1
    rcpts, raw = smtp.messages[0]
    assert rcpts == ["jefe@obra.example"]
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert msg["Subject"] == "Incidente EPP: Sin casco — C1"
    assert f"https://sv.example/incidents/{inc.id}" in msg.get_body(("plain",)).get_content()
    atts = [p for p in msg.walk() if p.get_content_type() == "image/jpeg"]
    assert len(atts) == 1 and atts[0].get_payload(decode=True) == b"jpeg-annotated"  # evidencia anotada real


# ------------------------------------------------------------------ reportes
async def test_reports_json_pdf_xlsx(client):
    from openpyxl import load_workbook

    h = auth(await login(client))
    cam = await _camera(client, h)
    c = client.app.state.container
    day = datetime(2026, 11, 10, tzinfo=UTC)
    # 2 incidentes el día 10 (uno descartado en revisión), 1 el día 12; 1 fuera del periodo diario
    a, _ = await c.incidents.record(_new_incident(cam["id"], confirmed_at=day + timedelta(hours=9)))
    await c.incidents.record(_new_incident(cam["id"], confirmed_at=day + timedelta(hours=15)))
    await c.incidents.record(_new_incident(cam["id"], confirmed_at=day + timedelta(days=2, hours=10)))
    r = await client.patch(f"/api/v1/incidents/{a.id}/status", headers=h, json={"status": "EN_REVISION"})
    assert r.status_code == 200, r.text
    r = await client.patch(f"/api/v1/incidents/{a.id}/status", headers=h,
                           json={"status": "DESCARTADO", "note": "falso positivo"})
    assert r.status_code == 200, r.text
    await upsert_minutes(c.engine, [{"camera_id": cam["id"], "bucket": day + timedelta(hours=9), "analyzed_frames": 60,
                                     "person_frames": 100, "max_persons": 4, "compliant": 80, "in_review": 5,
                                     "possible": 10, "confirmed": 10, "unverifiable": 20}])

    r = await client.get("/api/v1/reports/daily", headers=h, params={"date": "2026-11-10"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["totals"] == {"incidents": 2, "pending": 1, "confirmed_by_review": 0, "discarded": 1}
    assert d["compliance_pct"] == 80.0 and d["unverifiable_share_pct"] == round(100 * 20 / 120, 1)
    assert len(d["days"]) == 1 and d["by_type"] == {"helmet": 2}

    w = (await client.get("/api/v1/reports/weekly", headers=h, params={"date": "2026-11-12"})).json()
    assert w["totals"]["incidents"] == 3 and len(w["days"]) == 7  # lunes 9 a domingo 15
    assert w["days"][1]["compliance_pct"] == 80.0 and w["days"][0]["compliance_pct"] is None
    # La zona horaria del usuario desplaza el día: con UTC-10 las 09:00 UTC del 10 son el día 9
    tz = (await client.get("/api/v1/reports/daily", headers=h,
                           params={"date": "2026-11-09", "tz_offset_minutes": -600})).json()
    assert tz["totals"]["incidents"] == 1
    m = (await client.get("/api/v1/reports/monthly", headers=h, params={"date": "2026-11-20"})).json()
    assert m["totals"]["incidents"] == 3 and len(m["days"]) == 30

    pdf = await client.get("/api/v1/reports/weekly", headers=h, params={"date": "2026-11-12", "format": "pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-") and b"%%EOF" in pdf.content[-1024:]
    assert 'filename="reporte-weekly-2026-11-09.pdf"' in pdf.headers["content-disposition"]

    x = await client.get("/api/v1/reports/monthly", headers=h, params={"date": "2026-11-20", "format": "xlsx"})
    assert x.status_code == 200
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Resumen", "Por día", "Por cámara", "Incidentes"]
    inc_rows = list(wb["Incidentes"].iter_rows(min_row=2, values_only=True))
    assert len(inc_rows) == 3 and {r[4] for r in inc_rows} == {"Pendiente", "Descartado"}
    cams = list(wb["Por cámara"].iter_rows(min_row=2, values_only=True))
    assert cams[0][0] == "C1" and cams[0][1] == 3 and cams[0][3] == 1 and cams[0][8] == 80.0

    # Filtro por cámara, permisos y auditoría
    other = await _camera(client, h, "C2")
    f = (await client.get("/api/v1/reports/weekly", headers=h,
                          params={"date": "2026-11-12", "camera_id": other["id"]})).json()
    assert f["totals"]["incidents"] == 0 and f["cameras_filter"] == ["C2"]
    assert (await client.get("/api/v1/reports/daily", headers=h, params={"date": "2026-11-10", "format": "doc"})
            ).status_code == 422
    assert (await client.get("/api/v1/reports/daily", params={"date": "2026-11-10"})).status_code == 401
    audit = (await client.get("/api/v1/audit", headers=h, params={"action": "report."})).json()["items"]
    assert {a["after"]["format"] for a in audit} == {"pdf", "xlsx"}  # la vista previa JSON no se audita


async def test_formula_injection_is_neutralised_in_excel(client):
    from openpyxl import load_workbook

    h = auth(await login(client))
    cam = await _camera(client, h, "=HYPERLINK(\"http://evil\")")
    c = client.app.state.container
    inc = _new_incident(cam["id"], confirmed_at=datetime(2026, 11, 10, 9, tzinfo=UTC))
    from dataclasses import replace

    await c.incidents.record(replace(inc, camera_name=cam["name"]))
    x = await client.get("/api/v1/reports/daily", headers=h, params={"date": "2026-11-10", "format": "xlsx"})
    wb = load_workbook(io.BytesIO(x.content))
    val = wb["Incidentes"]["C2"].value
    assert val.startswith("'=")  # se guarda como texto, no como fórmula


_ = (ADMIN_PASSWORD,)


async def test_worker_hot_swaps_detection_model(client, settings):
    """Worker real con modelos ONNX reales (CPU): el ajuste de la administración cambia el modelo sin reiniciar."""
    from pathlib import Path

    import numpy as np
    from security_vision_worker.runtime import WorkerRuntime

    from security_vision.composition import build_detection_service, build_video_registry, camera_policy
    from security_vision.core.interfaces.video import Frame
    from security_vision.infrastructure.database.session import uow_factory
    from security_vision.infrastructure.models.store import RegistryModelCatalog

    cat = RegistryModelCatalog(Path(settings.model_registry_dir))
    needed = ("rtdetr-v2-r18-coco@1", "rtdetr-v2-r18-ppe-pilot@1")
    if not all((info := cat.get(m)) is not None and info.artifact_present for m in needed):
        pytest.skip("faltan artefactos ONNX exportados")
    s = settings.model_copy(update={"inference_devices": ["cpu"], "detection_model": "rtdetr-v2-r18-coco@1"})
    c = client.app.state.container
    rt = WorkerRuntime(uow=uow_factory(c.engine), cipher=c.cipher, registry=build_video_registry(), storage=c.storage,
                       policy=camera_policy(s), bus=None, media=None, publisher_factory=None,
                       model_loader=lambda mid: build_detection_service(s, mid), default_model=s.detection_model,
                       engine_name="onnxruntime")
    h = auth(await login(client))
    assert await rt.ensure_model() is True and rt.detector.model_id == "rtdetr-v2-r18-coco@1"
    assert await rt.ensure_model() is False  # sin cambios: no recarga
    loaded = (await client.get("/api/v1/models", headers=h)).json()["loaded"]
    assert loaded["model_id"] == "rtdetr-v2-r18-coco@1" and loaded["device"] == "cpu" and loaded["error"] is None

    old = rt.detector
    await client.put("/api/v1/models/active", headers=h, json={"model_id": "rtdetr-v2-r18-ppe-pilot@1"})
    assert await rt.ensure_model() is True
    assert rt.detector.model_id == "rtdetr-v2-r18-ppe-pilot@1" and rt.model_swaps == 1
    with pytest.raises(RuntimeError):
        old.model.engine.get_device()  # el anterior se liberó
    frame = Frame(data=np.zeros((480, 640, 3), np.uint8), frame_id=1, captured_at=datetime.now(UTC))
    rt.detector.detect(frame, "00000000-0000-0000-0000-000000000001")  # el nuevo modelo infiere de verdad
    m = (await client.get("/api/v1/models", headers=h)).json()
    assert m["active_model"] == m["loaded"]["model_id"] == "rtdetr-v2-r18-ppe-pilot@1"

    # Un modelo que no carga: se conserva el actual y se informa del error (sin reintentar en bucle)
    async with uow_factory(c.engine)() as uow:
        await uow.settings.set("detection.active_model", {"model_id": "no-existe@9"}, actor_id=None)
        await uow.commit()
    assert await rt.ensure_model() is False and rt.detector.model_id == "rtdetr-v2-r18-ppe-pilot@1"
    loaded = (await client.get("/api/v1/models", headers=h)).json()["loaded"]
    assert loaded["requested"] == "no-existe@9" and "no registrado" in loaded["error"]
    assert loaded["model_id"] == "rtdetr-v2-r18-ppe-pilot@1"
