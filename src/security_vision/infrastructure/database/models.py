"""Modelo relacional (SQLAlchemy 2). Ver docs/architecture/02-modelo-datos.md.

Fase 1 crea: identidad (usuarios, roles, permisos, sesiones), auditoría, sitios, cámaras,
zonas, perfiles de seguridad, modelos de IA y políticas de retención. Incidentes,
evidencias y estadísticas llegan en sus fases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from security_vision.core.domain.ids import uuid7

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


def pk() -> Mapped[UUID]:
    return mapped_column(primary_key=True, default=uuid7)


# --- identidad -------------------------------------------------------------------

class UserRow(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[UUID] = pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)


class RoleRow(Timestamps, Base):
    __tablename__ = "roles"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class PermissionRow(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)


class RolePermissionRow(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code", ondelete="CASCADE"),
                                                 primary_key=True)


class UserRoleRow(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64))
    previous_refresh_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLogRow(Base):
    """Solo inserción: un trigger en la migración impide UPDATE y DELETE."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    ip: Mapped[str | None] = mapped_column(String(64))


# --- operación -------------------------------------------------------------------

class SiteRow(Timestamps, Base):
    __tablename__ = "sites"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")


class RetentionPolicyRow(Timestamps, Base):
    __tablename__ = "retention_policies"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    evidences_days: Mapped[int] = mapped_column(Integer, default=90)
    observations_days: Mapped[int] = mapped_column(Integer, default=14)
    recordings_days: Mapped[int] = mapped_column(Integer, default=7)
    __table_args__ = (
        CheckConstraint("evidences_days > 0 AND observations_days > 0 AND recordings_days > 0", name="positive"),
    )


class SecurityProfileRow(Timestamps, Base):
    __tablename__ = "security_profiles"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    required_ppe: Mapped[list[Any]] = mapped_column(default=list)
    thresholds: Mapped[dict[str, Any]] = mapped_column(default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class DetectionModelRow(Timestamps, Base):
    __tablename__ = "detection_models"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    architecture: Mapped[str] = mapped_column(String(50))
    task: Mapped[str] = mapped_column(String(50), default="detection")
    classes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    artifact_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    input_spec: Mapped[dict[str, Any]] = mapped_column(default=dict)
    license: Mapped[str] = mapped_column(String(100))
    weights_license: Mapped[str] = mapped_column(String(100))
    dataset_ref: Mapped[str | None] = mapped_column(String(200))
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="registered")
    __table_args__ = (UniqueConstraint("name", "version", name="uq_detection_models_name_version"),)


class CameraRow(Timestamps, Base):
    __tablename__ = "cameras"
    id: Mapped[UUID] = pk()
    site_id: Mapped[UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(32))  # resuelto por el registro de plugins
    source_uri: Mapped[str] = mapped_column(String(1000))  # nunca contiene credenciales
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    target_fps: Mapped[float | None] = mapped_column(Float)
    analysis_fps: Mapped[float] = mapped_column(Float, default=2.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_id: Mapped[UUID | None] = mapped_column(ForeignKey("detection_models.id", ondelete="SET NULL"))
    default_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("security_profiles.id", ondelete="SET NULL"))
    retention_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("retention_policies.id", ondelete="SET NULL"))
    location: Mapped[dict[str, Any]] = mapped_column(default=dict)
    mediamtx_path: Mapped[str | None] = mapped_column(String(200))
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_cameras_site_name", postgresql_nulls_not_distinct=True),
        CheckConstraint("analysis_fps > 0 AND analysis_fps <= 60", name="analysis_fps_range"),
        CheckConstraint("source_uri !~ '://[^/@]+@'", name="no_credentials_in_uri"),
    )


class CameraStatusEventRow(Base):
    """Historial de conectividad por cámara (se purga según retención)."""

    __tablename__ = "camera_status_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    camera_id: Mapped[UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(500))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_camera_status_events_camera_at", "camera_id", "at"),)


