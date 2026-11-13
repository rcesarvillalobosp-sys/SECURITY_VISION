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

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Redes desde las que se puede leer /metrics de la API (Prometheus). Fuera de ellas: 404.
    metrics_allowed_networks: list[str] = ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12",
                                           "192.168.0.0/16"]
    web_dist: str | None = None  # p. ej. apps/web/dist: la API sirve el frontend compilado

    # Vídeo y almacenamiento
    video_provider: str = "pyav"  # adaptador VideoSource por defecto (pyav | gstreamer)
    allow_test_sources: bool = False  # fuentes testpattern:// (solo desarrollo)
    video_files_dir: str | None = None  # raíz permitida para cámaras de tipo archivo
    storage_dir: str = "var/storage"
    camera_probe_timeout: float = Field(default=15.0, ge=1, le=120)

    # MediaMTX (opcional). Vacío = sin servidor de medios.
    mediamtx_api_url: str | None = None  # p. ej. http://127.0.0.1:9997
    mediamtx_rtsp_url: str = "rtsp://127.0.0.1:8554"
    mediamtx_webrtc_url: str = "http://127.0.0.1:8889"
    mediamtx_api_user: str | None = None
    mediamtx_api_password: SecretStr | None = None
    mediamtx_publish_user: str | None = None
    mediamtx_publish_password: SecretStr | None = None
    # Autenticación HTTP de MediaMTX contra la API (lectura desde otros equipos con el token de sesión).
    # Clave compartida que MediaMTX envía en la URL de autenticación. Vacío = endpoint desactivado.
    mediamtx_auth_key: SecretStr | None = None

    # Inferencia (criterios 13 y 14: modelo y motor se cambian solo por configuración)
    detection_model: str | None = None  # "nombre@versión" del registro de modelos; vacío = sin detección
    inference_engine: str = "onnxruntime"  # onnxruntime | openvino
    inference_devices: list[str] = ["cuda", "cpu"]  # preferencia con respaldo explícito
    model_registry_dir: str = "ml/model_registry"
    tracker: str = "bytetrack"
    tracker_max_lost_seconds: float = Field(default=3.0, gt=0, le=60)

    # Retención (días)
    retention_evidences_days: int = Field(default=90, ge=1, le=3650)
    retention_status_events_days: int = Field(default=30, ge=1, le=3650)

    # Worker de procesamiento
    worker_metrics_port: int = 9101
    worker_metrics_host: str = "127.0.0.1"  # 0.0.0.0 solo en una red privada (p. ej. la del compose)
    worker_reconcile_seconds: float = 30.0
    worker_snapshot_seconds: float = 5.0

    # Trazas OpenTelemetry (opcional): OTLP/HTTP, p. ej. http://127.0.0.1:4318. Vacío = desactivadas.
    otel_endpoint: str | None = None
    otel_sample_ratio: float = Field(default=0.1, ge=0, le=1)  # fracción de fotogramas/peticiones trazadas
    # Micro-batching de la detección (Fase 9)
    detection_max_batch: int = Field(default=4, ge=1, le=32)
    detection_max_wait_ms: float = Field(default=0.0, ge=0, le=100)

    # Alertas externas
    public_web_url: str | None = None  # p. ej. https://seguridad.ejemplo.com: enlaces en las alertas
    alerts_enabled: bool = True  # despachador de alertas en el proceso de la API
    alert_webhook_allow_private: bool = False  # permitir webhooks a IPs privadas/locales (riesgo SSRF)
    alert_webhook_timeout: float = Field(default=10.0, gt=0, le=60)
    smtp_host: str | None = None  # vacío = canal email deshabilitado
    smtp_port: int = 587
    smtp_security: str = Field(default="starttls", pattern="^(starttls|ssl|none)$")
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_timeout: float = Field(default=15.0, gt=0, le=120)

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
            if self.allow_test_sources:
                raise ValueError("SV_ALLOW_TEST_SOURCES no se permite en producción")
            if self.smtp_host and self.smtp_security == "none":
                raise ValueError("SMTP sin cifrar no se permite en producción")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
