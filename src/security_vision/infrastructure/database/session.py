"""Motor asíncrono y unidad de trabajo sobre SQLAlchemy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from security_vision.core.interfaces.repositories import UnitOfWork

from .repositories.cameras import SqlCameraRepository
from .repositories.identity import SqlAuditLog, SqlRoleRepository, SqlSessionRepository, SqlUserRepository


def create_engine(url: str, *, pool_size: int = 10, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True, echo=echo)


async def ping(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


class SqlUnitOfWork(UnitOfWork):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self._session = self._sessionmaker()
        self.users = SqlUserRepository(self._session)
        self.roles = SqlRoleRepository(self._session)
        self.sessions = SqlSessionRepository(self._session)
        self.audit = SqlAuditLog(self._session)
        self.cameras = SqlCameraRepository(self._session)
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._session is not None
        if exc and exc[0] is not None:
            await self._session.rollback()
        await self._session.close()
        self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


def uow_factory(engine: AsyncEngine) -> Callable[[], SqlUnitOfWork]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return lambda: SqlUnitOfWork(maker)