class ZoneRow(Timestamps, Base):
    __tablename__ = "zones"
    id: Mapped[UUID] = pk()
    camera_id: Mapped[UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="ppe")
    polygon: Mapped[list[Any]] = mapped_column()
    profile_id: Mapped[UUID | None] = mapped_column(ForeignKey("security_profiles.id", ondelete="SET NULL"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (Index("ix_zones_camera_id", "camera_id"),
                      UniqueConstraint("camera_id", "name", name="uq_zones_camera_name"))


# --- incidentes y evidencias ------------------------------------------------------------

class IncidentRow(Timestamps, Base):
    """Incumplimiento confirmado por el motor de reglas, sujeto a revisión humana."""

    __tablename__ = "incidents"
    id: Mapped[UUID] = pk()
    source_event_id: Mapped[UUID] = mapped_column(unique=True)  # idempotencia
    camera_id: Mapped[UUID | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    camera_name: Mapped[str] = mapped_column(String(200))  # instantánea: el incidente sobrevive a la cámara
    zone_id: Mapped[UUID | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"))
    profile_id: Mapped[UUID | None] = mapped_column(ForeignKey("security_profiles.id", ondelete="SET NULL"))
    profile_version: Mapped[int | None] = mapped_column(Integer)
    track_id: Mapped[int] = mapped_column(Integer)
    violation_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PENDIENTE")
    confidence: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    __table_args__ = (
        Index("ix_incidents_confirmed_at", "confirmed_at"),
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_camera_confirmed", "camera_id", "confirmed_at"),
        CheckConstraint("status IN ('PENDIENTE','EN_REVISION','CONFIRMADO','DESCARTADO','RESUELTO')",
                        name="status_valid"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class EvidenceRow(Base):
    __tablename__ = "evidences"
    id: Mapped[UUID] = pk()
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # frame | annotated | crop | context
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    frame_id: Mapped[int | None] = mapped_column(BigInteger)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DetectionRow(Base):
    """Detecciones persistidas: las de los fotogramas de evidencia (no todas las de cada fotograma)."""

    __tablename__ = "detections"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidences.id", ondelete="SET NULL"))
    camera_id: Mapped[UUID] = mapped_column()
    track_id: Mapped[int | None] = mapped_column(Integer)
    class_name: Mapped[str] = mapped_column(String(64))
    bbox: Mapped[list[Any]] = mapped_column()  # [x1, y1, x2, y2] normalizado
    confidence: Mapped[float] = mapped_column(Float)
    frame_id: Mapped[int] = mapped_column(BigInteger)
    frame_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_id: Mapped[str] = mapped_column(String(120))
    inference_ms: Mapped[float] = mapped_column(Float)


class IncidentHistoryRow(Base):
    __tablename__ = "incident_history"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32))  # created | status_changed | ended | commented
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IncidentCommentRow(Base):
    __tablename__ = "incident_comments"
    id: Mapped[UUID] = pk()
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxRow(Base):
    """Eventos escritos en la misma transacción que el cambio; un relé los publica (al menos una vez)."""

    __tablename__ = "event_outbox"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("ix_event_outbox_pending", "id", postgresql_where="published_at IS NULL"),)


class CameraStatsRow(Base):
    """Agregados por cámara y minuto (fotogramas-persona): base del panel y de los reportes."""

    __tablename__ = "camera_stats"
    camera_id: Mapped[UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)  # inicio del minuto
    analyzed_frames: Mapped[int] = mapped_column(Integer, default=0)
    person_frames: Mapped[int] = mapped_column(Integer, default=0)  # suma de personas por fotograma
    max_persons: Mapped[int] = mapped_column(Integer, default=0)
    compliant: Mapped[int] = mapped_column(Integer, default=0)
    in_review: Mapped[int] = mapped_column(Integer, default=0)
    possible: Mapped[int] = mapped_column(Integer, default=0)
    confirmed: Mapped[int] = mapped_column(Integer, default=0)
    unverifiable: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("ix_camera_stats_bucket", "bucket"),)
