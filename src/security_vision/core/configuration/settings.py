"""Configuración por variables de entorno (prefijo ``SV_``) y archivo ``.env``.

Los secretos son ``SecretStr``: no aparecen en logs ni en ``repr``. En producción la
aplicación se niega a arrancar con secretos de ejemplo o débiles.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_MARKERS = ("change-me", "changeme", "example", "secret")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SV_", env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True

    database_url: SecretStr = SecretStr("postgresql+asyncpg://security_vision@localhost:5433/security_vision")
    database_pool_size: int = 10
    database_echo: bool = False

    jwt_secret: SecretStr = Field(min_length=32)
    jwt_issuer: str = "security-vision"
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=90)

    # Clave AES-256-GCM (base64 url-safe de 32 bytes) para secretos en reposo (credenciales RTSP).
    secrets_key: SecretStr

    max_failed_logins: int = 5
    lockout_minutes: int = 15

    cors_origins: list[str] = ["http://localhost:5173"]

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment is Environment.PRODUCTION:
            for name in ("jwt_secret", "secrets_key"):
                value = getattr(self, name).get_secret_value().lower()
                if any(m in value for m in INSECURE_MARKERS):
                    raise ValueError(f"SV_{name.upper()} parece un valor de ejemplo")
            if "*" in self.cors_origins:
                raise ValueError("CORS '*' no permitido en producción")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
