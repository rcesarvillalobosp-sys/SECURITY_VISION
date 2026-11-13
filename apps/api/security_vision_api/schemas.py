"""Contratos HTTP (entrada validada, salida sin datos sensibles)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class MeOut(BaseModel):
    user_id: UUID
    email: str
    roles: list[str]
    permissions: list[str]


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_active: bool
    roles: list[str]
    last_login_at: datetime | None


class UserCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1024)
    roles: list[str] = Field(default_factory=list, max_length=10)


class RolesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[str] = Field(max_length=10)


class RoleOut(BaseModel):
    name: str
    description: str
    permissions: list[str]


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int
