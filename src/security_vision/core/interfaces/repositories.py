"""Puertos de persistencia usados por los módulos de negocio."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from ..domain.compliance import CameraRules, SecurityProfile, ZoneRule
from ..domain.identity import AuthSession, User
from .cameras import CameraRepository
from .incidents import IncidentRepository


class UserRepository(ABC):
    @abstractmethod
    async def get(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def list(self, offset: int = 0, limit: int = 50) -> list[User]: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def add(self, user: User) -> None: ...

    @abstractmethod
    async def update(self, user: User) -> None: ...

    @abstractmethod
    async def set_roles(self, user_id: UUID, roles: Sequence[str]) -> None: ...

    @abstractmethod
    async def permissions_for(self, user_id: UUID) -> frozenset[str]: ...


class RoleRepository(ABC):
    @abstractmethod
    async def sync(self, roles: Mapping[str, tuple[str, frozenset[str]]], permissions: Sequence[str]) -> None:
        """Crea/actualiza roles y permisos por defecto de forma idempotente."""

    @abstractmethod
    async def list(self) -> list[tuple[str, str, list[str]]]: ...

    @abstractmethod
    async def existing(self, names: Sequence[str]) -> set[str]: ...


class SessionRepository(ABC):
    @abstractmethod
    async def add(self, session: AuthSession) -> None: ...

    @abstractmethod
    async def get(self, session_id: UUID) -> AuthSession | None: ...

    @abstractmethod
    async def update(self, session: AuthSession) -> None: ...

    @abstractmethod
    async def revoke_all_for_user(self, user_id: UUID, at: datetime) -> int: ...


class AuditLog(ABC):
    @abstractmethod
    async def record(self, action: str, *, actor_id: UUID | None, entity_type: str | None = None,
                     entity_id: str | None = None, before: Mapping[str, Any] | None = None,
                     after: Mapping[str, Any] | None = None, ip: str | None = None) -> None: ...


class RulesRepository(ABC):
    @abstractmethod
    async def list_profiles(self) -> list[SecurityProfile]: ...

    @abstractmethod
    async def get_profile(self, profile_id: UUID) -> SecurityProfile | None: ...

    @abstractmethod
    async def save_profile(self, profile: SecurityProfile, *, new: bool) -> None: ...

    @abstractmethod
    async def delete_profile(self, profile_id: UUID) -> None: ...

    @abstractmethod
    async def profile_in_use(self, profile_id: UUID) -> bool: ...

    @abstractmethod
    async def list_zones(self, camera_id: UUID) -> list[ZoneRule]: ...

    @abstractmethod
    async def get_zone(self, zone_id: UUID) -> tuple[UUID, ZoneRule] | None:
        """(camera_id, zona)."""

    @abstractmethod
    async def save_zone(self, camera_id: UUID, zone: ZoneRule, *, enabled: bool, new: bool) -> None: ...

    @abstractmethod
    async def delete_zone(self, zone_id: UUID) -> None: ...

    @abstractmethod
    async def camera_rules(self, camera_id: UUID) -> CameraRules: ...


class UnitOfWork(ABC):
    users: UserRepository
    roles: RoleRepository
    sessions: SessionRepository
    audit: AuditLog
    cameras: CameraRepository
    rules: RulesRepository
    incidents: IncidentRepository

    @abstractmethod
    async def __aenter__(self) -> Self: ...

    @abstractmethod
    async def __aexit__(self, *exc: object) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...
