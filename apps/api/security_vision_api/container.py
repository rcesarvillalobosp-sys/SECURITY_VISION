"""Raíz de composición: el único lugar que conoce las implementaciones concretas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from security_vision.core.configuration.settings import Settings
from security_vision.infrastructure.database.session import create_engine, uow_factory
from security_vision.infrastructure.monitoring.metrics import ApiMetrics, create_api_metrics
from security_vision.infrastructure.security.adapters import AesGcmCipher, Argon2PasswordHasher, JwtTokenService
from security_vision.modules.users.services import AuthPolicy, AuthService, UserService


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    auth: AuthService
    users: UserService
    hasher: Argon2PasswordHasher
    cipher: AesGcmCipher
    metrics: ApiMetrics

    async def close(self) -> None:
        await self.engine.dispose()


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings.database_url.get_secret_value(), pool_size=settings.database_pool_size,
                           echo=settings.database_echo)
    uow = uow_factory(engine)
    hasher = Argon2PasswordHasher()
    tokens = JwtTokenService(settings.jwt_secret.get_secret_value(), settings.jwt_issuer)
    policy = AuthPolicy(access_token_ttl=timedelta(minutes=settings.access_token_minutes),
                        refresh_token_ttl=timedelta(days=settings.refresh_token_days),
                        max_failed_logins=settings.max_failed_logins,
                        lockout=timedelta(minutes=settings.lockout_minutes))
    return Container(settings=settings, engine=engine, auth=AuthService(uow, hasher, tokens, policy),
                     users=UserService(uow, hasher), hasher=hasher,
                     cipher=AesGcmCipher(settings.secrets_key.get_secret_value()), metrics=create_api_metrics())
