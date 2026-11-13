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
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_cameras_site_name", postgresql_nulls_not_distinct=True),
        CheckConstraint("analysis_fps > 0 AND analysis_fps <= 60", name="analysis_fps_range"),
        CheckConstraint("source_uri !~ '://[^/@]+@'", name="no_credentials_in_uri"),
    )


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
