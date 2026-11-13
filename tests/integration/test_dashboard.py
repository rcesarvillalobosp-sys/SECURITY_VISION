"""Panel: KPI y series desde estadísticas reales, y WebSocket en vivo (auth, origen, reparto, caducidad)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from security_vision.infrastructure.database.repositories.stats import upsert_minutes

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, auth, login

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(settings, tmp_path):
    return settings.model_copy(update={"allow_test_sources": True, "storage_dir": str(tmp_path / "s")})


async def test_summary_and_series_from_stats(client):
    admin = await login(client)
    h = auth(admin)
    cam = (await client.post("/api/v1/cameras", headers=h, json={
        "name": "C1", "source_type": "test", "source_uri": "testpattern://"})).json()
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    row = {"camera_id": cam["id"], "bucket": now, "analyzed_frames": 10, "person_frames": 20, "max_persons": 3,
           "compliant": 12, "in_review": 3, "possible": 2, "confirmed": 1, "unverifiable": 2}
    engine = client.app.state.container.engine
    await upsert_minutes(engine, [row])
    await upsert_minutes(engine, [row])  # aditivo: el mismo minuto se suma
    s = (await client.get("/api/v1/dashboard/summary", headers=h)).json()
    # cumplimiento = conformes / (conformes + posibles + confirmados) = 24 / 30
    assert s["compliance_today_pct"] == 80.0
    assert s["cameras"]["enabled"] == 1 and s["cameras"]["disconnected"] == 1  # sin worker: no transmite
    assert s["incidents"]["today"] == 0 and s["avg_persons_per_frame_today"] == 2.0
    ser = (await client.get("/api/v1/dashboard/series", headers=h, params={"range": "24h"})).json()
    assert ser["step"] == "hour" and ser["compliance"][-1]["compliance_pct"] == 80.0
    assert ser["compliance"][-1]["max_persons"] == 3
    assert (await client.get("/api/v1/dashboard/series", headers=h, params={"range": "1y"})).status_code == 422


def test_websocket_auth_origin_and_live_frames(settings):
    """TestClient síncrono (necesario para WebSocket); usa la misma BD de pruebas."""
    from security_vision.core.events.catalog import CameraStatusChanged
    from security_vision.infrastructure.messaging.postgres_bus import PostgresMessageBus
    from security_vision_api.main import create_app

    async def ensure_admin() -> None:
        from security_vision.infrastructure.database.session import create_engine, uow_factory
        from security_vision.infrastructure.security.adapters import Argon2PasswordHasher
        from security_vision.modules.users.services import bootstrap

        engine = create_engine(settings.database_url.get_secret_value(), pool_size=1)
        await bootstrap(uow_factory(engine), Argon2PasswordHasher(), ADMIN_EMAIL, ADMIN_PASSWORD)
        await engine.dispose()

    asyncio.run(ensure_admin())  # autosuficiente: no depende del orden de los tests
    app = create_app(settings)
    with TestClient(app) as tc:
        token = tc.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).json()[
            "access_token"]
        # Sin auth en el primer mensaje: se cierra
        with tc.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(json.dumps({"type": "subscribe"}))
            with pytest.raises(Exception):  # noqa: B017 - cierre 4401
                ws.receive_text()
        # Origen no permitido: rechazado antes de aceptar
        with pytest.raises(Exception), tc.websocket_connect(  # noqa: B017
                "/api/v1/ws", headers={"origin": "https://evil.example"}):
            pass
        with tc.websocket_connect("/api/v1/ws", headers={"origin": "http://localhost:5173"}) as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            assert json.loads(ws.receive_text())["type"] == "ready"
            ws.send_text(json.dumps({"type": "subscribe", "cameras": ["cam-a"]}))

            async def publish() -> None:
                bus = PostgresMessageBus(settings.database_url.get_secret_value())
                await asyncio.sleep(0.5)
                frame = {"cam": "cam-b", "ts": datetime.now(UTC).isoformat(), "fid": 1, "w": 640, "h": 480,
                         "tracks": [], "items": []}
                await bus.publish_raw("sv_live", json.dumps(frame))  # no suscrita: no debe llegar
                frame |= {"cam": "cam-a", "tracks": [{"id": 3, "b": [0.1, 0.1, 0.2, 0.5], "s": "CUMPLIMIENTO"}]}
                await bus.publish_raw("sv_live", json.dumps(frame))
                from uuid import uuid4

                await bus.publish(CameraStatusChanged(camera_id=uuid4(), status="streaming"))
                await bus.close()

            asyncio.run(publish())
            got = [json.loads(ws.receive_text()) for _ in range(2)]
            got = [m for m in got if m["type"] != "ping"]
            frames = [m for m in got if m["type"] == "frame"]
            events = [m for m in got if m["type"] == "event"]
            assert frames and frames[0]["data"]["cam"] == "cam-a" and frames[0]["data"]["tracks"][0]["id"] == 3
            assert events and events[0]["event"] == "camera.status_changed.v1"
        assert app.state.container.live.clients == set()  # el cliente se libera al desconectar


_ = (timedelta, login)


def test_websocket_through_real_uvicorn(settings):
    """El TestClient no pasa por uvicorn: no detectó que faltaba la biblioteca de WebSocket.
    Aquí se arranca un uvicorn real y se conecta un cliente WebSocket real."""
    import socket
    import threading
    import time

    import uvicorn
    from websockets.sync.client import connect

    from security_vision_api.main import create_app

    async def ensure_admin() -> None:
        from security_vision.infrastructure.database.session import create_engine, uow_factory
        from security_vision.infrastructure.security.adapters import Argon2PasswordHasher
        from security_vision.modules.users.services import bootstrap

        engine = create_engine(settings.database_url.get_secret_value(), pool_size=1)
        await bootstrap(uow_factory(engine), Argon2PasswordHasher(), ADMIN_EMAIL, ADMIN_PASSWORD)
        await engine.dispose()

    asyncio.run(ensure_admin())
    with socket.socket() as sck:
        sck.bind(("127.0.0.1", 0))
        port = sck.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        import httpx

        token = httpx.post(f"http://127.0.0.1:{port}/api/v1/auth/login",
                           json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).json()["access_token"]
        with connect(f"ws://127.0.0.1:{port}/api/v1/ws", origin="http://localhost:5173") as ws:
            ws.send(json.dumps({"type": "auth", "token": token}))
            assert json.loads(ws.recv(timeout=5))["type"] == "ready"
    finally:
        server.should_exit = True
        t.join(10)
