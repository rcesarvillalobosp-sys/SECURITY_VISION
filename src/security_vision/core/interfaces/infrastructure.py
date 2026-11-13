"""Puertos de infraestructura: almacenamiento de objetos, bus de eventos, alertas y seguridad."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import BinaryIO, ClassVar

from ..events.base import DomainEvent


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    content_type: str
    created_at: datetime


class ObjectStorage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes | BinaryIO, content_type: str) -> StoredObject: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def stat(self, key: str) -> tuple[int, datetime, str]:
        """(tamaño, última modificación UTC, content-type). ``FileNotFoundError`` si no existe."""

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def signed_url(self, key: str, ttl: timedelta) -> str: ...

    @abstractmethod
    def list(self, prefix: str, older_than: datetime | None = None) -> Iterator[StoredObject]: ...


class MessageBus(ABC):
    """Entrega al menos una vez: los consumidores deben ser idempotentes (event_id)."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...

    @abstractmethod
    def subscribe(self, event_types: Sequence[str], group: str) -> AsyncIterator[DomainEvent]: ...

    @abstractmethod
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Alert:
    incident_id: str
    title: str
    body: str
    severity: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    ok: bool
    detail: str = ""


class AlertChannel(ABC):
    channel_type: ClassVar[str]

    @abstractmethod
    async def send(self, alert: Alert) -> DeliveryResult: ...


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, password: str) -> str: ...

    @abstractmethod
    def verify(self, password_hash: str, password: str) -> bool: ...

    @abstractmethod
    def needs_rehash(self, password_hash: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: str
    session_id: str
    email: str
    roles: list[str]
    permissions: list[str]
    expires_at: datetime


class TokenService(ABC):
    @abstractmethod
    def issue_access_token(self, claims: AccessTokenClaims) -> str: ...

    @abstractmethod
    def decode_access_token(self, token: str) -> AccessTokenClaims:
        """Lanza ``AuthenticationError`` si el token es inválido o ha expirado."""


class SecretCipher(ABC):
    """Cifrado simétrico autenticado para secretos en reposo (p. ej. credenciales RTSP)."""

    @abstractmethod
    def encrypt(self, plaintext: str, associated_data: bytes = b"") -> bytes: ...

    @abstractmethod
    def decrypt(self, ciphertext: bytes, associated_data: bytes = b"") -> str: ...
