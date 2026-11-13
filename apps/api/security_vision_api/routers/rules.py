"""Perfiles de seguridad (qué EPP se exige y con qué umbrales) y zonas por cámara."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from security_vision.core.domain.compliance import EVALUABLE_PPE, RuleThresholds, SecurityProfile, ZoneRule
from security_vision.core.domain.identity import Permission, Principal

from ..container import Container
from ..deps import client_ip, get_container, require

router = APIRouter(prefix="/api/v1", tags=["rules"])
C = Annotated[Container, Depends(get_container)]
Reader = Annotated[Principal, Depends(require(Permission.CAMERAS_READ))]
RulesWriter = Annotated[Principal, Depends(require(Permission.RULES_WRITE))]
ZonesWriter = Annotated[Principal, Depends(require(Permission.ZONES_WRITE))]


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    required_ppe: list[str] = Field(min_length=1, max_length=len(EVALUABLE_PPE))
    thresholds: dict[str, Any] | None = None


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    required_ppe: list[str] | None = Field(default=None, min_length=1, max_length=len(EVALUABLE_PPE))
    thresholds: dict[str, Any] | None = None


class ProfileOut(BaseModel):
    id: str
    name: str
    required_ppe: list[str]
    thresholds: dict[str, Any]
    version: int


class ZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    polygon: list[list[float]] = Field(min_length=3, max_length=64)
    profile_id: UUID | None = None
    kind: str = Field(default="ppe", pattern="^(ppe|restricted)$")


class ZonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    polygon: list[list[float]] | None = Field(default=None, min_length=3, max_length=64)
    profile_id: UUID | None = None
    kind: str | None = Field(default=None, pattern="^(ppe|restricted)$")
    enabled: bool | None = None


class ZoneOut(BaseModel):
    id: str
    name: str
    kind: str
    polygon: list[list[float]]
    profile_id: str | None


class Catalog(BaseModel):
    evaluable_ppe: list[str]
    default_thresholds: dict[str, Any]


def _p(p: SecurityProfile) -> ProfileOut:
    return ProfileOut(id=p.id, name=p.name, required_ppe=list(p.required_ppe), thresholds=p.thresholds.to_dict(),
                      version=p.version)


def _z(z: ZoneRule) -> ZoneOut:
    return ZoneOut(id=z.zone_id, name=z.name, kind=z.kind, polygon=[list(p) for p in z.polygon],
                   profile_id=z.profile.id if z.profile else None)


@router.get("/security-profiles/catalog", response_model=Catalog)
async def catalog(_: Reader) -> Catalog:
    return Catalog(evaluable_ppe=list(EVALUABLE_PPE), default_thresholds=RuleThresholds().to_dict())


@router.get("/security-profiles", response_model=list[ProfileOut])
async def list_profiles(container: C, _: Reader) -> list[ProfileOut]:
    return [_p(p) for p in await container.rules.list_profiles()]


@router.post("/security-profiles", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(body: ProfileIn, request: Request, container: C, principal: RulesWriter) -> ProfileOut:
    p = await container.rules.create_profile(body.name, body.required_ppe, body.thresholds, actor=principal,
                                             ip=client_ip(request))
    return _p(p)


@router.patch("/security-profiles/{profile_id}", response_model=ProfileOut)
async def update_profile(profile_id: UUID, body: ProfilePatch, request: Request, container: C,
                         principal: RulesWriter) -> ProfileOut:
    p = await container.rules.update_profile(profile_id, body.model_dump(exclude_unset=True), actor=principal,
                                             ip=client_ip(request))
    return _p(p)


@router.delete("/security-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: UUID, request: Request, container: C, principal: RulesWriter) -> Response:
    await container.rules.delete_profile(profile_id, actor=principal, ip=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cameras/{camera_id}/zones", response_model=list[ZoneOut])
async def list_zones(camera_id: UUID, container: C, _: Reader) -> list[ZoneOut]:
    return [_z(z) for z in await container.rules.list_zones(camera_id)]


@router.post("/cameras/{camera_id}/zones", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
async def create_zone(camera_id: UUID, body: ZoneIn, request: Request, container: C,
                      principal: ZonesWriter) -> ZoneOut:
    z = await container.rules.create_zone(camera_id, body.name, body.polygon, body.profile_id, body.kind,
                                          actor=principal, ip=client_ip(request))
    return _z(z)


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
async def update_zone(zone_id: UUID, body: ZonePatch, request: Request, container: C,
                      principal: ZonesWriter) -> ZoneOut:
    z = await container.rules.update_zone(zone_id, body.model_dump(exclude_unset=True), actor=principal,
                                          ip=client_ip(request))
    return _z(z)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(zone_id: UUID, request: Request, container: C, principal: ZonesWriter) -> Response:
    await container.rules.delete_zone(zone_id, actor=principal, ip=client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
