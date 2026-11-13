"""Raíz de composición: el único lugar que conoce las implementaciones concretas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from security_vision.composition import build_media, build_storage, build_video_registry, camera_policy
from security_vision.core.configuration.settings import Settings
from security_vision.core.interfaces.cameras import MediaServer
from security_vision.infrastructure.database.session import create_engine, uow_factory
from security_vision.infrastructure.messaging.postgres_bus import PostgresMessageBus
from security_vision.infrastructure.monitoring.metrics import ApiMetrics, create_api_metrics
from security_vision.infrastructure.security.adapters import AesGcmCipher, Argon2PasswordHasher, JwtTokenService
from security_vision.infrastructure.storage.local import LocalFileStorage
from security_vision.infrastructure.video.probe import RegistryVideoProbe
from security_vision.modules.cameras.service import CameraService
from security_vision.modules.incidents.service import IncidentService
from security_vision.modules.security_rules.service import RulesService
from security_vision.modules.users.services import AuthPolicy, AuthService, UserService

from .live import LiveHub


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    auth: AuthService
    users: UserService
    cameras: CameraService
    rules: RulesService
    incidents: IncidentService
    hasher: Argon2PasswordHasher
    cipher: AesGcmCipher
    storage: LocalFileStorage
    bus: PostgresMessageBus
    media: MediaServer | None
    metrics: ApiMetrics
    tokens: JwtTokenService | None = None
    live: LiveHub | None = None

    def auth_token_expiry(self, token: str):
        assert self.tokens is not None
        return self.tokens.decode_access_token(token).expires_at

    async def audit_evidence(self, user_id, incident_id, key: str, ip: str | None, tampered: bool = False) -> None:
        from security_vision.infrastructure.database.session import uow_factory

        async with uow_factory(self.engine)() as uow:
            await uow.audit.record("evidence.integrity_failed" if tampered else "evidence.viewed", actor_id=user_id,
                                   entity_type="incident", entity_id=str(incident_id), after={"key": key}, ip=ip)
            await uow.commit()

    async def close(self) -> None:
        await self.bus.close()
        if self.media is not None and hasattr(self.media, "close"):
            await self.media.close()
        await self.engine.dispose()


def build_container(settings: Settings) -> Container:
    db_url = settings.database_url.get_secret_value()
    engine = create_engine(db_url, pool_size=settings.database_pool_size, echo=settings.database_echo)
    uow = uow_factory(engine)
    hasher = Argon2PasswordHasher()
    tokens = JwtTokenService(settings.jwt_secret.get_secret_value(), settings.jwt_issuer)
    policy = AuthPolicy(access_token_ttl=timedelta(minutes=settings.access_token_minutes),
                        refresh_token_ttl=timedelta(days=settings.refresh_token_days),
                        max_failed_logins=settings.max_failed_logins,
                        lockout=timedelta(minutes=settings.lockout_minutes))
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    storage = build_storage(settings)
    bus = PostgresMessageBus(db_url)
    media = build_media(settings)
    from security_vision.infrastructure.video.mediamtx import path_name

    cameras = CameraService(uow, cipher, RegistryVideoProbe(build_video_registry()), storage,
                            camera_policy(settings), bus=bus, media=media, media_path_for=path_name)
    return Container(settings=settings, engine=engine, auth=AuthService(uow, hasher, tokens, policy),
                     users=UserService(uow, hasher), cameras=cameras, rules=RulesService(uow, bus),
                     incidents=IncidentService(uow, storage),
                     hasher=hasher, cipher=cipher,
                     storage=storage, bus=bus, media=media, metrics=create_api_metrics(), tokens=tokens,
                     live=LiveHub(bus))
