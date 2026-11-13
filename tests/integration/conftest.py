"""Tests de integración contra PostgreSQL REAL (SV_TEST_DATABASE_URL, nunca la BD de desarrollo).

Se omiten (skip) con un motivo explícito si no hay base de datos de pruebas disponible.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from security_vision.core.configuration.settings import Settings
from security_vision.infrastructure.security.adapters import AesGcmCipher

ROOT = Path(__file__).resolve().parents[2]
ADMIN_EMAIL = "admin@test.local"
ADMIN_PASSWORD = "Admin-Pruebas-2026!"
TABLES = "audit_log, sessions, user_roles, users, zones, cameras, sites, security_profiles, detection_models, " \
         "retention_policies, event_outbox, system_settings, alert_channels"


def _test_db_url() -> str | None:
    if url := os.environ.get("SV_TEST_DATABASE_URL"):
        return url
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SV_TEST_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _test_db_url()
    if not url:
        pytest.skip("SV_TEST_DATABASE_URL no definido (ver scripts/dev_postgres.py)")
    if not url.rstrip("/").endswith("_test"):
        pytest.fail("la URL de pruebas debe apuntar a una base de datos *_test")

    async def reachable() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except OSError:
            return False
        finally:
            await engine.dispose()

    if not asyncio.run(reachable()):
        pytest.skip("PostgreSQL de pruebas no accesible (uv run python scripts/dev_postgres.py start)")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
def settings(db_url: str) -> Settings:
    return Settings(_env_file=None, environment="test", log_json=False, database_url=db_url,
                    jwt_secret="t" * 48, secrets_key=AesGcmCipher.generate_key(), max_failed_logins=3,
                    bootstrap_admin_email=ADMIN_EMAIL, bootstrap_admin_password=ADMIN_PASSWORD)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    from security_vision.modules.users.services import bootstrap
    from security_vision_api.container import build_container
    from security_vision_api.main import create_app

    container = build_container(settings)
    async with container.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    from security_vision.infrastructure.database.session import uow_factory

    await bootstrap(uow_factory(container.engine), container.hasher, ADMIN_EMAIL, ADMIN_PASSWORD)
    app = create_app(settings, container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def login(c: httpx.AsyncClient, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> str:
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
