"""Administración de usuarios y roles."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from security_vision.core.domain.identity import Permission, Principal, User

from ..container import Container
from ..deps import client_ip, get_container, require
from ..schemas import Page, RoleOut, RolesIn, UserCreateIn, UserOut

router = APIRouter(prefix="/api/v1", tags=["users"])
C = Annotated[Container, Depends(get_container)]


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, display_name=u.display_name, is_active=u.is_active, roles=u.roles,
                   last_login_at=u.last_login_at)


@router.get("/users", response_model=Page[UserOut])
async def list_users(container: C, _: Annotated[Principal, Depends(require(Permission.USERS_READ))],
                     offset: Annotated[int, Query(ge=0)] = 0,
                     limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Page[UserOut]:
    users, total = await container.users.list_users(offset, limit)
    return Page[UserOut](items=[_out(u) for u in users], total=total, offset=offset, limit=limit)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateIn, request: Request, container: C,
                      principal: Annotated[Principal, Depends(require(Permission.USERS_WRITE))]) -> UserOut:
    user = await container.users.create_user(email=body.email, display_name=body.display_name,
                                             password=body.password, roles=body.roles, actor=principal,
                                             ip=client_ip(request))
    return _out(user)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: UUID, container: C,
                   _: Annotated[Principal, Depends(require(Permission.USERS_READ))]) -> UserOut:
    return _out(await container.users.get(user_id))


@router.put("/users/{user_id}/roles", response_model=UserOut)
async def set_roles(user_id: UUID, body: RolesIn, request: Request, container: C,
                    principal: Annotated[Principal, Depends(require(Permission.USERS_WRITE))]) -> UserOut:
    return _out(await container.users.set_roles(user_id, body.roles, actor=principal, ip=client_ip(request)))


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(container: C, _: Annotated[Principal, Depends(require(Permission.ROLES_READ))]
                     ) -> list[RoleOut]:
    return [RoleOut(name=n, description=d, permissions=p) for n, d, p in await container.users.list_roles()]
