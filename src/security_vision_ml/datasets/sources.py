"""Manifiestos de fuentes de datos: licencia, procedencia, descarga y mapeo de clases.

Cada fuente se describe en un YAML en ``ml/datasets/sources/``. El manifiesto es la
única fuente de verdad sobre qué se puede hacer con un dataset; el código nunca
infiere permisos a partir del nombre de la licencia.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from security_vision.core.domain.taxonomy import CanonicalClass


class UsePurpose(StrEnum):
    COMMERCIAL_TRAINING = "commercial_training"
    COMMERCIAL_EVALUATION = "commercial_evaluation"
    RESEARCH = "research"


COMMERCIAL_PURPOSES = {UsePurpose.COMMERCIAL_TRAINING, UsePurpose.COMMERCIAL_EVALUATION}


class LicenseStatus(StrEnum):
    VERIFIED = "verified"  # licencia leída en la fuente oficial y procedencia clara
    UNCLEAR_PROVENANCE = "unclear_provenance"  # licencia declarada, origen de imágenes desconocido
    UNVERIFIED = "unverified"  # no se pudo leer la licencia


class MappingStatus(StrEnum):
    DIRECT = "direct"  # equivalencia semántica clara
    NEEDS_VISUAL_REVIEW = "needs_visual_review"  # requiere inspección humana antes de usarse
    EXCLUDED = "excluded"  # clase fuera de la taxonomía o no equivalente


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LicenseInfo(Strict):
    name: str
    spdx: str | None = None
    url: str | None = None
    evidence_url: str  # página donde se leyó la licencia
    verified_on: date | None = None
    status: LicenseStatus
    commercial_use: Literal["allowed", "forbidden", "unknown"]
    share_alike: bool = False
    attribution_required: bool = True
    attribution_text: str | None = None
    notes: str | None = None


class Provenance(Strict):
    publisher: str
    homepage: str
    upstream: list[str] = Field(default_factory=list)
    image_origin: str | None = None
    notes: str | None = None


class DownloadSpec(Strict):
    url: str
    filename: str
    format: Literal["yolo", "coco"]
    expected_size: int | None = None
    sha256: str | None = None


class MappingRule(Strict):
    target: CanonicalClass | None = None
    status: MappingStatus
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> MappingRule:
        if self.status is MappingStatus.EXCLUDED and self.target is not None:
            raise ValueError("una clase excluida no puede tener destino")
        if self.status is not MappingStatus.EXCLUDED and self.target is None:
            raise ValueError("un mapeo no excluido necesita destino")
        return self


class MappingReview(Strict):
    source_class: str
    decision: Literal["approved", "rejected"]
    reviewer: str
    reviewed_on: date
    sample_size: int = Field(gt=0)
    # Si se indica, la aprobación solo vale para imágenes re-etiquetadas en esa corrección.
    requires_correction: str | None = None
    notes: str | None = None


class SourceManifest(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    name: str
    version: str
    license: LicenseInfo
    provenance: Provenance
    download: DownloadSpec | None = None
    # Formato de fuentes sin descarga automática (p. ej. exportaciones de CVAT colocadas a mano).
    local_format: Literal["yolo", "coco"] = "yolo"
    allowed_purposes: frozenset[UsePurpose] = frozenset()
    class_mapping: dict[str, MappingRule]
    reviews: list[MappingReview] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _purposes_consistent_with_license(self) -> SourceManifest:
        if self.license.status is not LicenseStatus.VERIFIED and self.allowed_purposes:
            raise ValueError(f"{self.id}: sin licencia verificada no puede autorizarse ningún uso")
        if self.license.commercial_use != "allowed" and self.allowed_purposes & COMMERCIAL_PURPOSES:
            raise ValueError(f"{self.id}: la licencia no permite uso comercial")
        for review in self.reviews:
            if review.source_class not in self.class_mapping:
                raise ValueError(f"{self.id}: revisión de clase desconocida {review.source_class!r}")
        return self

    def is_authorized(self, purpose: UsePurpose) -> bool:
        return purpose in self.allowed_purposes

    def effective_mapping(self, source_class: str, applied_corrections: frozenset[str] = frozenset()
                          ) -> MappingRule:
        """Mapeo aplicable teniendo en cuenta las revisiones visuales registradas.

        ``applied_corrections``: correcciones aplicadas a la imagen concreta (ver corrections.py).
        """
        rule = self.class_mapping.get(source_class)
        if rule is None:
            return MappingRule(status=MappingStatus.EXCLUDED, reason="clase no declarada en el manifiesto")
        if rule.status is not MappingStatus.NEEDS_VISUAL_REVIEW:
            return rule
        decisions = [r for r in self.reviews if r.source_class == source_class]
        if decisions and decisions[-1].decision == "approved":
            needed = decisions[-1].requires_correction
            if needed is not None and needed not in applied_corrections:
                return MappingRule(target=rule.target, status=MappingStatus.NEEDS_VISUAL_REVIEW,
                                   reason=f"aprobado solo tras la corrección '{needed}' (pendiente en esta imagen)")
            return MappingRule(target=rule.target, status=MappingStatus.DIRECT, reason="aprobado tras revisión")
        if decisions and decisions[-1].decision == "rejected":
            return MappingRule(status=MappingStatus.EXCLUDED, reason="rechazado en revisión visual")
        return rule


def load_manifest(path: Path) -> SourceManifest:
    with path.open(encoding="utf-8") as fh:
        return SourceManifest.model_validate(yaml.safe_load(fh))


def load_all(directory: Path) -> dict[str, SourceManifest]:
    manifests: dict[str, SourceManifest] = {}
    for path in sorted(directory.glob("*.yaml")):
        m = load_manifest(path)
        if m.id in manifests:
            raise ValueError(f"id de fuente duplicado: {m.id}")
        manifests[m.id] = m
    return manifests


class CompatibilityError(Exception):
    pass


def check_combination(manifests: list[SourceManifest], purpose: UsePurpose) -> None:
    """Impide mezclar fuentes que no autorizan el mismo uso o con cláusulas incompatibles."""
    blocked = [m.id for m in manifests if not m.is_authorized(purpose)]
    if blocked:
        raise CompatibilityError(f"fuentes no autorizadas para {purpose}: {', '.join(blocked)}")
    if purpose in COMMERCIAL_PURPOSES:
        share_alike = [m.id for m in manifests if m.license.share_alike]
        if share_alike:
            raise CompatibilityError(
                f"fuentes share-alike no se combinan automáticamente en uso comercial: {', '.join(share_alike)}"
            )
