"""Casos de uso de identidad: autenticación, sesiones con rotación de refresh token, usuarios y RBAC.

Depende solo de puertos del núcleo (UnitOfWork, PasswordHasher, TokenService).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from security_vision.core.domain.errors import (
    AccountLockedError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from security_vision.core.domain.identity import DEFAULT_ROLES, AuthSession, Permission, Principal, User
from security_vision.core.domain.ids import uuid7
from security_vision.core.interfaces.infrastructure import AccessTokenClaims, PasswordHasher, TokenService
from security_vision.core.interfaces.repositories import UnitOfWork

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 12


def utcnow() -> datetime:
    return datetime.now(UTC)


def _hash_refresh(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"la contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    if classes < 3:
        raise ValidationError("la contraseña debe combinar al menos 3 de: minúsculas, mayúsculas, dígitos, símbolos")


@dataclass(frozen=True)
class AuthPolicy:
    access_token_ttl: timedelta = timedelta(minutes=15)
    refresh_token_ttl: timedelta = timedelta(days=7)
    max_failed_logins: int = 5
    lockout: timedelta = timedelta(minutes=15)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str  # "<session_id>.<secreto>"
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, uow: Callable[[], UnitOfWork], hasher: PasswordHasher, tokens: TokenService,
                 policy: AuthPolicy, clock: Callable[[], datetime] = utcnow) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens
        self._policy = policy
        self._now = clock
        # Hash ficticio: igualar el coste de tiempo cuando el usuario no existe (evita enumeración).
        self._dummy_hash = hasher.hash(secrets.token_urlsafe(16))

    async def login(self, email: str, password: str, *, ip: str | None = None,
                    user_agent: str | None = None) -> TokenPair:
        now = self._now()
        async with self._uow() as uow:
            user = await uow.users.get_by_email(email.strip().lower())
            if user is None or not user.is_active:
                self._hasher.verify(self._dummy_hash, password)
                await uow.audit.record("auth.login_failed", actor_id=None, entity_type="user",
                                       after={"email": email.strip().lower()[:320], "reason": "unknown_or_inactive"},
                                       ip=ip)
                await uow.commit()
                raise AuthenticationError("credenciales inválidas")
            if user.locked_until and user.locked_until > now:
                await uow.audit.record("auth.login_locked", actor_id=user.id, entity_type="user",
                                       entity_id=str(user.id), ip=ip)
                await uow.commit()
                raise AccountLockedError("cuenta bloqueada temporalmente")
            if not self._hasher.verify(user.password_hash, password):
                user.failed_logins += 1
                if user.failed_logins >= self._policy.max_failed_logins:
                    user.locked_until = now + self._policy.lockout
                    user.failed_logins = 0
                await uow.users.update(user)
                await uow.audit.record("auth.login_failed", actor_id=user.id, entity_type="user",
                                       entity_id=str(user.id), after={"reason": "bad_password"}, ip=ip)
                await uow.commit()
                raise AuthenticationError("credenciales inválidas")
            if self._hasher.needs_rehash(user.password_hash):
                user.password_hash = self._hasher.hash(password)
            user.failed_logins = 0
            user.locked_until = None
            user.last_login_at = now
            await uow.users.update(user)
            secret = secrets.token_urlsafe(32)
            session = AuthSession(id=uuid7(), user_id=user.id, refresh_token_hash=_hash_refresh(secret),
                                  previous_refresh_hash=None, expires_at=now + self._policy.refresh_token_ttl,
                                  user_agent=(user_agent or "")[:400] or None, ip=ip)
            await uow.sessions.add(session)
            pair = await self._issue(uow, user, session, secret, now)
            await uow.audit.record("auth.login", actor_id=user.id, entity_type="session",
                                   entity_id=str(session.id), ip=ip)
            await uow.commit()
            return pair

    async def refresh(self, refresh_token: str, *, ip: str | None = None) -> TokenPair:
        """Rotación: cada refresh invalida el anterior. Reutilizar uno ya rotado revoca la sesión."""
        now = self._now()
        session_id, secret = self._split(refresh_token)
        async with self._uow() as uow:
            session = await uow.sessions.get(session_id)
            if session is None or session.revoked_at is not None or session.expires_at <= now:
                raise AuthenticationError("sesión inválida")
            presented = _hash_refresh(secret)
            if session.previous_refresh_hash and hmac.compare_digest(presented, session.previous_refresh_hash):
                session.revoked_at = now
                await uow.sessions.update(session)
                await uow.audit.record("auth.refresh_reuse_detected", actor_id=session.user_id,
                                       entity_type="session", entity_id=str(session.id), ip=ip)
                await uow.commit()
                raise AuthenticationError("sesión inválida")
            if not hmac.compare_digest(presented, session.refresh_token_hash):
                raise AuthenticationError("sesión inválida")
            user = await uow.users.get(session.user_id)
            if user is None or not user.is_active:
                raise AuthenticationError("sesión inválida")
            new_secret = secrets.token_urlsafe(32)
            session.previous_refresh_hash = session.refresh_token_hash
            session.refresh_token_hash = _hash_refresh(new_secret)
            await uow.sessions.update(session)
            pair = await self._issue(uow, user, session, new_secret, now)
            await uow.commit()
            return pair

    async def logout(self, principal: Principal, *, ip: str | None = None) -> None:
        async with self._uow() as uow:
            session = await uow.sessions.get(principal.session_id)
            if session and session.revoked_at is None:
                session.revoked_at = self._now()
                await uow.sessions.update(session)
                await uow.audit.record("auth.logout", actor_id=principal.user_id, entity_type="session",
                                       entity_id=str(session.id), ip=ip)
                await uow.commit()

    async def authenticate(self, access_token: str) -> Principal:
        """Valida el token y que la sesión siga activa (permite revocar antes de que expire el JWT)."""
        claims = self._tokens.decode_access_token(access_token)
        async with self._uow() as uow:
            session = await uow.sessions.get(UUID(claims.session_id))
            if session is None or session.revoked_at is not None:
                raise AuthenticationError("sesión revocada")
        return Principal(user_id=UUID(claims.user_id), session_id=UUID(claims.session_id), email=claims.email,
                         roles=frozenset(claims.roles), permissions=frozenset(claims.permissions))

    async def _issue(self, uow: UnitOfWork, user: User, session: AuthSession, secret: str,
                     now: datetime) -> TokenPair:
        perms = await uow.users.permissions_for(user.id)
        expires = now + self._policy.access_token_ttl
        token = self._tokens.issue_access_token(AccessTokenClaims(
            user_id=str(user.id), session_id=str(session.id), email=user.email, roles=sorted(user.roles),
            permissions=sorted(perms), expires_at=expires))
        return TokenPair(token, expires, f"{session.id}.{secret}", session.expires_at)

    @staticmethod
    def _split(refresh_token: str) -> tuple[UUID, str]:
        try:
            sid, secret = refresh_token.split(".", 1)
            return UUID(sid), secret
        except ValueError as exc:
            raise AuthenticationError("sesión inválida") from exc


class UserService:
    def __init__(self, uow: Callable[[], UnitOfWork], hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def create_user(self, *, email: str, display_name: str, password: str, roles: Sequence[str],
                          actor: Principal | None, ip: str | None = None) -> User:
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise ValidationError("email inválido")
        validate_password(password)
        async with self._uow() as uow:
            if await uow.users.get_by_email(email):
                raise ConflictError("ya existe un usuario con ese email")
            missing = set(roles) - await uow.roles.existing(list(roles))
            if missing:
                raise ValidationError(f"roles inexistentes: {', '.join(sorted(missing))}")
            user = User(id=uuid7(), email=email, display_name=display_name.strip()[:200],
                        password_hash=self._hasher.hash(password), is_active=True, roles=sorted(set(roles)))
            await uow.users.add(user)
            await uow.audit.record("user.created", actor_id=actor.user_id if actor else None, entity_type="user",
                                   entity_id=str(user.id), after={"email": email, "roles": user.roles}, ip=ip)
            await uow.commit()
            return user

    async def set_roles(self, user_id: UUID, roles: Sequence[str], *, actor: Principal,
                        ip: str | None = None) -> User:
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise NotFoundError("usuario no encontrado")
            missing = set(roles) - await uow.roles.existing(list(roles))
            if missing:
                raise ValidationError(f"roles inexistentes: {', '.join(sorted(missing))}")
            if user.id == actor.user_id and "admin" in user.roles and "admin" not in roles:
                raise ValidationError("no puedes quitarte a ti mismo el rol admin")
            before = list(user.roles)
            await uow.users.set_roles(user_id, sorted(set(roles)))
            # Los permisos cambian: se cierran las sesiones del usuario para que el cambio sea inmediato.
            await uow.sessions.revoke_all_for_user(user_id, utcnow())
            await uow.audit.record("user.roles_changed", actor_id=actor.user_id, entity_type="user",
                                   entity_id=str(user_id), before={"roles": before},
                                   after={"roles": sorted(set(roles))}, ip=ip)
            await uow.commit()
            user.roles = sorted(set(roles))
            return user

    async def list_users(self, offset: int, limit: int) -> tuple[list[User], int]:
        async with self._uow() as uow:
            return await uow.users.list(offset, limit), await uow.users.count()

    async def get(self, user_id: UUID) -> User:
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
        if user is None:
            raise NotFoundError("usuario no encontrado")
        return user

    async def list_roles(self) -> list[tuple[str, str, list[str]]]:
        async with self._uow() as uow:
            return await uow.roles.list()


async def bootstrap(uow_factory: Callable[[], UnitOfWork], hasher: PasswordHasher,
                    admin_email: str | None, admin_password: str | None) -> dict[str, object]:
    """Idempotente: sincroniza permisos/roles del catálogo y crea el primer admin si no hay usuarios."""
    roles = {name: (desc, frozenset(str(p) for p in perms)) for name, (desc, perms) in DEFAULT_ROLES.items()}
    async with uow_factory() as uow:
        await uow.roles.sync(roles, [str(p) for p in Permission])
        await uow.commit()
        has_users = await uow.users.count() > 0
    created = None
    if not has_users and admin_email and admin_password:
        user = await UserService(uow_factory, hasher).create_user(
            email=admin_email, display_name="Administrador", password=admin_password, roles=["admin"], actor=None)
        created = user.email
    from security_vision.modules.security_rules.service import ensure_default_profile

    profile = await ensure_default_profile(uow_factory)
    return {"roles": sorted(roles), "permissions": len(Permission), "admin_created": created,
            "users_existed": has_users, "default_profile_created": profile}
