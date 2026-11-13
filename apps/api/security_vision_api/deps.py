"""Dependencias FastAPI: contenedor, principal autenticado y control de permisos."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from security_vision.core.domain.errors import AuthenticationError
from security_vision.core.domain.identity import Permission, Principal

from .container import Container

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def get_principal(
    container: Annotated[Container, Depends(get_container)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no autenticado", headers={"WWW-Authenticate": "Bearer"})
    try:
        return await container.auth.authenticate(credentials.credentials)
    except AuthenticationError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido o sesión revocada",
                            headers={"WWW-Authenticate": "Bearer"}) from None


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(*permissions: Permission) -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def checker(principal: CurrentPrincipal) -> Principal:
        missing = [p for p in permissions if not principal.can(p)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"permiso requerido: {', '.join(missing)}")
        return principal

    return checker
