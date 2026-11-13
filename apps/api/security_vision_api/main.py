"""Aplicación FastAPI."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from security_vision.core.configuration.settings import Environment, Settings, get_settings
from security_vision.core.domain.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from security_vision.infrastructure.monitoring.logging import configure_logging, request_id_var

from .container import Container, build_container
from .routers import admin, auth, cameras, dashboard, incidents, media, reports, rules, system, users

log = logging.getLogger("security_vision.api")

ERROR_STATUS: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        from security_vision.infrastructure.messaging.outbox import OutboxRelay

        relay = asyncio.create_task(OutboxRelay(app.state.container.engine, app.state.container.bus).run_forever())
        alerts_task = None
        if settings.alerts_enabled and app.state.container.dispatcher is not None:
            alerts_task = asyncio.create_task(app.state.container.dispatcher.run_forever())
        if app.state.container.live is not None:
            app.state.container.live.start()
        log.info("API iniciada", extra={"environment": settings.environment.value})
        yield
        relay.cancel()
        if alerts_task is not None:
            alerts_task.cancel()
        if app.state.container.live is not None:
            await app.state.container.live.stop()
        await app.state.container.close()

    app = FastAPI(
        title="Security Vision API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.environment is Environment.PRODUCTION else "/docs",
        redoc_url=None,
    )
    from security_vision.infrastructure.monitoring.tracing import instrument_fastapi, setup_tracing

    if setup_tracing("security-vision-api", settings.otel_endpoint, settings.otel_sample_ratio):
        instrument_fastapi(app)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"])

    @app.middleware("http")
    async def observe(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid[:64])
        metrics = request.app.state.container.metrics
        metrics.in_flight.inc()
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            metrics.in_flight.dec()
            route = request.scope.get("route")
            label = getattr(route, "path", "unmatched")  # plantilla de ruta: cardinalidad acotada
            metrics.requests.labels(request.method, label, str(status_code)).inc()
            metrics.latency.labels(request.method, label).observe(time.perf_counter() - start)
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid[:64]
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        code = next((c for t, c in ERROR_STATUS.items() if isinstance(exc, t)), status.HTTP_400_BAD_REQUEST)
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=code)

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(cameras.router)
    app.include_router(rules.router)
    app.include_router(incidents.router)
    app.include_router(dashboard.router)
    app.include_router(admin.router)
    app.include_router(reports.router)
    app.include_router(media.router)
    _mount_web(app, settings)
    return app


def _mount_web(app: FastAPI, settings: Settings) -> None:
    """Sirve el frontend compilado (mismo origen que la API) si SV_WEB_DIST apunta a apps/web/dist."""
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = Path(settings.web_dist) if settings.web_dist else None
    if not dist or not (dist / "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith(("api/", "health/", "metrics")):
            from fastapi import HTTPException

            raise HTTPException(status.HTTP_404_NOT_FOUND)  # una ruta de API inexistente no devuelve la SPA
        target = (dist / path).resolve()
        if path and target.is_file() and target.is_relative_to(dist.resolve()):
            return FileResponse(target)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


def app_factory() -> FastAPI:
    """Punto de entrada para uvicorn: ``uvicorn security_vision_api.main:app_factory --factory``."""
    return create_app()
