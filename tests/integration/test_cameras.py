"""Cámaras: API, worker real (hilos de captura), PostgreSQL real y MediaMTX real (si está instalado)."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from security_vision.core.events.catalog import CameraConfigChanged
from security_vision.core.interfaces.video import VideoSourceConfig
from security_vision.infrastructure.messaging.postgres_bus import PostgresMessageBus
from security_vision.modules.cameras.supervisor import ReconnectPolicy

from .conftest import ADMIN_PASSWORD, auth, login

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def settings(settings, tmp_path):  # sobrescribe: habilita fuentes de prueba y almacenamiento temporal
    return settings.model_copy(update={"allow_test_sources": True, "storage_dir": str(tmp_path / "storage"),
                                       "worker_snapshot_seconds": 0.5})


async def _create(client, token, **body):
    r = await client.post("/api/v1/cameras", headers=auth(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_camera_crud_and_credential_protection(client):
    admin = await login(client)
    cam = await _create(client, admin, name="Puerta norte", source_type="rtsp",
                        source_uri="rtsp://192.0.2.10:554/stream1", username="admin", password="Sup3r-Secreta!")
    assert cam["has_credentials"] is True
    assert "Sup3r-Secreta!" not in str(cam) and "password" not in cam
    engine = client.app.state.container.engine
    async with engine.begin() as conn:
        blob = (await conn.execute(text("SELECT credentials_encrypted FROM cameras"))).scalar_one()
        audit = (await conn.execute(text("SELECT coalesce(after::text,'') FROM audit_log "
                                          "WHERE action LIKE 'camera.%'"))).scalars().all()
    assert b"Sup3r-Secreta!" not in blob and not any("Sup3r" in a for a in audit)
    # Las credenciales cifradas están ligadas a la cámara (AAD): se descifran correctamente.
    from security_vision.modules.cameras.service import decrypt_credentials

    full = await client.app.state.container.cameras.get(cam["id"])
    assert decrypt_credentials(full, client.app.state.container.cipher) == ("admin", "Sup3r-Secreta!")

    bad = await client.post("/api/v1/cameras", headers=auth(admin), json={
        "name": "x", "source_type": "rtsp", "source_uri": "rtsp://admin:pw@192.0.2.10/s"})
    assert bad.status_code == 422 and "credenciales" in bad.text
    dup = await client.post("/api/v1/cameras", headers=auth(admin), json={
        "name": "Puerta norte", "source_type": "rtsp", "source_uri": "rtsp://192.0.2.11/s"})
    assert dup.status_code == 409
    no_files = await client.post("/api/v1/cameras", headers=auth(admin), json={
        "name": "f", "source_type": "file", "source_uri": "a.mp4"})
    assert no_files.status_code == 422

    r = await client.patch(f"/api/v1/cameras/{cam['id']}", headers=auth(admin),
                           json={"analysis_fps": 5, "target_fps": 15, "name": "Puerta Norte A"})
    assert r.status_code == 200 and r.json()["analysis_fps"] == 5 and r.json()["has_credentials"]
    bad_fps = await client.patch(f"/api/v1/cameras/{cam['id']}", headers=auth(admin), json={"analysis_fps": 30})
    assert bad_fps.status_code == 422  # supera target_fps
    assert len((await client.get("/api/v1/cameras", headers=auth(admin))).json()) == 1
    assert (await client.delete(f"/api/v1/cameras/{cam['id']}", headers=auth(admin))).status_code == 204
    assert (await client.get(f"/api/v1/cameras/{cam['id']}", headers=auth(admin))).status_code == 404


async def test_viewer_cannot_manage_cameras(client):
    admin = await login(client)
    await client.post("/api/v1/users", headers=auth(admin), json={
        "email": "v@test.local", "display_name": "V", "password": "Viewer-Seguro-1", "roles": ["viewer"]})
    viewer = await login(client, "v@test.local", "Viewer-Seguro-1")
    assert (await client.get("/api/v1/cameras", headers=auth(viewer))).status_code == 200
    r = await client.post("/api/v1/cameras", headers=auth(viewer), json={
        "name": "x", "source_type": "test", "source_uri": "testpattern://"})
    assert r.status_code == 403


async def test_connectivity_probe(client):
    admin = await login(client)
    ok = await _create(client, admin, name="Patrón", source_type="test", source_uri="testpattern://?width=320&height=240")
    r = (await client.post(f"/api/v1/cameras/{ok['id']}/test", headers=auth(admin))).json()
    assert r["ok"] is True and r["width"] == 320 and r["height"] == 240
    dead = await _create(client, admin, name="Apagada", source_type="rtsp", source_uri="rtsp://127.0.0.1:1/x")
    t0 = time.monotonic()
    r = (await client.post(f"/api/v1/cameras/{dead['id']}/test", headers=auth(admin))).json()
    assert r["ok"] is False and r["error"] and time.monotonic() - t0 < 20


async def test_postgres_bus_roundtrip(db_url):
    bus = PostgresMessageBus(db_url)
    try:
        received: list = []

        async def consume():
            async for ev in bus.subscribe(["camera.config_changed.v1"]):
                received.append(ev)
                return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.5)  # dar tiempo a LISTEN
        from uuid import uuid4

        ev = CameraConfigChanged(camera_id=uuid4(), action="created")
        await bus.publish(ev)
        await asyncio.wait_for(task, 5)
        assert received == [ev]
    finally:
        await bus.close()


async def test_worker_isolation_status_and_snapshots(client, settings):
    """3 cámaras (2 sanas + 1 que no conecta) en el worker real; estado en BD, snapshots vía API."""
    import security_vision_worker.main as wmain

    admin = await login(client)
    good1 = await _create(client, admin, name="A", source_type="test", source_uri="testpattern://?fps=20",
                          analysis_fps=2)
    good2 = await _create(client, admin, name="B", source_type="test", source_uri="testpattern://?fps=20")
    dead = await _create(client, admin, name="C", source_type="test", source_uri="testpattern://?fail_connect=1")

    runtime, engine, bus = wmain.build_runtime(settings)
    runtime.supervisor._policy = ReconnectPolicy(initial_delay=0.1, max_delay=0.5)
    runtime.loop = asyncio.get_running_loop()
    tasks = [asyncio.create_task(runtime.status_writer()), asyncio.create_task(runtime.snapshot_writer()),
             asyncio.create_task(runtime.config_listener())]
    try:
        await runtime.reconcile()
        await asyncio.sleep(3)
        cams = {c["name"]: c for c in (await client.get("/api/v1/cameras", headers=auth(admin))).json()}
        assert cams["A"]["status"] == "streaming" and cams["B"]["status"] == "streaming"
        assert cams["C"]["status"] == "reconnecting" and "rechazada" in (cams["C"]["last_error"] or "")
        w = runtime.supervisor.workers()
        assert w[good1["id"]].stats.frames > 30 and w[good2["id"]].stats.frames > 30
        assert w[dead["id"]].stats.connection_errors >= 3
        a = runtime.analysis[good1["id"]].stats
        assert 3 <= a.analyzed <= 8  # ~2/s durante ~3 s: el análisis va a su ritmo
        assert a.frame_age_ewma < 0.5  # siempre toma un fotograma reciente
        snap = await client.get(f"/api/v1/cameras/{good1['id']}/snapshot", headers=auth(admin))
        assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
        assert (await client.get(f"/api/v1/cameras/{dead['id']}/snapshot", headers=auth(admin))).status_code == 404

        # Alta por API -> NOTIFY -> el worker la arranca sin reiniciar.
        new = await _create(client, admin, name="D", source_type="test", source_uri="testpattern://?fps=10")
        for _ in range(30):
            if new["id"] in runtime.supervisor.workers():
                break
            await asyncio.sleep(0.2)
        assert new["id"] in runtime.supervisor.workers()
        # Deshabilitar por API -> el worker la detiene.
        await client.patch(f"/api/v1/cameras/{good2['id']}", headers=auth(admin), json={"enabled": False})
        for _ in range(30):
            if good2["id"] not in runtime.supervisor.workers():
                break
            await asyncio.sleep(0.2)
        assert good2["id"] not in runtime.supervisor.workers()
        async with engine.begin() as conn:  # type: ignore[attr-defined]
            n = (await conn.execute(text("SELECT count(*) FROM camera_status_events"))).scalar_one()
        assert n >= 4
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.to_thread(runtime.shutdown)
        await bus.close()
        await engine.dispose()  # type: ignore[attr-defined]


# --- MediaMTX real ----------------------------------------------------------------------

def _mediamtx_exe() -> Path | None:
    base = Path(os.environ.get("SV_MEDIAMTX_HOME", Path(os.environ.get("LOCALAPPDATA", "")) / "security-vision"
                               / "mediamtx"))
    exe = base / ("mediamtx.exe" if sys.platform.startswith("win") else "mediamtx")
    return exe if exe.exists() else (Path(shutil.which("mediamtx")) if shutil.which("mediamtx") else None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mediamtx(tmp_path):
    exe = _mediamtx_exe()
    if exe is None:
        pytest.skip("MediaMTX no instalado (ver docs/installation/local-windows.md)")
    from dev_mediamtx import render_config

    ports = {"rtsp": _free_port(), "webrtc": _free_port(), "api": _free_port(), "ice": _free_port()}
    cfg = tmp_path / "mtx.yml"
    cfg.write_text(render_config(rtsp_port=ports["rtsp"], webrtc_port=ports["webrtc"], api_port=ports["api"],
                                 ice_udp_port=ports["ice"], publish_user="pub", publish_pwd="pub-pass",
                                 api_user="api", api_pwd="api-pass", auth="internal"), encoding="utf-8")
    # cwd temporal: MediaMTX no debe dejar archivos (p. ej. certificados) en el repositorio
    proc = subprocess.Popen([str(exe), str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tmp_path)
    try:
        for _ in range(50):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", ports["api"])) == 0:
                    break
            time.sleep(0.1)
        yield ports
    finally:
        proc.terminate()
        proc.wait(5)


async def test_mediamtx_publish_proxy_and_read(mediamtx):
    """Cadena RTSP real: publicador (cámara simulada) -> MediaMTX -> ruta proxy -> lector PyAV."""
    from security_vision.infrastructure.video.mediamtx import MediaMtxServer
    from security_vision.plugins.video_sources.pyav_publisher import PyAVRtspPublisher
    from security_vision.plugins.video_sources.pyav_source import PyAVVideoSource
    from security_vision.plugins.video_sources.test_pattern import TestPatternSource

    p = mediamtx
    rtsp = f"rtsp://127.0.0.1:{p['rtsp']}"
    media = MediaMtxServer(f"http://127.0.0.1:{p['api']}", rtsp, f"http://127.0.0.1:{p['webrtc']}", "api", "api-pass")
    try:
        await media.ensure_path("simcam", None)  # ruta de publicación = "cámara IP" simulada
        await media.ensure_path("cam-proxy", f"{rtsp}/simcam")  # proxy, como con una cámara RTSP real
        await media.ensure_path("cam-proxy", f"{rtsp}/simcam")  # idempotente (PATCH)

        stop = asyncio.Event()

        def publish() -> str | None:
            src = TestPatternSource(VideoSourceConfig(uri="testpattern://?width=640&height=360&fps=15"))
            src.connect()
            pub = PyAVRtspPublisher(f"{rtsp}/simcam", 15, "pub", "pub-pass")
            try:
                while not stop.is_set():
                    pub.publish(src.read_frame(1.0))
            finally:
                pub.close()
            return pub.encoder

        pub_task = asyncio.create_task(asyncio.to_thread(publish))
        await asyncio.sleep(2.5)

        def read(url: str) -> tuple[int, int, int]:
            s = PyAVVideoSource(VideoSourceConfig(uri=url, options={"open_timeout": 5, "read_timeout": 5}))
            s.connect()
            frames = [s.read_frame(5) for _ in range(20)]
            s.disconnect()
            return len(frames), frames[-1].width, frames[-1].height

        assert await asyncio.to_thread(read, f"{rtsp}/simcam") == (20, 640, 360)
        assert await asyncio.to_thread(read, f"{rtsp}/cam-proxy") == (20, 640, 360)
        names = {x["name"] for x in await media.list_paths()}
        assert {"simcam", "cam-proxy"} <= names
        await media.remove_path("cam-proxy")
        stop.set()
        encoder = await pub_task
        assert encoder in ("h264_nvenc", "h264_qsv", "h264_mf", "libvpx")  # nunca libx264
    finally:
        await media.close()


async def test_mediamtx_rejects_anonymous_publish(mediamtx):
    from security_vision.plugins.video_sources.pyav_publisher import PyAVRtspPublisher
    from security_vision.plugins.video_sources.test_pattern import TestPatternSource

    src = TestPatternSource(VideoSourceConfig(uri="testpattern://?width=64&height=64"))
    src.connect()
    pub = PyAVRtspPublisher(f"rtsp://127.0.0.1:{mediamtx['rtsp']}/intruso", 10)
    with pytest.raises(Exception):  # noqa: B017 - FFmpeg devuelve 401 como error genérico
        for _ in range(5):
            pub.publish(src.read_frame(1))
    pub.close()


_ = ADMIN_PASSWORD
