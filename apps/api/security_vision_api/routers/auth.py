"""Autenticación. El refresh token viaja SOLO en una cookie httpOnly (no accesible desde JS)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from security_vision.core.configuration.settings import Environment
from security_vision.core.domain.errors import AccountLockedError, AuthenticationError
from security_vision.modules.users.services import TokenPair

from ..container import Container
from ..deps import CurrentPrincipal, client_ip, get_container
from ..schemas import LoginIn, MeOut, TokenOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
REFRESH_COOKIE = "sv_refresh"
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, container: Container, pair: TokenPair) -> None:
    response.set_cookie(
        REFRESH_COOKIE, pair.refresh_token, expires=pair.refresh_expires_at, path=COOKIE_PATH, httponly=True,
        secure=container.settings.environment is Environment.PRODUCTION, samesite="strict",
    )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response,
                container: Annotated[Container, Depends(get_container)]) -> TokenOut:
    try:
        pair = await container.auth.login(body.email, body.password, ip=client_ip(request),
                                          user_agent=request.headers.get("user-agent"))
    except AccountLockedError:
        container.metrics.logins.labels("locked").inc()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "cuenta bloqueada temporalmente") from None
    except AuthenticationError:
        container.metrics.logins.labels("failed").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credenciales inválidas") from None
    container.metrics.logins.labels("success").inc()
    _set_refresh_cookie(response, container, pair)
    return TokenOut(access_token=pair.access_token, expires_at=pair.access_expires_at)


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response, container: Annotated[Container, Depends(get_container)],
                  sv_refresh: Annotated[str | None, Cookie()] = None) -> TokenOut:
    if not sv_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sin sesión")
    try:
        pair = await container.auth.refresh(sv_refresh, ip=client_ip(request))
    except AuthenticationError:
        response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sesión inválida") from None
    _set_refresh_cookie(response, container, pair)
    return TokenOut(access_token=pair.access_token, expires_at=pair.access_expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: CurrentPrincipal, request: Request, response: Response,
                 container: Annotated[Container, Depends(get_container)]) -> Response:
    await container.auth.logout(principal, ip=client_ip(request))
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal) -> MeOut:
    return MeOut(user_id=principal.user_id, email=principal.email, roles=sorted(principal.roles),
                 permissions=sorted(principal.permissions))
