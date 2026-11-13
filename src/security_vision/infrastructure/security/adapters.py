"""Adaptadores de seguridad: Argon2id, JWT (HS256) y AES-256-GCM."""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime

import jwt
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security_vision.core.domain.errors import AuthenticationError
from security_vision.core.interfaces.infrastructure import (
    AccessTokenClaims,
    PasswordHasher,
    SecretCipher,
    TokenService,
)


class Argon2PasswordHasher(PasswordHasher):
    """Parámetros por defecto de argon2-cffi (perfil RFC 9106 de baja memoria)."""

    def __init__(self) -> None:
        self._ph = _Argon2()

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._ph.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._ph.check_needs_rehash(password_hash)


class JwtTokenService(TokenService):
    ALGORITHM = "HS256"

    def __init__(self, secret: str, issuer: str) -> None:
        if len(secret) < 32:
            raise ValueError("el secreto JWT debe tener al menos 32 caracteres")
        self._secret = secret
        self._issuer = issuer

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        payload = {
            "iss": self._issuer,
            "sub": claims.user_id,
            "sid": claims.session_id,
            "email": claims.email,
            "roles": claims.roles,
            "perms": claims.permissions,
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int(claims.expires_at.timestamp()),
            "typ": "access",
        }
        return jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            p = jwt.decode(token, self._secret, algorithms=[self.ALGORITHM], issuer=self._issuer,
                           options={"require": ["exp", "sub", "sid", "iss"]})
        except jwt.PyJWTError as exc:
            raise AuthenticationError("token inválido") from exc
        if p.get("typ") != "access":
            raise AuthenticationError("token inválido")
        return AccessTokenClaims(user_id=p["sub"], session_id=p["sid"], email=p.get("email", ""),
                                 roles=list(p.get("roles", [])), permissions=list(p.get("perms", [])),
                                 expires_at=datetime.fromtimestamp(p["exp"], UTC))


class AesGcmCipher(SecretCipher):
    """Formato: versión(1 byte) || nonce(12) || ciphertext+tag."""

    VERSION = b"\x01"

    def __init__(self, key_b64: str) -> None:
        key = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
        if len(key) != 32:
            raise ValueError("SV_SECRETS_KEY debe ser 32 bytes en base64 url-safe")
        self._aead = AESGCM(key)

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")

    def encrypt(self, plaintext: str, associated_data: bytes = b"") -> bytes:
        nonce = os.urandom(12)
        return self.VERSION + nonce + self._aead.encrypt(nonce, plaintext.encode(), associated_data)

    def decrypt(self, ciphertext: bytes, associated_data: bytes = b"") -> str:
        if ciphertext[:1] != self.VERSION:
            raise ValueError("versión de cifrado no soportada")
        nonce, body = ciphertext[1:13], ciphertext[13:]
        return self._aead.decrypt(nonce, body, associated_data).decode()
