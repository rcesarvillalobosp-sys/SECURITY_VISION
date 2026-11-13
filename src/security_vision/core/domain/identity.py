"""Identidad y control de acceso: usuarios, roles, permisos y sesiones."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Permission(StrEnum):
    """Catálogo de permisos. Añadir un permiso aquí lo sincroniza en la BD (svctl bootstrap)."""

    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    ROLES_READ = "roles:read"
    AUDIT_READ = "audit:read"
    CAMERAS_READ = "cameras:read"
    CAMERAS_WRITE = "cameras:write"
    ZONES_WRITE = "zones:write"
    RULES_WRITE = "rules:write"
    MODELS_WRITE = "models:write"
    INCIDENTS_READ = "incidents:read"
    INCIDENTS_REVIEW = "incidents:review"
    REPORTS_READ = "reports:read"
    ALERTS_WRITE = "alerts:write"
    SYSTEM_ADMIN = "system:admin"


P = Permission
DEFAULT_ROLES: dict[str, tuple[str, frozenset[Permission]]] = {
    "admin": ("Administración completa", frozenset(Permission)),
    "supervisor": ("Supervisión de seguridad y configuración operativa", frozenset({
        P.USERS_READ, P.ROLES_READ, P.CAMERAS_READ, P.CAMERAS_WRITE, P.ZONES_WRITE, P.RULES_WRITE,
        P.INCIDENTS_READ, P.INCIDENTS_REVIEW, P.REPORTS_READ, P.ALERTS_WRITE, P.AUDIT_READ,
    })),
    "operator": ("Monitoreo y revisión de incidentes", frozenset({
        P.CAMERAS_READ, P.INCIDENTS_READ, P.INCIDENTS_REVIEW, P.REPORTS_READ,
    })),
    "viewer": ("Solo lectura", frozenset({P.CAMERAS_READ, P.INCIDENTS_READ, P.REPORTS_READ})),
}


@dataclass(slots=True)
class User:
    id: UUID
    email: str
    display_name: str
    password_hash: str
    is_active: bool
    roles: list[str] = field(default_factory=list)
    failed_logins: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class AuthSession:
    id: UUID
    user_id: UUID
    refresh_token_hash: str
    previous_refresh_hash: str | None
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip: str | None = None


@dataclass(frozen=True, slots=True)
class Principal:
    """Usuario autenticado en el contexto de una petición."""

    user_id: UUID
    session_id: UUID
    email: str
    roles: frozenset[str]
    permissions: frozenset[str]

    def can(self, permission: Permission | str) -> bool:
        return str(permission) in self.permissions
