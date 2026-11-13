"""Adaptadores SQL de los repositorios de identidad y auditoría."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from security_vision.core.domain.identity import AuthSession, User
from security_vision.core.interfaces.repositories import (
    AuditLog,
    RoleRepository,
    SessionRepository,
    UserRepository,
)

from ..models import AuditLogRow, PermissionRow, RolePermissionRow, RoleRow, SessionRow, UserRoleRow, UserRow


class SqlUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def _roles(self, user_id: UUID) -> list[str]:
        rows = await self.s.execute(
            select(RoleRow.name).join(UserRoleRow, UserRoleRow.role_id == RoleRow.id)
            .where(UserRoleRow.user_id == user_id).order_by(RoleRow.name))
        return list(rows.scalars())

    async def _to_domain(self, row: UserRow) -> User:
        return User(id=row.id, email=row.email, display_name=row.display_name, password_hash=row.password_hash,
                    is_active=row.is_active, roles=await self._roles(row.id), failed_logins=row.failed_logins,
                    locked_until=row.locked_until, last_login_at=row.last_login_at, created_at=row.created_at)

    async def get(self, user_id: UUID) -> User | None:
        row = await self.s.scalar(select(UserRow).where(UserRow.id == user_id, UserRow.deleted_at.is_(None)))
        return await self._to_domain(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        row = await self.s.scalar(
            select(UserRow).where(UserRow.email == email.lower(), UserRow.deleted_at.is_(None)))
        return await self._to_domain(row) if row else None

    async def list(self, offset: int = 0, limit: int = 50) -> list[User]:
        rows = await self.s.scalars(select(UserRow).where(UserRow.deleted_at.is_(None))
                                    .order_by(UserRow.email).offset(offset).limit(limit))
        return [await self._to_domain(r) for r in rows]

    async def count(self) -> int:
        return int(await self.s.scalar(select(func.count()).select_from(UserRow)
                                       .where(UserRow.deleted_at.is_(None))) or 0)

    async def add(self, user: User) -> None:
        self.s.add(UserRow(id=user.id, email=user.email.lower(), display_name=user.display_name,
                           password_hash=user.password_hash, is_active=user.is_active,
                           failed_logins=user.failed_logins))
        await self.s.flush()
        await self.set_roles(user.id, user.roles)

    async def update(self, user: User) -> None:
        await self.s.execute(update(UserRow).where(UserRow.id == user.id).values(
            display_name=user.display_name, password_hash=user.password_hash, is_active=user.is_active,
            failed_logins=user.failed_logins, locked_until=user.locked_until, last_login_at=user.last_login_at))

    async def set_roles(self, user_id: UUID, roles: Sequence[str]) -> None:
        await self.s.execute(delete(UserRoleRow).where(UserRoleRow.user_id == user_id))
        if roles:
            ids = (await self.s.scalars(select(RoleRow.id).where(RoleRow.name.in_(list(roles))))).all()
            self.s.add_all([UserRoleRow(user_id=user_id, role_id=rid) for rid in ids])
        await self.s.flush()

    async def permissions_for(self, user_id: UUID) -> frozenset[str]:
        rows = await self.s.scalars(
            select(RolePermissionRow.permission_code)
            .join(UserRoleRow, UserRoleRow.role_id == RolePermissionRow.role_id)
            .where(UserRoleRow.user_id == user_id).distinct())
        return frozenset(rows)


class SqlRoleRepository(RoleRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def sync(self, roles: Mapping[str, tuple[str, frozenset[str]]], permissions: Sequence[str]) -> None:
        existing_perms = set((await self.s.scalars(select(PermissionRow.code))).all())
        self.s.add_all([PermissionRow(code=p) for p in permissions if p not in existing_perms])
        await self.s.flush()
        for name, (description, perms) in roles.items():
            role = await self.s.scalar(select(RoleRow).where(RoleRow.name == name))
            if role is None:
                role = RoleRow(name=name, description=description, is_system=True)
                self.s.add(role)
                await self.s.flush()
            else:
                role.description = description
            # Los roles de sistema reflejan exactamente el catálogo del código.
            await self.s.execute(delete(RolePermissionRow).where(RolePermissionRow.role_id == role.id))
            self.s.add_all([RolePermissionRow(role_id=role.id, permission_code=p) for p in sorted(perms)])
        await self.s.flush()

    async def list(self) -> list[tuple[str, str, list[str]]]:
        roles = (await self.s.scalars(select(RoleRow).order_by(RoleRow.name))).all()
        out = []
        for r in roles:
            perms = (await self.s.scalars(select(RolePermissionRow.permission_code)
                                          .where(RolePermissionRow.role_id == r.id)
                                          .order_by(RolePermissionRow.permission_code))).all()
            out.append((r.name, r.description, list(perms)))
        return out

    async def existing(self, names: Sequence[str]) -> set[str]:
        return set((await self.s.scalars(select(RoleRow.name).where(RoleRow.name.in_(list(names))))).all())


class SqlSessionRepository(SessionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    @staticmethod
    def _to_domain(r: SessionRow) -> AuthSession:
        return AuthSession(id=r.id, user_id=r.user_id, refresh_token_hash=r.refresh_token_hash,
                           previous_refresh_hash=r.previous_refresh_hash, expires_at=r.expires_at,
                           revoked_at=r.revoked_at, user_agent=r.user_agent, ip=r.ip)

    async def add(self, session: AuthSession) -> None:
        self.s.add(SessionRow(id=session.id, user_id=session.user_id, refresh_token_hash=session.refresh_token_hash,
                              previous_refresh_hash=session.previous_refresh_hash, expires_at=session.expires_at,
                              user_agent=session.user_agent, ip=session.ip))
        await self.s.flush()

    async def get(self, session_id: UUID) -> AuthSession | None:
        row = await self.s.get(SessionRow, session_id)
        return self._to_domain(row) if row else None

    async def update(self, session: AuthSession) -> None:
        await self.s.execute(update(SessionRow).where(SessionRow.id == session.id).values(
            refresh_token_hash=session.refresh_token_hash, previous_refresh_hash=session.previous_refresh_hash,
            expires_at=session.expires_at, revoked_at=session.revoked_at))

    async def revoke_all_for_user(self, user_id: UUID, at: datetime) -> int:
        res = await self.s.execute(update(SessionRow).where(SessionRow.user_id == user_id,
                                                            SessionRow.revoked_at.is_(None)).values(revoked_at=at))
        return res.rowcount or 0


class SqlAuditLog(AuditLog):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def record(self, action: str, *, actor_id: UUID | None, entity_type: str | None = None,
                     entity_id: str | None = None, before: Mapping[str, Any] | None = None,
                     after: Mapping[str, Any] | None = None, ip: str | None = None) -> None:
        self.s.add(AuditLogRow(action=action, actor_id=actor_id, entity_type=entity_type, entity_id=entity_id,
                               before=dict(before) if before else None, after=dict(after) if after else None,
                               ip=ip))
        await self.s.flush()
