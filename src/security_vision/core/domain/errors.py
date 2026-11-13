"""Errores de dominio. La capa API los traduce a HTTP; el dominio no conoce HTTP."""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    code = "conflict"


class ValidationError(DomainError):
    code = "validation_error"


class AuthenticationError(DomainError):
    """Credenciales inválidas. El mensaje es deliberadamente genérico."""

    code = "authentication_failed"


class AccountLockedError(AuthenticationError):
    code = "account_locked"


class PermissionDeniedError(DomainError):
    code = "permission_denied"
