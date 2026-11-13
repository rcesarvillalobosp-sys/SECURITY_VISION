"""``sv-worker``: proceso de captura (y, desde la Fase 3, de análisis) de las cámaras habilitadas."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from prometheus_client import start_http_server

from security_vision.composition import (
    build_detection_service,
    build_media,
    build_retention,
    build_storage,
    build_tracking,
    build_video_registry,
    camera_policy,
)
from security_vision.core.configuration.settings import Settings, get_settings
from security_vision.core.interfaces.video import VideoPublisher
from security_vision.infrastructure.database.session import create_engine, uow_factory
from security_vision.infrastructure.messaging.outbox import OutboxRelay
from security_vision.infrastructure.messaging.postgres_bus import PostgresMessageBus
from security_vision.infrastructure.monitoring.logging import configure_logging
from security_vision.infrastructure.security.adapters import AesGcmCipher
from security_vision.modules.incidents.service import IncidentService

from .metrics import build_registry
from .runtime import WorkerRuntime

log = logging.getLogger("security_vision.worker")


def build_runtime(settings: Settings) -> tuple[WorkerRuntime, object, PostgresMessageBus]:
    db_url = settings.database_url.get_secret_value()
    engine = create_engine(db_url, pool_size=3)
    bus = PostgresMessageBus(db_url)
    media = build_media(settings)
    publisher_factory = None
    if media is not None:
        from security_vision.plugins.video_sources.pyav_publisher import PyAVRtspPublisher

        user = settings.mediamtx_publish_user
        pwd = settings.mediamtx_publish_password.get_secret_value() if settings.mediamtx_publish_password else None

        def publisher_factory(url: str, fps: float) -> VideoPublisher:
            return PyAVRtspPublisher(url, fps, user, pwd)

    tracker_factory, associator = build_tracking(settings)
    uow = uow_factory(engine)
    storage = build_storage(settings)
    runtime = WorkerRuntime(uow=uow, cipher=AesGcmCipher(settings.secrets_key.get_secret_value()),
                            registry=build_video_registry(), storage=storage,
                            policy=camera_policy(settings), bus=bus, media=media,
                            publisher_factory=publisher_factory, snapshot_seconds=settings.worker_snapshot_seconds,
                            tracker_factory=tracker_factory, associator=associator,
                            incidents=IncidentService(uow, storage),
                            model_loader=lambda mid: build_detection_service(settings, mid),
                            default_model=settings.detection_model, engine_name=settings.inference_engine)
    return runtime, engine, bus


async def _daily_retention(settings: Settings, engine: object) -> None:
    service = build_retention(settings, engine)  # type: ignore[arg-type]
    while True:
        try:
            await service.purge()
        except Exception:
            log.exception("purga de retención falló")
        await asyncio.sleep(24 * 3600)


async def run(settings: Settings) -> None:
    runtime, engine, bus = build_runtime(settings)
    runtime.loop = asyncio.get_running_loop()
    start_http_server(settings.worker_metrics_port, addr="127.0.0.1", registry=build_registry(runtime))
    log.info("worker iniciado; métricas en http://127.0.0.1:%d/metrics", settings.worker_metrics_port)
    await runtime.ensure_model()  # modelo activo (ajuste de la administración o SV_DETECTION_MODEL)
    await runtime.reconcile()
    tasks = [asyncio.create_task(c) for c in (
        runtime.status_writer(), runtime.snapshot_writer(), runtime.config_listener(), runtime.event_publisher(),
        runtime.incident_writer(), OutboxRelay(engine, bus).run_forever(),  # type: ignore[arg-type]
        runtime.live_publisher(), runtime.stats_flusher(engine),
        _daily_retention(settings, engine),
        runtime.periodic_reconcile(settings.worker_reconcile_seconds))]
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, AttributeError):  # Windows no soporta add_signal_handler
            runtime.loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.to_thread(runtime.shutdown)
        await bus.close()
        await engine.dispose()  # type: ignore[attr-defined]
        if runtime.media is not None and hasattr(runtime.media, "close"):
            await runtime.media.close()
        log.info("worker detenido")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
